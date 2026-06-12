"""Booking-field extraction.

Strategy: rule-based first (regex + dateparser) — covers the majority of
enquiry emails with zero API cost. Only when the rules can't fill every
required field AND an Anthropic API key is configured do we fall back to
claude-haiku (the cheapest Claude model) for a single extraction call.
"""

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, time

import dateparser

from booking_pipeline.config import Settings
from booking_pipeline.email_ingestion import IncomingEmail
from booking_pipeline.logging_conf import get_logger

logger = get_logger(__name__)

REQUIRED_FIELDS = ("client_name", "service_type", "requested_date", "requested_time")

# Synonyms mapped onto canonical service types (the keys of SERVICE_PRICES)
_SERVICE_SYNONYMS: dict[str, str] = {
    "consultation": "consultation",
    "consult": "consultation",
    "advice session": "consultation",
    "installation": "installation",
    "install": "installation",
    "fitting": "installation",
    "maintenance": "maintenance",
    "service visit": "maintenance",
    "servicing": "maintenance",
    "inspection": "inspection",
    "inspect": "inspection",
    "survey": "inspection",
}

_TIME_RE = re.compile(
    r"\b(?:at|around|from)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"<?([\w.+-]+@[\w-]+\.[\w.]+)>?")
_NAME_FROM_SENDER_RE = re.compile(r'^\s*"?([^"<]+?)"?\s*<')
# prefix is case-insensitive but the captured name must be capitalised
_NAME_IN_BODY_RE = re.compile(
    r"\b(?i:my name is|this is|i am|i'm)\s+([A-Z]\w+(?:\s+[A-Z]\w*)?)"
)
_LOCATION_RES = (
    re.compile(r"(?:location|address|site)\s*[:\-]\s*(.+)", re.IGNORECASE),
    re.compile(
        r"\bat\s+(\d+\s[\w\s]+?(?:street|st|road|rd|avenue|ave|lane|ln|close|drive|way)\b[^,.\n]*)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:premises|office|workshop|home)\s+in\s+([A-Z][\w\s]{2,40}?)(?:[,.\n]|$)"),
)


@dataclass(frozen=True)
class ExtractionResult:
    client_name: str | None = None
    client_email: str | None = None
    service_type: str | None = None
    requested_date: date | None = None
    requested_time: time | None = None
    location: str | None = None
    method: str = "rules"  # rules | llm | failed
    missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def confidence(self) -> float:
        found = sum(1 for f in REQUIRED_FIELDS if getattr(self, f) is not None)
        return found / len(REQUIRED_FIELDS)

    @property
    def complete(self) -> bool:
        return self.confidence == 1.0


def extract_fields(email: IncomingEmail, settings: Settings) -> ExtractionResult:
    """Rule-based extraction with optional Claude fallback."""
    result = _extract_with_rules(email)
    if result.complete:
        logger.info("rules extracted all fields for thread %s", email.thread_id)
        return result

    if settings.anthropic_api_key:
        logger.info(
            "rules incomplete (missing: %s) — falling back to %s",
            ", ".join(result.missing),
            settings.claude_model,
        )
        llm = _extract_with_claude(email, settings)
        if llm is not None:
            merged = _merge(result, llm)
            return replace(merged, method="llm", missing=_missing(merged))

    logger.info(
        "extraction incomplete for thread %s (missing: %s), no fallback used",
        email.thread_id,
        ", ".join(result.missing),
    )
    return result


# --- rule-based ---------------------------------------------------------------


def _extract_with_rules(email: IncomingEmail) -> ExtractionResult:
    text = f"{email.subject}\n{email.body}"

    result = ExtractionResult(
        client_name=_find_name(email),
        client_email=_find_email(email.sender),
        service_type=_find_service(text),
        requested_date=_find_date(text),
        requested_time=_find_time(text),
        location=_find_location(email.body),
    )
    return replace(result, missing=_missing(result))


def _find_name(email: IncomingEmail) -> str | None:
    m = _NAME_FROM_SENDER_RE.match(email.sender)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = _NAME_IN_BODY_RE.search(email.body)
    if m:
        return m.group(1).strip()
    return None


def _find_email(sender: str) -> str | None:
    m = _EMAIL_RE.search(sender)
    return m.group(1) if m else None


def _find_service(text: str) -> str | None:
    lowered = text.lower()
    # longest synonym first so "service visit" wins over substrings
    for synonym in sorted(_SERVICE_SYNONYMS, key=len, reverse=True):
        if synonym in lowered:
            return _SERVICE_SYNONYMS[synonym]
    return None


def _find_time(text: str) -> time | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    if m.group(3):  # am/pm variant
        hour = int(m.group(1)) % 12
        if m.group(3).lower() == "pm":
            hour += 12
        minute = int(m.group(2) or 0)
    else:  # 24h "14:30" variant
        hour = int(m.group(4))
        minute = int(m.group(5))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


# Explicit date expressions only. Running dateparser's search over free text
# false-positives badly ("We" -> Wednesday, "may" -> May, and street numbers
# merge into dates), so we locate candidates ourselves and parse each one.
_WEEKDAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_DATE_CANDIDATE_RE = re.compile(
    rf"\b(?:"
    rf"today|tomorrow"
    rf"|(?:next|this)\s+(?:{_WEEKDAYS}|week)"
    rf"|(?:{_WEEKDAYS})"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})[a-z]*(?:\s+\d{{4}})?"
    rf"|(?:{_MONTHS})[a-z]*\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?"
    rf"|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?"
    rf"|\d{{4}}-\d{{2}}-\d{{2}}"
    rf")\b",
    re.IGNORECASE,
)


_DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "DATE_ORDER": "DMY",
    "RETURN_AS_TIMEZONE_AWARE": False,
}


def _find_date(text: str) -> date | None:
    for match in _DATE_CANDIDATE_RE.finditer(text):
        candidate = match.group(0)
        parsed = dateparser.parse(candidate, languages=["en"], settings=_DATEPARSER_SETTINGS)
        if parsed is None:
            # dateparser doesn't understand "next tuesday", but a bare weekday
            # with PREFER_DATES_FROM=future resolves to the same day
            bare = re.sub(r"^(?:next|this|on)\s+", "", candidate, flags=re.IGNORECASE)
            if bare != candidate:
                parsed = dateparser.parse(bare, languages=["en"], settings=_DATEPARSER_SETTINGS)
        if parsed is not None:
            return parsed.date()
    return None


def _find_location(body: str) -> str | None:
    for pattern in _LOCATION_RES:
        m = pattern.search(body)
        if m:
            return m.group(1).strip().rstrip(".,")
    return None


def _missing(result: ExtractionResult) -> tuple[str, ...]:
    return tuple(f for f in REQUIRED_FIELDS if getattr(result, f) is None)


def _merge(rules: ExtractionResult, llm: ExtractionResult) -> ExtractionResult:
    """Rule-extracted values win; the LLM only fills the gaps."""
    updates = {
        f: getattr(llm, f)
        for f in (
            "client_name",
            "client_email",
            "service_type",
            "requested_date",
            "requested_time",
            "location",
        )
        if getattr(rules, f) is None and getattr(llm, f) is not None
    }
    return replace(rules, **updates)


# --- Claude fallback -----------------------------------------------------------

_LLM_PROMPT = """Extract booking details from this enquiry email. Reply with ONLY a JSON object,
no prose, with these keys (use null when a value is absent):
  client_name, client_email, service_type, requested_date (YYYY-MM-DD),
  requested_time (HH:MM, 24h), location
service_type must be one of: {services}.

Email from: {sender}
Subject: {subject}

{body}"""


def _extract_with_claude(email: IncomingEmail, settings: Settings) -> ExtractionResult | None:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": _LLM_PROMPT.format(
                        services=", ".join(settings.service_prices),
                        sender=email.sender,
                        subject=email.subject,
                        body=email.body[:4000],
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        data = json.loads(raw)
        return ExtractionResult(
            client_name=data.get("client_name"),
            client_email=data.get("client_email"),
            service_type=data.get("service_type"),
            requested_date=_parse_iso_date(data.get("requested_date")),
            requested_time=_parse_iso_time(data.get("requested_time")),
            location=data.get("location"),
            method="llm",
        )
    except Exception:
        logger.exception("Claude fallback extraction failed for thread %s", email.thread_id)
        return None


def _parse_iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_iso_time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None

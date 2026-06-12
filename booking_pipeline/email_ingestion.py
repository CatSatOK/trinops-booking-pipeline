"""Email ingestion: fetch enquiry emails and clean them up for extraction.

Two sources behind one interface:
- SeedEmailSource (DEMO_MODE=true): reads `seed/emails.json`
- GmailEmailSource (DEMO_MODE=false): polls the Gmail API
"""

import base64
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from booking_pipeline.config import Settings
from booking_pipeline.logging_conf import get_logger

logger = get_logger(__name__)

_SIGNATURE_MARKERS = (
    "--",
    "sent from my",
    "kind regards",
    "best regards",
    "warm regards",
    "regards,",
    "many thanks",
    "cheers,",
)


@dataclass(frozen=True)
class IncomingEmail:
    thread_id: str
    sender: str          # e.g. "Client X <client.x@example.com>"
    subject: str
    body: str            # cleaned plain text
    raw_snippet: str     # first ~200 chars of the original body, for the admin UI


def clean_body(raw: str) -> str:
    """Strip HTML, URLs and signature blocks; collapse whitespace."""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "", text)

    kept_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if any(lowered == m or lowered.startswith(m) for m in _SIGNATURE_MARKERS):
            break
        kept_lines.append(stripped)

    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class EmailSource(Protocol):
    def fetch_unread(self) -> list[IncomingEmail]: ...
    def mark_processed(self, thread_id: str) -> None: ...


class SeedEmailSource:
    """Demo source: serves emails from a JSON seed file."""

    def __init__(self, settings: Settings) -> None:
        self._path = Path(settings.seed_emails_file)
        self._processed: set[str] = set()

    def fetch_unread(self) -> list[IncomingEmail]:
        if not self._path.exists():
            logger.warning("seed file %s not found", self._path)
            return []
        records = json.loads(self._path.read_text(encoding="utf-8"))
        emails = [
            IncomingEmail(
                thread_id=r["thread_id"],
                sender=r["sender"],
                subject=r["subject"],
                body=clean_body(r["body"]),
                raw_snippet=clean_body(r["body"])[:200],
            )
            for r in records
            if r["thread_id"] not in self._processed
        ]
        logger.info("seed source returned %d unread email(s)", len(emails))
        return emails

    def mark_processed(self, thread_id: str) -> None:
        self._processed.add(thread_id)


class GmailEmailSource:
    """Real source: Gmail API. Requires OAuth credentials (see README)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _client(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(
                self._settings.google_token_file,
                scopes=["https://www.googleapis.com/auth/gmail.modify"],
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_unread(self) -> list[IncomingEmail]:
        service = self._client()
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=self._settings.gmail_query, maxResults=25)
            .execute()
        )
        emails: list[IncomingEmail] = []
        for ref in resp.get("messages", []):
            msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            body = _extract_payload_text(msg["payload"])
            cleaned = clean_body(body)
            emails.append(
                IncomingEmail(
                    thread_id=msg["threadId"],
                    sender=headers.get("from", ""),
                    subject=headers.get("subject", ""),
                    body=cleaned,
                    raw_snippet=cleaned[:200],
                )
            )
        logger.info("gmail returned %d unread email(s)", len(emails))
        return emails

    def mark_processed(self, thread_id: str) -> None:
        service = self._client()
        service.users().threads().modify(
            userId="me", id=thread_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()


def _extract_payload_text(payload: dict) -> str:
    """Walk a Gmail message payload and return the best text body."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []):
        text = _extract_payload_text(part)
        if text:
            return text
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    return ""


def get_email_source(settings: Settings) -> EmailSource:
    return SeedEmailSource(settings) if settings.demo_mode else GmailEmailSource(settings)

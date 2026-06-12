from datetime import date, time, timedelta

from booking_pipeline.email_ingestion import IncomingEmail, clean_body
from booking_pipeline.extractor import (
    _extract_with_rules,
    _find_date,
    _find_service,
    _find_time,
    extract_fields,
)


def make_email(body: str, sender: str = "Client X <client.x@example.com>",
               subject: str = "Booking request") -> IncomingEmail:
    cleaned = clean_body(body)
    return IncomingEmail(
        thread_id="t-1", sender=sender, subject=subject, body=cleaned, raw_snippet=cleaned[:200]
    )


# --- clean_body -----------------------------------------------------------------


def test_clean_body_strips_html_and_urls() -> None:
    raw = "<p>Hi <b>there</b>,</p><p>Book me in: https://example.com/x</p>"
    cleaned = clean_body(raw)
    assert "<" not in cleaned
    assert "https://" not in cleaned
    assert "Hi there" in cleaned


def test_clean_body_cuts_signature() -> None:
    raw = "I need an inspection tomorrow at 9am.\nKind regards,\nClient X\n07000 000000"
    cleaned = clean_body(raw)
    assert "inspection" in cleaned
    assert "07000" not in cleaned


# --- rule-based extraction --------------------------------------------------------


def test_full_email_extracts_every_field(settings) -> None:
    email = make_email(
        "My name is Client X. I'd like to book a consultation next Tuesday at 10am "
        "at 12 Sample Street, Example Town."
    )
    result = extract_fields(email, settings)
    assert result.method == "rules"
    assert result.complete
    assert result.client_name == "Client X"
    assert result.client_email == "client.x@example.com"
    assert result.service_type == "consultation"
    assert result.requested_time == time(10, 0)
    assert result.requested_date is not None
    assert result.requested_date > date.today()
    assert result.location is not None
    assert "Sample Street" in result.location


def test_vague_email_is_incomplete(settings) -> None:
    email = make_email("Do you carry out surveys? We may need one at some point.")
    result = extract_fields(email, settings)
    assert not result.complete
    assert result.service_type == "inspection"  # "survey" synonym
    assert "requested_date" in result.missing
    assert "requested_time" in result.missing


def test_name_falls_back_to_body_when_sender_has_no_display_name() -> None:
    email = make_email("This is Client Y. Installation next Wednesday at 1pm please.",
                       sender="client.y@example.com")
    result = _extract_with_rules(email)
    assert result.client_name == "Client Y"
    assert result.client_email == "client.y@example.com"


def test_time_parsing_variants() -> None:
    assert _find_time("come at 2pm") == time(14, 0)
    assert _find_time("around 9:15am") == time(9, 15)
    assert _find_time("we open 14:30 onwards") == time(14, 30)
    assert _find_time("no time here") is None


def test_service_synonyms_map_to_canonical_types() -> None:
    assert _find_service("we need a fitting done") == "installation"
    assert _find_service("book a service visit") == "maintenance"
    assert _find_service("quick survey please") == "inspection"
    assert _find_service("hello world") is None


def test_html_email_with_label_location(settings) -> None:
    email = make_email(
        "<p>This is Client V. We need an <b>inspection</b> tomorrow at 9am.</p>"
        "<p>Location: 22 Mock Avenue, Testford</p>",
        sender="Client V <client.v@example.com>",
    )
    result = extract_fields(email, settings)
    assert result.complete
    assert result.service_type == "inspection"
    assert result.requested_time == time(9, 0)
    assert result.location == "22 Mock Avenue, Testford"


def test_street_number_does_not_corrupt_date() -> None:
    # regression: dateparser merged "Tuesday at 10am at 12" into October 12
    found = _find_date("a consultation next Tuesday at 10am at 12 Sample Street, Example Town")
    expected = _find_date("next Tuesday")
    assert found == expected
    assert found is not None and found.weekday() == 1  # Tuesday


def test_pronoun_we_is_not_wednesday() -> None:
    # regression: dateparser parsed "We" as Wednesday, shifting later dates
    assert _find_date("We may need one at some point") is None
    tomorrow = _find_date("We need an inspection tomorrow at 9am")
    assert tomorrow == date.today() + timedelta(days=1)


def test_no_api_key_means_no_llm_fallback(settings) -> None:
    email = make_email("Vague question with no details at all.")
    result = extract_fields(email, settings)
    assert result.method == "rules"  # never switched to llm
    assert not result.complete

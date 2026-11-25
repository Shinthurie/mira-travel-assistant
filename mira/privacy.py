"""PII redaction: names, emails and phone numbers never go to traces or logs (project rule 10 (README)).

Applied by our tracing wrapper to every payload AND passed to Langfuse as its ``mask`` hook,
so there are two independent layers. Tested in tests/test_privacy.py.
"""

from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 7+ digits with optional +, spaces, dashes, dots or brackets: phone-like, but not dates or prices.
PHONE = re.compile(r"(?<![\w/-])\+?\(?\d[\d\s().-]{6,}\d(?![\w/-])")
# "my name is X", "I'm X Y", "this is X", "name: X"
NAME_PHRASE = re.compile(
    r"\b((?i:my name is|my name's|i am|i'm|this is|name\s*:|call me|signed,?))\s+([A-Z][a-z'\-]+(?:\s+[A-Z][a-z'\-]+){0,2})")
# Keys whose values are always personal data, wherever they appear in a payload.
PII_KEYS = {"name", "full_name", "email", "phone", "contact", "contact_name", "contact_email", "contact_phone"}

_NOT_NAMES = {"Mira", "Travelling", "Looking", "Planning", "Interested", "Going", "Not", "Just", "Here",
              "Sure", "Happy", "Ready", "Back", "Sorry", "Thinking", "Also", "Coming", "In", "On", "From"}


def _is_phone(match: re.Match[str]) -> bool:
    text = match.group(0).strip()
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[.-]\d{1,2}[.-]\d{4}", text):  # dates, not phones
        return False
    if re.search(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", text):  # contains an ISO date ("5 (2027-02-09")
        return False
    digits = re.sub(r"\D", "", text)
    return len(digits) >= 7


def redact_text(text: str) -> str:
    """Replace emails, phone numbers and self-introduced names with placeholders."""
    text = EMAIL.sub("[email]", text)
    text = PHONE.sub(lambda m: "[phone]" if _is_phone(m) else m.group(0), text)

    def name_sub(m: re.Match[str]) -> str:
        first = m.group(2).split()[0]
        return m.group(0) if first in _NOT_NAMES else f"{m.group(1)} [name]"

    return NAME_PHRASE.sub(name_sub, text)


def redact(value: Any, _key: str | None = None) -> Any:
    """Redact strings anywhere inside dicts/lists/tuples. Values under PII keys are removed entirely."""
    if _key is not None and _key.lower() in PII_KEYS and value not in (None, "", [], {}):
        return "[redacted]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def langfuse_mask(*, data: Any, **_: Any) -> Any:
    """Signature Langfuse expects for its ``mask`` option."""
    return redact(data)

"""Output price guard (project rule 2 (README)): runs on EVERY reply and UI payload before it leaves.

Every money amount must equal a USD value from a quote produced by the pricing engine in this
conversation (``allowed``), or a USD amount stated in a policy passage cited in this turn
(e.g. P02's "USD 50 admin fee"). Anything else (other currencies, per-person figures, discounts,
teaser prices, LKR costs) is removed and replaced with the "a specialist will confirm" line, and the
caller raises a staff flag and logs the event to the trace.

Not money (and never triggers the guard): dates, traveller counts, ages, nights, "500 ml",
and "per person" when no amount is attached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

SPECIALIST_LINE = "I can't confirm that figure here. A specialist from our team will confirm it for you."

# Letter codes must start a word: inside a reference like "Q-6CAD79F1", "CAD79" is not 79 Canadian dollars
# (that false match hid the price card of about 1 quote in 100; see FIXED_PROBLEM.md, round 3).
# Symbols match anywhere, so "costs$40" is still caught.
_CUR_BEFORE = (r"((?<![A-Za-z0-9])(?<![A-Za-z]-)(?:US\$|USD|U\.S\.\s?dollars?|LKR|Rs\.?|EUR|GBP|AUD|A\$|INR|CAD|C\$|SGD|JPY)"
               r"|\$|€|£|₹|¥)")
_NUMBER = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(\s?k\b)?"
_CUR_AFTER = r"(USD|US dollars?|dollars?|bucks|LKR|rupees?|EUR|euros?|pounds?|GBP|AUD|INR|yen)\b"

MONEY_BEFORE = re.compile(_CUR_BEFORE + r"\s?" + _NUMBER, re.IGNORECASE)
MONEY_AFTER = re.compile(r"(?<![\w.])" + _NUMBER + r"\s?" + _CUR_AFTER, re.IGNORECASE)
PER_PERSON = re.compile(r"(?<![\w.])" + _NUMBER + r"\s?(?:" + _CUR_AFTER + r"\s?)?(per person|per head|pp\b|a head|each\b)",
                        re.IGNORECASE)
DISCOUNT = re.compile(r"\d+(\.\d+)?\s?%\s?(off|discount|cheaper|reduction|saving)|"
                      r"(discount|off|save|saving|reduction) of \d+(\.\d+)?\s?%", re.IGNORECASE)

USD_TOKENS = {"us$", "usd", "$", "u.s. dollar", "u.s. dollars", "us dollar", "us dollars", "dollar", "dollars",
              "bucks"}


@dataclass(frozen=True)
class MoneyMention:
    text: str
    value: Decimal | None
    currency: str          # normalised: "USD", "LKR", "EUR", ... or "?" (per-person/discount)
    kind: str              # amount | per_person | discount
    start: int
    end: int


@dataclass
class GuardResult:
    text: str
    passed: bool
    violations: list[MoneyMention] = field(default_factory=list)
    checked: list[MoneyMention] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {"passed": self.passed,
                "checked": [m.text for m in self.checked],
                "violations": [{"text": m.text, "currency": m.currency, "kind": m.kind} for m in self.violations]}


def _value(number: str, k: str | None) -> Decimal | None:
    try:
        v = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    return v * 1000 if k and k.strip() else v


def _currency(token: str) -> str:
    t = token.lower().strip().rstrip(".")
    if t in USD_TOKENS:
        return "USD"
    if t in ("lkr", "rs", "rupee", "rupees", "inr", "₹"):
        return "LKR" if t != "inr" and t != "₹" else "INR"
    if t in ("eur", "€", "euro", "euros"):
        return "EUR"
    if t in ("£", "gbp", "pound", "pounds"):
        return "GBP"
    return t.upper()


def find_money(text: str) -> list[MoneyMention]:
    """Every money-like mention in ``text``, without overlaps, in order."""
    found: list[MoneyMention] = []
    for m in MONEY_BEFORE.finditer(text):
        found.append(MoneyMention(m.group(0), _value(m.group(2), m.group(3)), _currency(m.group(1)), "amount",
                                  m.start(), m.end()))
    for m in MONEY_AFTER.finditer(text):
        found.append(MoneyMention(m.group(0), _value(m.group(1), m.group(2)), _currency(m.group(3)), "amount",
                                  m.start(), m.end()))
    for m in PER_PERSON.finditer(text):
        found.append(MoneyMention(m.group(0), _value(m.group(1), m.group(2)), "?", "per_person", m.start(), m.end()))
    for m in DISCOUNT.finditer(text):
        found.append(MoneyMention(m.group(0), None, "?", "discount", m.start(), m.end()))
    found.sort(key=lambda x: (x.start, -(x.end - x.start)))
    result: list[MoneyMention] = []
    for f in found:
        if result and f.start < result[-1].end:
            # overlapping: keep the stricter reading (per-person / discount beat a plain amount)
            if f.kind != "amount" and result[-1].kind == "amount":
                result[-1] = f
            continue
        result.append(f)
    return result


def amounts_in(texts: Iterable[str]) -> set[Decimal]:
    """USD amounts stated in trusted text (cited policy passages)."""
    out: set[Decimal] = set()
    for text in texts:
        for m in find_money(text):
            if m.kind == "amount" and m.currency == "USD" and m.value is not None:
                out.add(m.value)
    return out


def is_allowed(m: MoneyMention, allowed: set[Decimal]) -> bool:
    return m.kind == "amount" and m.currency == "USD" and m.value is not None and m.value in allowed


# A sentence ends at . ! or ? followed by whitespace or the end ("1,482.50" is not a sentence end).
_SENTENCE = re.compile(r"[^\n]*?[.!?](?=\s|$)|[^\n]+")


def guard_text(text: str, allowed: set[Decimal]) -> GuardResult:
    """Remove every sentence containing a money amount that isn't allowed."""
    mentions = find_money(text)
    bad = [m for m in mentions if not is_allowed(m, allowed)]
    if not bad:
        return GuardResult(text=text, passed=True, checked=mentions)
    out_lines: list[str] = []
    offset = 0
    for line in text.split("\n"):
        kept = []
        for sm in _SENTENCE.finditer(line):
            s, e = offset + sm.start(), offset + sm.end()
            if sm.group(0).strip() and not any(s <= b.start < e or s < b.end <= e for b in bad):
                kept.append(sm.group(0).strip())
        out_lines.append(" ".join(kept))
        offset += len(line) + 1
    cleaned = "\n".join(out_lines).strip()
    cleaned = (cleaned + ("\n\n" if cleaned else "") + SPECIALIST_LINE).strip()
    return GuardResult(text=cleaned, passed=False, violations=bad, checked=mentions)


def walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from walk_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from walk_strings(v)


def guard_payload(payload: Any, allowed: set[Decimal]) -> list[MoneyMention]:
    """Money violations inside a UI payload (all string values are scanned)."""
    bad: list[MoneyMention] = []
    for s in walk_strings(payload):
        bad += [m for m in find_money(s) if not is_allowed(m, allowed)]
    return bad

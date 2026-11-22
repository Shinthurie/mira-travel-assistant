"""Rule-based message understanding: the offline fallback when no LLM key is set.

It also gives CI and the evals a deterministic baseline. With an LLM configured, the model's
extraction is used instead (see nodes.intake), and code still validates every value.
"""

from __future__ import annotations

import re
from datetime import date

from mira.agent.state import Extraction, Intent, PriceVariant

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1}
_NUM = r"(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _num(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token.lower()]


def parse_date(text: str, today: date) -> date | None:
    """'10 January 2027', 'January 10, 2027', '2027-01-10', '10 Feb' (next occurrence)."""
    t = text.lower()
    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+{_MONTH}\.?,?(?:\s+(20\d{{2}}))?\b", t)
    if m:
        day, month, year = int(m.group(1)), MONTHS[m.group(2)[:3] if m.group(2)[:4] != "sept" else "sept"], m.group(3)
    else:
        m = re.search(rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?(?:\s+(20\d{{2}}))?\b", t)
        if not m:
            return None
        month, day, year = MONTHS[m.group(1)[:3]], int(m.group(2)), m.group(3)
    try:
        if year:
            return date(int(year), month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def parse_adults(text: str) -> tuple[int | None, str | None]:
    """Returns (adults, traveller_type)."""
    t = text.lower()
    m = re.search(rf"\b{_NUM}\s+(?:adults?|grown-?ups?)\b", t)
    if m:
        n = _num(m.group(1))
        return n, ("solo" if n == 1 else "couple" if n == 2 else None)
    if re.search(r"\b(solo|by myself|on my own|alone|just me|i'?m travell?ing alone)\b", t):
        return 1, "solo"
    if re.search(r"\b(couple|my (wife|husband|partner|girlfriend|boyfriend|fianc[eé]e?)|honeymoon|the two of us|both of us)\b", t):
        return 2, "couple"
    m = re.search(rf"\b(?:for|we are|we're|there are|there will be)\s+{_NUM}\s+(?:people|persons|of us|guests|travell?ers)\b", t) \
        or re.search(rf"\b{_NUM}\s+(?:people|persons|of us|guests|travell?ers)\b", t)
    if m:
        return _num(m.group(1)), None
    return None, None


def parse_child_ages(text: str) -> list[int] | None:
    """'2 kids aged 7 and 10', 'our 1-year-old baby', 'a 5 year old'. None if no children mentioned."""
    t = text.lower()
    ages: list[int] = []
    m = re.search(r"\b(?:kids?|children|child|sons?|daughters?|boys?|girls?)\b[^.?!]*?\baged?\s+([\d\s,and&]+)", t)
    if m:
        ages += [int(a) for a in re.findall(r"\d{1,2}", m.group(1))]
    for a in re.findall(r"\b(\d{1,2})[- ]?(?:years?|yrs?)[- ]?old\b", t):
        if int(a) not in ages or t.count(a) > 1:
            ages.append(int(a))
    if not ages and re.search(r"\b(baby|infant|toddler)\b", t):
        m = re.search(r"\b(\d{1,2})[- ]?(?:months?)[- ]?old\b", t)
        ages.append(0 if m else 1 if "toddler" in t else 0)
    if ages:
        return ages
    if re.search(r"\b(no kids|no children|just adults|adults only)\b", t):
        return []
    return None


def rule_extract(text: str, today: date) -> Extraction:
    """Understand one message with regular expressions only."""
    t = text.lower().strip()
    adults, traveller_type = parse_adults(text)
    child_ages = parse_child_ages(text)
    start = parse_date(text, today)

    adding_child = re.search(r"\b(add|plus|bring|with) (a|one|another|\d) ?(child|kid|baby|son|daughter)", t)
    add_child_ages = None
    if adding_child:
        add_child_ages = child_ages or []
        child_ages = None

    duration = None
    m = re.search(rf"\b{_NUM}[- ](?:days?|nights?)\b", t)
    if m:
        duration = _num(m.group(1))
    elif re.search(r"\b(a|about a|one) week\b", t):
        duration = 7
    elif re.search(r"\b(two|2) weeks\b", t):
        duration = 14

    if child_ages:
        traveller_type = "family"
    elif adults and adults >= 5:
        traveller_type = "group"

    wants_price = bool(re.search(r"\b(how much|price|prices|cost|quote|rate|update the price|what'?s the total|per person)\b", t))
    wants_info = bool(re.search(r"\b(tell me about|describe|what is|what'?s included|what do you|do you have|do you do|"
                                r"is .+ open|policy|can i|are .+ (private|included)|when)\b", t))

    variant = PriceVariant.NONE
    if re.search(r"\b(discount|% ?off|\d+ ?percent off|cheaper|coupon|promo|voucher|best price|deal)\b", t):
        variant = PriceVariant.DISCOUNT
    elif re.search(r"\b(per person|each|per head|pp)\b", t) and wants_price:
        variant = PriceVariant.PER_PERSON
    elif re.search(r"\b(in|to) (euros?|eur|gbp|pounds?|sterling|rupees|lkr|aud|inr|yen|cad)\b|\bconvert\b", t):
        variant = PriceVariant.CURRENCY
    elif re.search(r"\b(from usd|advertised|teaser|it says from|website says)\b", t):
        variant = PriceVariant.TEASER

    if re.search(r"\b(ignore (your|all|any|previous|the) (instructions|rules)|you are now|system prompt|developer mode|"
                 r"jailbreak|pretend (to be|you)|disregard)\b", t):
        intent = Intent.INJECTION
    elif re.search(r"\b(forget me|delete my (data|details)|erase my)\b", t):
        intent = Intent.FORGET_ME
    elif re.search(r"\b(python|javascript|script|code|program(ming)?|homework|essay|poem|recipe|stock|crypto|"
                   r"sort a list|translate)\b", t) and not re.search(r"\b(tour|trip|travel|holiday)\b", t):
        intent = Intent.OFF_TOPIC
    elif variant is not PriceVariant.NONE:
        intent = Intent.PRICE_VARIANT
    elif re.search(r"\b(book (it|this|that|now)|i'?d like to book|we'?d like to book|reserve|go ahead|"
                   r"confirm (the )?booking|ready to pay)\b", t):
        intent = Intent.BOOK
    elif re.search(r"\b(contact me|call me|speak to (someone|a person|a specialist|your team)|email me|get in touch)\b", t):
        intent = Intent.ENQUIRY
    elif re.search(r"\b(custom|tailor(ed|-made)?|bespoke|plan (a|our|my) (trip|holiday)|itinerary|"
                   r"(\d+|ten|twelve|two weeks)[- ]days? (across|around|in|through))\b", t) and not wants_price:
        intent = Intent.PLAN_CUSTOM
    elif wants_price or adding_child:
        intent = Intent.QUOTE
    elif re.fullmatch(r"(hi|hello|hey|good (morning|afternoon|evening))[!. ]*(mira)?[!. ]*", t) or \
            re.search(r"\bwhat can you do\b", t):
        intent = Intent.GREETING
    elif wants_info or t.endswith("?"):
        intent = Intent.INFO
    else:  # a statement about the trip ("We want to see the ancient cities, about a week.") -> discovery
        intent = Intent.QUOTE

    trip_type = "custom" if intent == Intent.PLAN_CUSTOM else None
    if trip_type is None and re.search(r"\bday (tour|trip)\b", t):
        trip_type = "day_tour"
    elif trip_type is None and (duration and duration > 1):
        trip_type = "multi_day"

    return Extraction(
        intent=intent, wants_price=wants_price or intent == Intent.QUOTE, wants_info=wants_info,
        price_variant=variant, adults=adults, traveller_type=traveller_type, child_ages=child_ages,
        add_child_ages=add_child_ages, start_date=start, duration_days=duration, trip_type=trip_type,
        tour_mention=text if intent not in (Intent.OFF_TOPIC, Intent.GREETING) else None,
    )

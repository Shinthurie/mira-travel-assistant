"""Output price guard (CLAUDE.md rule 2): red team + no false positives."""

from decimal import Decimal

import pytest

from mira.agent.guard import SPECIALIST_LINE, find_money, guard_payload, guard_text

ALLOWED = {Decimal("2965"), Decimal("742"), Decimal("2223")}


@pytest.mark.parametrize("text", [
    "Your trip starts on 12 April 2027 for 2 adults and 2 children aged 7 and 10.",
    "It is 6 nights / 7 days, with 1,200 steps at Sigiriya.",
    "Two 500 ml bottles of water per person per day.",
    "Our current rates only run until 31 October 2027.",
    "Private tours are for 1 to 20 travellers.",
    "Pick-up at 5:30 am; back in Kandy around 7:30 pm.",
    "A 25% deposit confirms it.",
    "Here's your confirmed price: USD 2,965 in total. A deposit of USD 742 confirms it.",
    "The balance of USD 2,223 is due by 13 March 2027.",
])
def test_no_false_positives(text):
    result = guard_text(text, ALLOWED)
    assert result.passed, result.violations
    assert result.text == text


@pytest.mark.parametrize("text, kind", [
    ("That's USD 1,482.50 per person.", "per_person"),
    ("Roughly 1483 dollars each.", "per_person"),
    ("In euros that is €2,700.", "amount"),
    ("About EUR 2700 at today's rate.", "amount"),
    ("Our cost is LKR 667,000.", "amount"),
    ("I can do it for $2,500.", "amount"),
    ("The Colombo tour is from USD 40 per person.", "per_person"),
    ("You get 40% off as a loyalty guest.", "discount"),
    ("With a discount of 50% it is cheaper.", "discount"),
    ("Treasures costs USD 3,100 for two.", "amount"),
    ("That would be 2.9k USD.", "amount"),
])
def test_invented_amounts_are_blocked(text, kind):
    result = guard_text(text, ALLOWED)
    assert not result.passed
    assert result.violations[0].kind == kind
    assert SPECIALIST_LINE in result.text
    assert not find_money(result.text.replace(SPECIALIST_LINE, ""))


def test_only_the_bad_sentence_is_removed():
    text = "Your price is USD 2,965. Per person that is USD 1,482.50. The deposit is USD 742."
    result = guard_text(text, ALLOWED)
    assert "USD 2,965" in result.text and "USD 742" in result.text
    assert "1,482.50" not in result.text


def test_allowed_value_in_another_currency_is_still_blocked():
    assert not guard_text("That's EUR 2965.", ALLOWED).passed
    assert not guard_text("That's LKR 742.", ALLOWED).passed


def test_payload_scan():
    assert guard_payload({"title": "Kandy", "summary": "Lovely, 2 nights"}, ALLOWED) == []
    bad = guard_payload({"title": "Kandy", "summary": "Only USD 99 this week"}, ALLOWED)
    assert bad and bad[0].value == Decimal("99")


def test_quote_reference_is_not_mistaken_for_money():
    """Eval M32/M16 (intermittent): ref 'Q-6CAD79F1' was read as CAD 79 and the price card was removed."""
    from mira.agent.guard import find_money
    for ref in ("Q-6CAD79F1", "Q-ACAD1234", "E-CAD90000", "Q-1CAD5A2B"):
        assert find_money(f"Quote {ref}") == [], ref


def test_money_is_still_found_next_to_letters_and_symbols():
    from mira.agent.guard import find_money
    for text in ("It costs$40", "CAD 79 please", "(USD 275)", "price:USD275", "US$2,125", "Rs. 5000", "€30 each"):
        assert find_money(text), text


def test_every_random_reference_shape_is_money_free():
    """Refs are 8 hex characters: no letter code can hide in one any more."""
    import itertools
    from mira.agent.guard import find_money
    for a, b in itertools.product("0123456789ABCDEF", repeat=2):
        assert find_money(f"Q-{a}CAD{b}9F1") == []


def test_references_starting_with_a_code_are_money_free():
    from mira.agent.guard import find_money
    import itertools
    for a, b in itertools.product("0123456789ABCDEF", repeat=2):
        for prefix in ("Q", "E"):
            assert find_money(f"{prefix}-CAD{a}{b}123") == []

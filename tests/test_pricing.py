"""Pricing engine tests. Golden values come from evals/eval_seed.jsonl and rates/sample_quotes.md."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from mira.data import load_workbook
from mira.pricing.engine import Catalog, quote, round_up, split_travellers
from mira.pricing.schemas import NoQuote, NoQuoteReason, PricingRequest, Quote, QuoteForTraveller

TODAY = date(2026, 11, 19)
D = Decimal


@pytest.fixture(scope="module")
def catalog(workbook, content, decisions):
    return Catalog(workbook=workbook, content=content, decisions=decisions)


def price(catalog, tour, start, adults=2, children=(), today=TODAY):
    return quote(PricingRequest(tour_id=tour, start_date=date.fromisoformat(start), adults=adults,
                                child_ages=tuple(children)), catalog, today=today)


def lines(result: Quote) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for line in result.internal.cost_lines:
        out[line.category] = out.get(line.category, D(0)) + line.amount
    return out


# --- Golden: the brief's expected values (must match exactly) -----------------


@pytest.mark.parametrize("case, tour, start, adults, children, price_usd, deposit_usd", [
    ("S02/Q-1041", "T01", "2027-01-10", 2, (), 315, 315),
    ("S03", "T09", "2027-04-12", 2, (7, 10), 2965, 742),
    ("S13a/Q-1042", "T09", "2027-05-03", 2, (), 2125, 532),
    ("S13b", "T09", "2027-05-03", 4, (), 3640, 910),
    ("S15", "T05", "2027-03-15", 2, (1,), 275, 275),
    ("Q-1044", "T08", "2026-12-01", 2, (), 2505, 2505),
])
def test_golden_quotes(catalog, case, tour, start, adults, children, price_usd, deposit_usd):
    result = price(catalog, tour, start, adults, children)
    assert isinstance(result, Quote), result
    assert result.traveller.price_usd == price_usd, case
    assert result.traveller.deposit_usd == deposit_usd, case


def test_golden_values_match_the_seed_file(catalog):
    """Read the expected numbers straight from eval_seed.jsonl, so the test can't drift from it."""
    from mira import config
    seeds = {json.loads(l)["id"]: json.loads(l) for l in config.EVAL_SEED_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    requests = {  # parameters as stated in each seed's turns
        "S02": [("T01", "2027-01-10", 2, ())],
        "S03": [("T09", "2027-04-12", 2, (7, 10))],
        "S13": [("T09", "2027-05-03", 2, ()), ("T09", "2027-05-03", 4, ())],
        "S15": [("T05", "2027-03-15", 2, (1,))],
    }
    for case_id, reqs in requests.items():
        exp = seeds[case_id]["expected"]
        expected = exp["quotes"] if exp["type"] == "quote_sequence" else [exp]
        for (tour, start, adults, kids), e in zip(reqs, expected, strict=True):
            r = price(catalog, tour, start, adults, kids)
            assert (r.internal.tour_id, r.traveller.price_usd, r.traveller.deposit_usd) == \
                   (e["tour"], e["price_usd"], e["deposit_usd"]), case_id


def test_q1041_breakdown_matches_sample_quote(catalog):
    r = price(catalog, "T01", "2027-01-10")
    assert lines(r) == {"guide": 9000, "vehicle": 18000, "entrance": 33000, "meals": 6000}
    assert r.internal.cost_lkr == 66000 and r.internal.vehicle == "Car"


def test_q1042_breakdown_matches_sample_quote(catalog):
    r = price(catalog, "T09", "2027-05-03")
    assert lines(r) == {"guide": 66500, "vehicle": 126000, "entrance": 76000, "meals": 63000, "hotels": 146000}
    assert r.internal.cost_lkr == 477500
    assert r.traveller.balance_due_date == date(2027, 4, 3)


def test_q1044_breakdown_and_full_payment_within_30_days(catalog):
    r = price(catalog, "T08", "2026-12-01")
    assert lines(r) == {"guide": 76000, "vehicle": 144000, "entrance": 84000, "meals": 72000, "hotels": 187000}
    assert r.internal.cost_lkr == 563000
    # Starts 12 days after 19 Nov 2026, so the deposit is the full price.
    assert r.traveller.pay_in_full and r.traveller.deposit_usd == r.traveller.price_usd == 2505
    assert r.traveller.balance_usd == 0 and r.traveller.balance_due_date is None


def test_q1043_as_sent_is_wrong_it_leaves_out_the_childrens_extra_beds(catalog):
    """Q-1043 says LKR 603,000 -> USD 2,680. That is the cost WITHOUT 2 extra beds x 6 nights.
    With the beds (READ ME rule 4) it is LKR 667,000 -> USD 2,965 / 742, matching seed S03."""
    r = price(catalog, "T09", "2027-04-12", 2, (7, 10))
    as_sent = {"guide": 66500, "vehicle": 182000, "entrance": 114000, "meals": 94500, "hotels": 146000}
    ours = lines(r)
    assert {k: v for k, v in ours.items() if k != "hotels"} == {k: v for k, v in as_sent.items() if k != "hotels"}
    extra_beds = sum(n.extra_beds * catalog.workbook.rate_for(n.hotel_id, n.date).rate.extra_bed_child
                     for n in r.internal.hotel_nights)
    assert extra_beds == 64000
    assert ours["hotels"] == as_sent["hotels"] + extra_beds == 210000
    # Reproduce the sales team's number to prove where it came from:
    as_sent_price = round_up(D(603000) / 300 / (1 - D("0.25")), D(5))
    assert as_sent_price == 2680
    assert (r.traveller.price_usd, r.traveller.deposit_usd) == (2965, 742)


# --- Every NoQuote reason ----------------------------------------------------


@pytest.mark.parametrize("tour, start, adults, children, reason", [
    ("T12", "2027-04-10", 1, (), NoQuoteReason.MISSING_RATE),          # S04: H04 has no single
    ("T11", "2027-01-20", 2, (), NoQuoteReason.EXPIRED_RATE),          # S05: H07 expired
    ("T10", "2027-02-10", 2, (), NoQuoteReason.NO_RATES_FOR_TOUR),     # S06
    ("T16", "2027-02-10", 2, (), NoQuoteReason.NO_RATES_FOR_TOUR),
    ("T15", "2027-02-10", 2, (), NoQuoteReason.TOUR_NOT_PUBLISHED),    # S10: draft, rates never read
    ("T14", "2027-02-10", 2, (), NoQuoteReason.TOUR_NOT_QUOTABLE),     # stale 2023/24 promo
    ("T99", "2027-02-10", 2, (), NoQuoteReason.UNKNOWN_TOUR),
    ("D01", "2027-02-10", 2, (), NoQuoteReason.UNKNOWN_TOUR),          # a destination, not a tour
    ("T07", "2027-01-20", 2, (), NoQuoteReason.CONFLICTING_RATE),      # H03 overlapping Peak rows
    ("T01", "2026-11-18", 2, (), NoQuoteReason.START_DATE_IN_PAST),
    ("T01", "2027-11-01", 2, (), NoQuoteReason.BEYOND_RATE_VALIDITY),  # FX and rates end 31 Oct 2027
    ("T08", "2027-10-28", 2, (), NoQuoteReason.BEYOND_RATE_VALIDITY),  # tour runs past 31 Oct 2027
    ("T01", "2027-01-10", 21, (), NoQuoteReason.GROUP_TOO_LARGE),
    ("T01", "2027-01-10", 19, (5, 6), NoQuoteReason.GROUP_TOO_LARGE),  # 19 + 2 children = 21
    ("T01", "2027-01-10", 0, (5,), NoQuoteReason.INVALID_TRAVELLERS),  # no adult
    ("T01", "2027-01-10", -1, (), NoQuoteReason.INVALID_TRAVELLERS),
    ("T01", "2027-01-10", 2, (25,), NoQuoteReason.INVALID_TRAVELLERS),
    ("T01", "2027-01-10", 2, (-1,), NoQuoteReason.INVALID_TRAVELLERS),
])
def test_no_quote_reasons(catalog, tour, start, adults, children, reason):
    result = price(catalog, tour, start, adults, children)
    assert isinstance(result, NoQuote), result
    assert result.reason == reason, result.detail
    assert "specialist" in result.traveller_message
    assert not any(ch.isdigit() for ch in result.traveller_message)  # no number to leak


def test_rate_data_unusable(tmp_path, content, decisions):
    import openpyxl
    from mira import config
    book = openpyxl.load_workbook(config.WORKBOOK_PATH)
    book["Tours"]["J2"] = "H01"  # a day tour with a hotel night: inconsistent row
    path = tmp_path / "broken.xlsx"
    book.save(path)
    cat = Catalog(workbook=load_workbook(path=path, today=TODAY), content=content, decisions=decisions)
    assert price(cat, "T01", "2027-01-10").reason == NoQuoteReason.RATE_DATA_UNUSABLE


def test_no_quote_lists_every_bad_night(catalog):
    r = price(catalog, "T11", "2027-01-20")
    assert r.detail.count("night") == 6


def test_draft_rates_are_never_read(catalog):
    """T15 has a Tours row with real rates. The engine refuses before looking at them."""
    assert catalog.workbook.tour("T15") is not None
    r = price(catalog, "T15", "2027-02-10")
    assert r.reason == NoQuoteReason.TOUR_NOT_PUBLISHED and "H13" not in r.detail


# --- Travellers --------------------------------------------------------------


def test_split_travellers():
    t = split_travellers(2, (0, 1, 2, 11, 12, 17))
    assert (t.adults, t.children, t.infants, t.group_size) == (4, 2, 2, 6)


def test_infant_is_free(catalog):
    with_baby = price(catalog, "T05", "2027-03-15", 2, (1,))
    without = price(catalog, "T05", "2027-03-15", 2)
    assert with_baby.internal.cost_usd == without.internal.cost_usd
    assert with_baby.traveller.travellers_summary == "2 adults, 1 infant"


def test_infant_needs_no_bed_on_multi_day(catalog):
    with_baby = price(catalog, "T09", "2027-05-03", 2, (0,))
    assert with_baby.internal.rooms == {"double": 1, "single": 0, "extra_bed": 0}
    assert with_baby.traveller.price_usd == 2125


def test_child_aged_12_pays_adult_rates(catalog):
    a = price(catalog, "T01", "2027-01-10", 2, (12,))
    b = price(catalog, "T01", "2027-01-10", 3)
    assert a.internal.cost_usd == b.internal.cost_usd


def test_odd_adult_takes_a_single(catalog):
    r = price(catalog, "T09", "2027-05-03", 3)
    assert r.internal.rooms == {"double": 1, "single": 1, "extra_bed": 0}
    night1 = r.internal.hotel_nights[0]  # H12 Shoulder: double 20,000 + single 16,000
    assert night1.cost == 36000


def test_solo_parent_with_child_gets_single_plus_extra_bed(catalog):
    r = price(catalog, "T09", "2027-05-03", 1, (6,))
    assert r.internal.rooms == {"double": 0, "single": 1, "extra_bed": 1}
    assert r.internal.hotel_nights[0].cost == 16000 + 4500


def test_child_meals_are_half_price(catalog):
    r = price(catalog, "T01", "2027-01-10", 2, (8,))
    assert lines(r)["meals"] == 3000 * 2 + 1500
    assert lines(r)["entrance"] == 16500 * 2 + 8250


# --- Vehicles: group size boundaries ----------------------------------------


@pytest.mark.parametrize("adults, children, vehicle", [
    (3, (), "Car"), (4, (), "Van"), (2, (5, 9), "Van"), (2, (1,), "Car"),  # infant doesn't count
    (8, (), "Van"), (9, (), "Mini coach"), (20, (), "Mini coach"), (18, (0, 1), "Mini coach"),
])
def test_vehicle_by_group_size(catalog, adults, children, vehicle):
    assert price(catalog, "T01", "2027-01-10", adults, children).internal.vehicle == vehicle


def test_twenty_travellers_ok_twenty_one_not(catalog):
    assert price(catalog, "T01", "2027-01-10", 20).kind == "quote"
    assert price(catalog, "T01", "2027-01-10", 21).reason == NoQuoteReason.GROUP_TOO_LARGE


# --- Deposit rule ------------------------------------------------------------


def test_day_tour_always_pays_in_full(catalog):
    r = price(catalog, "T01", "2027-09-01")
    assert r.traveller.pay_in_full and r.traveller.deposit_usd == r.traveller.price_usd


def test_full_payment_boundary_30_vs_31_days(catalog):
    day30 = (TODAY + timedelta(days=30)).isoformat()   # 2026-12-19
    day31 = (TODAY + timedelta(days=31)).isoformat()   # 2026-12-20
    r30 = price(catalog, "T09", day30)
    r31 = price(catalog, "T09", day31)
    assert r30.traveller.pay_in_full and r30.traveller.deposit_usd == r30.traveller.price_usd
    assert not r31.traveller.pay_in_full
    assert r31.traveller.balance_due_date == date(2026, 11, 20)
    assert r31.traveller.deposit_usd + r31.traveller.balance_usd == r31.traveller.price_usd


def test_deposit_is_25_percent_of_rounded_price_rounded_up(catalog):
    r = price(catalog, "T09", "2027-05-03")  # 2125 x 25% = 531.25 -> 532
    assert r.traveller.deposit_usd == 532 and r.traveller.balance_usd == 1593


def test_start_today_is_allowed_and_paid_in_full(catalog):
    r = price(catalog, "T01", TODAY.isoformat())
    assert r.kind == "quote" and r.traveller.pay_in_full


# --- Seasons, USD hotel, rounding -------------------------------------------


def test_season_change_in_the_middle_of_a_tour(catalog):
    """T08 from 10 Dec 2026: nights 1-5 are Shoulder (to 14 Dec), nights 6-7 Peak (from 15 Dec)."""
    r = price(catalog, "T08", "2026-12-10")
    seasons = [n.season for n in r.internal.hotel_nights]
    assert seasons == ["Shoulder"] * 5 + ["Peak"] * 2
    peak_h09 = r.internal.hotel_nights[6]
    assert (peak_h09.hotel_id, peak_h09.cost) == ("H09", 36000)


def test_usd_hotel_h10_is_not_treated_as_lkr(catalog):
    """T13 = H11 x2 (LKR) + H10 x4 (USD 125 Shoulder). Hand-checked: 2445 / 612."""
    r = price(catalog, "T13", "2027-04-12")
    q = r.internal
    assert q.cost_usd_direct == 500                      # 4 nights x USD 125, not LKR 125
    assert q.cost_lkr == 77000 + 126000 + 90000 + 63000 + 44000
    assert q.cost_usd == q.cost_lkr / 300 + 500
    assert (r.traveller.price_usd, r.traveller.deposit_usd) == (2445, 612)


def test_t12_two_adults_prices_with_every_messy_hotel(catalog):
    """T12 in April uses H02 (text rate), H03 (Shoulder, no conflict), H04 (doubles exist), H08, H10 (USD)."""
    r = price(catalog, "T12", "2027-04-10")
    assert r.kind == "quote"
    assert {n.currency for n in r.internal.hotel_nights if n.hotel_id == "H10"} == {"USD"}
    assert r.traveller.price_usd % 5 == 0


@pytest.mark.parametrize("amount, expected", [
    ("315", 315), ("314.29", 315), ("310.01", 315), ("0.01", 5), ("2122.22", 2125), ("2125", 2125),
])
def test_round_up_to_next_5(amount, expected):
    assert round_up(D(amount), D(5)) == expected


def test_every_price_is_a_multiple_of_5_and_deposit_whole(catalog):
    for tour in ("T01", "T02", "T03", "T04", "T05", "T06", "T08", "T09", "T12", "T13"):
        r = price(catalog, tour, "2027-05-03", 4, (4,))  # even adults: T12's H04 has no single rate
        assert r.traveller.price_usd % 5 == 0, tour
        assert r.traveller.deposit_usd == r.traveller.deposit_usd.to_integral_value(), tour


def test_gross_profit_matches_margin(catalog):
    r = price(catalog, "T09", "2027-05-03")
    q = r.internal
    assert q.gross_profit_usd == q.price_usd - q.cost_usd
    assert D("25.0") <= q.gross_profit_pct <= D("25.2")  # rounding up adds a little margin


# --- Settings override (live demo) and determinism ------------------------------


def test_margin_override_changes_the_price(tmp_path, content, decisions):
    override = tmp_path / "o.json"
    override.write_text('{"margin_day_tour": "0.35"}', encoding="utf-8")
    cat = Catalog(workbook=load_workbook(overrides_path=override, today=TODAY), content=content, decisions=decisions)
    r = price(cat, "T01", "2027-01-10")  # 220 / 0.65 = 338.46 -> 340
    assert r.traveller.price_usd == 340
    assert r.internal.settings_overridden == ("margin_day_tour",)


def test_same_input_same_output(catalog):
    a = price(catalog, "T09", "2027-04-12", 2, (7, 10))
    b = price(catalog, "T09", "2027-04-12", 2, (7, 10))
    assert a == b


def test_tour_id_variants(catalog):
    assert price(catalog, "T-13", "2027-04-12").internal.tour_id == "T13"
    assert price(catalog, "t1", "2027-01-10").traveller.price_usd == 315


# --- Traveller schema never carries cost, margin or GP -------------------------


FORBIDDEN = ("cost", "margin", "gross", "profit", "gp", "lkr", "fx", "sell")


def test_traveller_schema_has_no_internal_fields():
    for name in QuoteForTraveller.model_fields:
        assert not any(word in name.lower() for word in FORBIDDEN), name


def test_traveller_payload_has_no_internal_values(catalog):
    r = price(catalog, "T09", "2027-04-12", 2, (7, 10))
    payload = r.traveller.model_dump_json().lower()
    for word in FORBIDDEN:
        assert f'"{word}' not in payload
    assert str(r.internal.cost_usd)[:6] not in payload


def test_traveller_schema_rejects_extra_fields(catalog):
    r = price(catalog, "T01", "2027-01-10")
    with pytest.raises(Exception):
        QuoteForTraveller(**r.traveller.model_dump(), cost_usd=1)


def test_traveller_view_content(catalog):
    t = price(catalog, "T09", "2027-04-12", 2, (7, 10)).traveller
    assert t.duration == "6 nights / 7 days" and t.end_date == date(2027, 4, 18)
    assert t.travellers_summary == "2 adults, 2 children (7, 10)"
    assert "English-speaking guide" in t.inclusions


def test_t06_uses_decision_duration_and_staff_note(catalog):
    r = price(catalog, "T06", "2027-01-10")
    assert r.traveller.duration == "1 day" and r.internal.nights == 0
    assert r.internal.staff_notes and "1 night / 2 days" in r.internal.staff_notes[0]

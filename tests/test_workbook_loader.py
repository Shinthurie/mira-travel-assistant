"""Workbook loader: one test per known data issue (see docs/DATA_AUDIT.md)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest

from mira.data.models import RateStatus
from mira.data.workbook import WorkbookError, load_workbook, normalise_tour_id, parse_date, parse_money

TODAY = date(2026, 11, 19)


def issue_codes(workbook) -> list[str]:
    return [i.code for i in workbook.issues]


# --- Settings -------------------------------------------------------------


def test_settings_read_from_workbook(workbook):
    s = workbook.settings
    assert s.fx_lkr_per_usd == Decimal("300")
    assert s.margin_day_tour == Decimal("0.3")
    assert s.margin_multi_day == Decimal("0.25")
    assert s.deposit_multi_day == Decimal("0.25")
    assert s.full_payment_within_days == 30
    assert s.max_group_size == 20
    assert s.round_up_to_usd == Decimal("5")
    assert s.fx_fixed_until == date(2027, 10, 31)
    assert s.overridden == ()


def test_override_file_changes_a_margin(tmp_path):
    override = tmp_path / "overrides.json"
    override.write_text(json.dumps({"margin_day_tour": "0.35"}), encoding="utf-8")
    wb = load_workbook(overrides_path=override, today=TODAY)
    assert wb.settings.margin_day_tour == Decimal("0.35")
    assert wb.settings.margin_multi_day == Decimal("0.25")  # untouched
    assert wb.settings.overridden == ("margin_day_tour",)
    assert "settings_overridden" in issue_codes(wb)


def test_override_file_rejects_unknown_keys(tmp_path):
    override = tmp_path / "overrides.json"
    override.write_text(json.dumps({"margin_day_tours": "0.35"}), encoding="utf-8")  # typo
    with pytest.raises(WorkbookError, match="unknown setting"):
        load_workbook(overrides_path=override, today=TODAY)


# --- Cell parsers ---------------------------------------------------------


@pytest.mark.parametrize("value, expected, ok", [
    (28000, Decimal("28000"), True),
    ("LKR 28,000", Decimal("28000"), True),
    ("28,000", Decimal("28000"), True),
    ("Rs. 5,500", Decimal("5500"), True),
    (None, None, True),          # empty = missing rate, decided by pricing
    ("", None, True),
    ("USD 125", None, False),    # wrong currency for an LKR row
    ("about 28k", None, False),
    (-5, None, False),
    (True, None, False),
])
def test_parse_money(value, expected, ok):
    amount, _, parsed_ok = parse_money(value, "LKR")
    assert (amount, parsed_ok) == (expected, ok)


@pytest.mark.parametrize("value, expected, ok", [
    (datetime(2026, 12, 15), date(2026, 12, 15), True),
    ("15/12/2026", date(2026, 12, 15), True),   # only DD/MM is a real date
    ("12/15/2026", date(2026, 12, 15), True),   # only MM/DD is a real date
    ("06/06/2027", date(2027, 6, 6), True),     # both readings are the same day
    ("2027-01-01", date(2027, 1, 1), True),
    ("05/06/2027", None, False),                # 5 June or 6 May: ambiguous -> unusable
    ("31/02/2027", None, False),
    (None, None, False),
])
def test_parse_date(value, expected, ok):
    parsed, _, parsed_ok = parse_date(value)
    assert (parsed, parsed_ok) == (expected, ok)


def test_tour_id_normalisation():
    assert normalise_tour_id("T-13") == "T13"
    assert normalise_tour_id("t5") == "T05"
    assert normalise_tour_id("Tour 13") is None


# --- Hotels tab -----------------------------------------------------------


def test_hotels_header_found_and_blank_rows_skipped(workbook):
    assert len(workbook.hotel_rates) == 52           # 53 data rows minus 1 blank
    assert 20 not in {r.row for r in workbook.hotel_rates}
    assert workbook.hotel_rates[0].row == 4          # title row 1, blank row 2, header row 3
    assert "title_rows_above_header" in issue_codes(workbook)
    assert "blank_row" in issue_codes(workbook)
    assert all(r.usable for r in workbook.hotel_rates)


def test_h02_text_double_rate_parses(workbook):
    rows = {r.row: r for r in workbook.hotel_rows("H02")}
    assert rows[8].double_room == Decimal("28000")
    assert rows[10].double_room == Decimal("28000")
    assert workbook.rate_for("H02", date(2026, 12, 2)).rate.double_room == Decimal("28000")


def test_h08_text_date_parses(workbook):
    lookup = workbook.rate_for("H08", date(2026, 12, 15))
    assert lookup.status == RateStatus.OK
    assert lookup.rate.season == "Peak" and lookup.rate.valid_from == date(2026, 12, 15)
    assert lookup.rate.double_room == Decimal("52000")
    assert workbook.rate_for("H08", date(2026, 12, 14)).rate.season == "Shoulder"


def test_h10_rates_are_usd(workbook):
    rows = workbook.hotel_rows("H10")
    assert len(rows) == 4 and all(r.currency == "USD" for r in rows)
    peak = workbook.rate_for("H10", date(2027, 2, 1)).rate
    assert (peak.double_room, peak.single_room, peak.extra_bed_child) == (Decimal(150), Decimal(125), Decimal(30))
    others = [r for r in workbook.hotel_rates if r.hotel_id != "H10"]
    assert all(r.currency == "LKR" for r in others)


def test_h04_has_no_single_rate(workbook):
    for row in workbook.hotel_rows("H04"):
        assert row.single_room is None
        assert row.double_room is not None and row.extra_bed_child is not None
        assert row.usable  # doubles still bookable; pricing returns missing_rate if a single is needed


def test_h07_expired_for_2027_01_20(workbook):
    lookup = workbook.rate_for("H07", date(2027, 1, 20), today=TODAY)
    assert lookup.status == RateStatus.EXPIRED
    assert lookup.rate is None
    assert "2026-10-31" in lookup.detail


def test_h03_jan_mar_2027_is_conflict(workbook):
    for night in (date(2027, 1, 1), date(2027, 2, 14), date(2027, 3, 31)):
        lookup = workbook.rate_for("H03", night)
        assert lookup.status == RateStatus.CONFLICT, night
        assert lookup.rate is None
        assert {r.row for r in lookup.candidates} == {13, 56}
    assert "overlapping_rates_conflict" in issue_codes(workbook)


def test_h03_december_2026_is_not_conflict(workbook):
    assert workbook.rate_for("H03", date(2026, 12, 20)).rate.double_room == Decimal("30000")  # Peak, row 13
    assert workbook.rate_for("H03", date(2026, 12, 1)).rate.double_room == Decimal("25000")   # Shoulder
    assert workbook.rate_for("H03", date(2027, 4, 1)).rate.double_room == Decimal("25000")


def test_season_change_between_two_nights(workbook):
    assert workbook.rate_for("H01", date(2026, 12, 14)).rate.season == "Shoulder"
    assert workbook.rate_for("H01", date(2026, 12, 15)).rate.season == "Peak"


def test_rates_beyond_31_oct_2027(workbook):
    assert workbook.rate_for("H01", date(2027, 10, 31)).status == RateStatus.OK
    lookup = workbook.rate_for("H01", date(2027, 11, 1))
    assert lookup.status == RateStatus.BEYOND_VALIDITY


def test_unknown_hotel(workbook):
    assert workbook.rate_for("H99", date(2027, 1, 1)).status == RateStatus.UNKNOWN_HOTEL


# --- Tours and Transport tabs ---------------------------------------------


def test_t13_id_normalised(workbook):
    assert "T13" in workbook.tours and "T-13" not in workbook.tours
    assert workbook.tour("T-13").raw_id == "T-13"
    assert workbook.tour("T13").hotel_ids_by_night == ("H11", "H11", "H10", "H10", "H10", "H10")
    assert "id_normalised" in issue_codes(workbook)


def test_every_tour_row_is_consistent(workbook):
    """Hotel count equals Nights, every hotel exists, day tours have no nights."""
    for tour in workbook.tours.values():
        assert tour.usable, (tour.tour_id, tour.problems)
        assert len(tour.hotel_ids_by_night) == tour.nights


def test_tour_types_and_rates(workbook):
    t01 = workbook.tour("T01")
    assert (t01.tour_type, t01.days, t01.nights) == ("day_tour", 1, 0)
    assert (t01.guide_lkr_per_day, t01.entrance_adult_lkr, t01.entrance_child_lkr,
            t01.meals_lkr_per_adult_per_day) == (9000, 16500, 8250, 3000)
    t09 = workbook.tour("T09")
    assert (t09.tour_type, t09.days, t09.nights) == ("multi_day", 7, 6)
    assert t09.hotel_ids_by_night == ("H12", "H12", "H02", "H02", "H03", "H03")
    assert workbook.tour("T06").tour_type == "day_tour"  # see data decision T06


def test_tours_without_rates(workbook, content):
    """T10 and T16 are published but have no rates; T15 has rates but is a draft."""
    published_tours = {d.id for d in content.published("tour")}
    assert published_tours - set(workbook.tours) == {"T10", "T16"}
    assert "T15" in workbook.tours and "T15" not in published_tours


def test_tour_notes_are_logged(workbook):
    assert workbook.tour("T15").notes == "New version – not launched yet"
    assert any(i.code == "tour_note" and "T15" in i.message for i in workbook.issues)


@pytest.mark.parametrize("group, vehicle", [
    (1, "Car"), (3, "Car"), (4, "Van"), (8, "Van"), (9, "Mini coach"), (20, "Mini coach"),
])
def test_vehicle_boundaries(workbook, group, vehicle):
    assert workbook.vehicle_for(group).name == vehicle


@pytest.mark.parametrize("group", [0, 21])
def test_no_vehicle_outside_1_to_20(workbook, group):
    assert workbook.vehicle_for(group) is None


# --- A deliberately messy workbook: ambiguous rows become unusable, never guessed ---


def _messy_workbook(path):
    """A minimal copy of the real layout with bad cells, written to a temp folder."""
    real = openpyxl.load_workbook(__import__("mira").config.WORKBOOK_PATH)
    hotels = real["Hotels"]
    hotels["D12"] = "05/06/2027"       # H03 Shoulder: ambiguous date
    hotels["F21"] = "about 22k"        # H05 Shoulder: unreadable money
    real.save(path)


def test_ambiguous_text_date_is_unusable(tmp_path):
    path = tmp_path / "messy.xlsx"
    _messy_workbook(path)
    wb = load_workbook(path=path, today=TODAY)
    h03 = {r.row: r for r in wb.hotel_rows("H03")}[12]
    assert not h03.usable and "ambiguous" in h03.problems[0]
    h05 = {r.row: r for r in wb.hotel_rows("H05")}[21]
    assert not h05.usable and "unparseable" in h05.problems[0]
    # The night that row would have covered now has no rate, and the reason is explained.
    lookup = wb.rate_for("H05", date(2026, 12, 1), today=TODAY)
    assert lookup.status == RateStatus.MISSING
    assert "row 21" in lookup.detail

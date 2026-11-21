"""Load the sales team's rate workbook (``rate_sheet_2026-27.xlsx``) as-is, into typed models.

Rules (see docs/DATA_AUDIT.md):
- Parse what is unambiguous (e.g. the text "LKR 28,000", the date text "15/12/2026").
- Flag what is ambiguous: the row is kept with ``usable=False`` and its reasons.
- Never guess. Hotel rate lookups return an explicit status (ok / conflict / expired / ...).

Columns are found by their header text, not by position, so a moved column fails loudly
instead of silently reading the wrong numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from mira import config
from mira.data.models import (
    DataIssue,
    HotelRate,
    IssueSeverity,
    RateLookup,
    RateStatus,
    Season,
    Settings,
    TourRate,
    Vehicle,
)


class WorkbookError(Exception):
    """The workbook's structure is not what we expect (missing tab, header or setting)."""


# ---------------------------------------------------------------------------
# Small cell parsers
# ---------------------------------------------------------------------------

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})


def normalise_label(text: Any) -> str:
    """Lower-case a header/label, unify dashes and spaces: 'Margin – day tours' -> 'margin - day tours'."""
    return " ".join(str(text).translate(_DASHES).lower().split())


_MONEY_TEXT = re.compile(r"^(?:(LKR|USD|RS\.?)\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)$", re.IGNORECASE)


def parse_money(value: Any, expected_currency: str) -> tuple[Decimal | None, str | None, bool]:
    """Parse a money cell.

    Returns ``(amount, note, ok)``:
    - ``(None, None, True)`` for an empty cell (a missing rate, which is not an error here),
    - ``(Decimal, None, True)`` for a plain number,
    - ``(Decimal, note, True)`` for unambiguous text such as "LKR 28,000",
    - ``(None, reason, False)`` for anything else (the row becomes unusable).
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None, None, True
    if isinstance(value, bool):
        return None, f"not a number: {value!r}", False
    if isinstance(value, (int, float)):
        amount = Decimal(str(value))
        if amount < 0:
            return None, f"negative amount {value!r}", False
        return amount, None, True
    if isinstance(value, str):
        match = _MONEY_TEXT.match(value.strip())
        if not match:
            return None, f"unparseable money text {value!r}", False
        prefix = (match.group(1) or "").upper().rstrip(".")
        prefix = "LKR" if prefix == "RS" else prefix
        if prefix and prefix != expected_currency:
            return None, f"text {value!r} says {prefix} but the row is {expected_currency}", False
        try:
            amount = Decimal(match.group(2).replace(",", ""))
        except InvalidOperation:
            return None, f"unparseable money text {value!r}", False
        return amount, f"money stored as text {value!r}, parsed as {amount}", True
    return None, f"unexpected cell type {type(value).__name__}", False


_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def parse_date(value: Any) -> tuple[date | None, str | None, bool]:
    """Parse a date cell. Returns ``(date, note, ok)`` like :func:`parse_money`.

    Text like "15/12/2026" is parsed only if just one reading (DD/MM or MM/DD) is a real date.
    "05/06/2027" could be 5 June or 6 May, so it is rejected as ambiguous.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None, "empty date", False
    if isinstance(value, datetime):
        return value.date(), None, True
    if isinstance(value, date):
        return value, None, True
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text), f"date stored as text {value!r}", True
        except ValueError:
            pass
        match = _SLASH_DATE.match(text)
        if match:
            a, b, year = (int(g) for g in match.groups())
            readings = set()
            for day, month in ((a, b), (b, a)):  # DD/MM first, then MM/DD
                try:
                    readings.add(date(year, month, day))
                except ValueError:
                    pass
            if len(readings) == 1:
                parsed = readings.pop()
                return parsed, f"date stored as text {value!r}, parsed as {parsed.isoformat()}", True
            if len(readings) > 1:
                return None, f"ambiguous date text {value!r} (DD/MM or MM/DD)", False
        return None, f"unparseable date {value!r}", False
    return None, f"unexpected cell type {type(value).__name__}", False


_TOUR_ID = re.compile(r"^T-?(\d+)$", re.IGNORECASE)
_HOTEL_ID = re.compile(r"^H\d{2}$")


def normalise_tour_id(raw: str) -> str | None:
    """'T-13' -> 'T13', 't5' -> 'T05'. Returns None if it doesn't look like a tour id."""
    match = _TOUR_ID.match(str(raw).strip())
    return f"T{int(match.group(1)):02d}" if match else None


def _is_blank_row(values: tuple[Any, ...]) -> bool:
    return all(v is None or (isinstance(v, str) and v.strip() == "") for v in values)


def _find_header(sheet, first_label: str) -> int:
    """Return the 1-based row number whose column A equals ``first_label`` (title rows may sit above it)."""
    for row in sheet.iter_rows(min_col=1, max_col=1):
        cell = row[0]
        if cell.value is not None and normalise_label(cell.value) == first_label:
            return cell.row
    raise WorkbookError(f"{sheet.title}: header row starting with {first_label!r} not found")


def _column_map(sheet, header_row: int, expected: dict[str, str]) -> dict[str, int]:
    """Map our field names to 0-based column indexes using the header text."""
    headers = {
        normalise_label(c.value): i
        for i, c in enumerate(sheet[header_row])
        if c.value is not None
    }
    columns: dict[str, int] = {}
    for label, field_name in expected.items():
        if label not in headers:
            raise WorkbookError(f"{sheet.title}: column {label!r} not found in row {header_row}")
        columns[field_name] = headers[label]
    return columns


# ---------------------------------------------------------------------------
# Loaded workbook
# ---------------------------------------------------------------------------


@dataclass
class Workbook:
    """Everything from the rate workbook, plus every issue found while loading."""

    settings: Settings
    seasons: list[Season]
    vehicles: list[Vehicle]
    tours: dict[str, TourRate]
    hotel_rates: list[HotelRate]
    issues: list[DataIssue] = field(default_factory=list)

    def tour(self, tour_id: str) -> TourRate | None:
        """The Tours-tab row for a tour id (accepts 'T13' or 'T-13'), or None if there are no rates."""
        normalised = normalise_tour_id(tour_id)
        return self.tours.get(normalised) if normalised else None

    def hotel_rows(self, hotel_id: str) -> list[HotelRate]:
        """All Hotels-tab rows for one hotel (usable and unusable)."""
        return [r for r in self.hotel_rates if r.hotel_id == hotel_id]

    def vehicle_for(self, group_size: int) -> Vehicle | None:
        """Vehicle whose min/max covers the group size (adults + children 2-11), or None."""
        for vehicle in self.vehicles:
            if vehicle.min_travellers <= group_size <= vehicle.max_travellers:
                return vehicle
        return None

    def rate_for(self, hotel_id: str, night: date, today: date | None = None) -> RateLookup:
        """Find the one rate that covers ``night`` for ``hotel_id``, or explain why there isn't one."""
        today = today or config.today()
        all_rows = self.hotel_rows(hotel_id)
        if not all_rows:
            return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.UNKNOWN_HOTEL,
                              detail=f"{hotel_id} is not in the Hotels tab")

        usable = [r for r in all_rows if r.usable]
        covering = [r for r in usable if r.covers(night)]

        if len(covering) == 1:
            return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.OK,
                              rate=covering[0], candidates=tuple(covering))

        if len(covering) > 1:
            values = {(r.currency, r.double_room, r.single_room, r.extra_bed_child) for r in covering}
            if len(values) == 1:  # exact duplicates agree, so the rate is unambiguous
                return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.OK,
                                  rate=covering[0], candidates=tuple(covering))
            rows = ", ".join(f"row {r.row}" for r in covering)
            return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.CONFLICT,
                              candidates=tuple(covering),
                              detail=f"{hotel_id} has conflicting rates for {night.isoformat()} ({rows})")

        # No usable row covers the night: work out which kind of gap it is.
        ends = [r.valid_to for r in usable if r.valid_to is not None]
        unusable_covering = [r for r in all_rows if not r.usable and r.covers(night)]
        if ends and max(ends) < today:
            return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.EXPIRED,
                              detail=f"all {hotel_id} rates ended on {max(ends).isoformat()}")
        if ends and night > max(ends):
            return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.BEYOND_VALIDITY,
                              detail=f"{hotel_id} rates run only until {max(ends).isoformat()}")
        detail = f"no {hotel_id} rate covers {night.isoformat()}"
        if unusable_covering:
            detail += "; unusable row(s): " + "; ".join(
                f"row {r.row}: {', '.join(r.problems)}" for r in unusable_covering)
        return RateLookup(hotel_id=hotel_id, night=night, status=RateStatus.MISSING,
                          candidates=tuple(unusable_covering), detail=detail)


# ---------------------------------------------------------------------------
# Tab loaders
# ---------------------------------------------------------------------------

_SETTINGS_LABELS = {
    "fx rate (lkr per 1 usd)": "fx_lkr_per_usd",
    "margin - day tours": "margin_day_tour",
    "margin - multi-day tours": "margin_multi_day",
    "deposit - multi-day tours": "deposit_multi_day",
    "full payment if starting within (days)": "full_payment_within_days",
    "max group size": "max_group_size",
    "round booking total up to next (usd)": "round_up_to_usd",
}
_INT_SETTINGS = {"full_payment_within_days", "max_group_size"}
_UNTIL_DATE = re.compile(r"until (\d{1,2} [A-Za-z]{3} \d{4})")


def _load_settings(sheet, issues: list[DataIssue]) -> dict[str, Any]:
    header = _find_header(sheet, "setting")
    values: dict[str, Any] = {}
    for row in sheet.iter_rows(min_row=header + 1):
        label, value = row[0].value, row[1].value
        if label is None:
            continue
        name = _SETTINGS_LABELS.get(normalise_label(label))
        if name is None:
            issues.append(DataIssue(code="unknown_setting", severity=IssueSeverity.WARNING,
                                    source=f"Settings!A{row[0].row}", message=f"ignored setting {label!r}"))
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WorkbookError(f"Settings!B{row[0].row}: {label!r} is not a number: {value!r}")
        values[name] = int(value) if name in _INT_SETTINGS else Decimal(str(value))
        notes = row[2].value if len(row) > 2 else None
        if name == "fx_lkr_per_usd" and isinstance(notes, str):
            match = _UNTIL_DATE.search(notes)
            if match:
                values["fx_fixed_until"] = datetime.strptime(match.group(1), "%d %b %Y").date()
    missing = set(_SETTINGS_LABELS.values()) - values.keys()
    if missing:
        raise WorkbookError(f"Settings tab is missing: {sorted(missing)}")
    return values


def apply_overrides(values: dict[str, Any], overrides_path: Path | None) -> Settings:
    """Build Settings from workbook values, then apply the optional JSON override file.

    The override file is for the live demo, e.g. ``{"margin_day_tour": "0.35"}``.
    Unknown keys are an error, so a typo can't be silently ignored.
    """
    overridden: list[str] = []
    if overrides_path is not None and overrides_path.exists():
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
        allowed = set(_SETTINGS_LABELS.values())
        unknown = set(data) - allowed
        if unknown:
            raise WorkbookError(f"{overrides_path.name}: unknown setting(s) {sorted(unknown)}; allowed: {sorted(allowed)}")
        for name, raw in data.items():
            values[name] = int(raw) if name in _INT_SETTINGS else Decimal(str(raw))
            overridden.append(name)
    return Settings(**values, overridden=tuple(sorted(overridden)))


def _load_seasons(sheet) -> list[Season]:
    header = _find_header(sheet, "season")
    seasons = []
    for row in sheet.iter_rows(min_row=header + 1, values_only=True):
        if _is_blank_row(row):
            continue
        start, _, ok1 = parse_date(row[1])
        end, _, ok2 = parse_date(row[2])
        if not (ok1 and ok2):
            raise WorkbookError(f"Seasons: bad dates in row {row!r}")
        seasons.append(Season(name=str(row[0]).strip(), valid_from=start, valid_to=end))
    return seasons


def _load_transport(sheet) -> list[Vehicle]:
    header = _find_header(sheet, "vehicle")
    vehicles = []
    for row in sheet.iter_rows(min_row=header + 1, values_only=True):
        if _is_blank_row(row):
            continue
        amount, note, ok = parse_money(row[3], "LKR")
        if not ok or amount is None:
            raise WorkbookError(f"Transport: bad rate in row {row!r}: {note}")
        vehicles.append(Vehicle(name=str(row[0]).strip(), min_travellers=int(row[1]),
                                max_travellers=int(row[2]), lkr_per_day=amount))
    vehicles.sort(key=lambda v: v.min_travellers)
    return vehicles


_HOTEL_COLUMNS = {
    "hotel id": "hotel_id",
    "hotel": "hotel_name",
    "season": "season",
    "valid from": "valid_from",
    "valid to": "valid_to",
    "double room (lkr)": "double_room",
    "single room (lkr)": "single_room",
    "extra bed - child (lkr)": "extra_bed_child",
    "notes": "notes",
}


def _load_hotels(sheet, issues: list[DataIssue]) -> list[HotelRate]:
    header = _find_header(sheet, "hotel id")
    if header > 1:
        issues.append(DataIssue(code="title_rows_above_header", severity=IssueSeverity.INFO,
                                source=f"Hotels!A1:A{header - 1}",
                                message=f"header is on row {header}; rows above it were skipped"))
    cols = _column_map(sheet, header, _HOTEL_COLUMNS)
    rates: list[HotelRate] = []

    for row in sheet.iter_rows(min_row=header + 1):
        values = tuple(c.value for c in row)
        row_no = row[0].row
        if _is_blank_row(values):
            issues.append(DataIssue(code="blank_row", severity=IssueSeverity.INFO,
                                    source=f"Hotels!{row_no}", message="blank row skipped"))
            continue

        def cell(name: str) -> Any:
            return values[cols[name]] if cols[name] < len(values) else None

        def ref(name: str) -> str:
            return f"Hotels!{openpyxl.utils.get_column_letter(cols[name] + 1)}{row_no}"

        problems: list[str] = []
        notes = cell("notes")
        notes = str(notes).strip() if notes not in (None, "") else None
        # The Notes column is the only place a non-LKR currency is stated (H10: "USD (Cinnamon contract)").
        currency = "USD" if notes and re.search(r"\bUSD\b", notes) else "LKR"
        if notes:
            issues.append(DataIssue(code="hotel_note", severity=IssueSeverity.WARNING, source=ref("notes"),
                                    message=f"{cell('hotel_id')}: note {notes!r}"
                                            + (" -> rates read as USD" if currency == "USD" else "")))

        parsed_dates: dict[str, date | None] = {}
        for name in ("valid_from", "valid_to"):
            parsed, note, ok = parse_date(cell(name))
            parsed_dates[name] = parsed
            if not ok:
                problems.append(f"{name}: {note}")
                issues.append(DataIssue(code="bad_date", severity=IssueSeverity.BLOCKING, source=ref(name),
                                        message=f"{cell('hotel_id')}: {note}; row unusable"))
            elif note:
                issues.append(DataIssue(code="text_date_parsed", severity=IssueSeverity.INFO,
                                        source=ref(name), message=f"{cell('hotel_id')}: {note}"))

        amounts: dict[str, Decimal | None] = {}
        for name in ("double_room", "single_room", "extra_bed_child"):
            amount, note, ok = parse_money(cell(name), currency)
            amounts[name] = amount
            if not ok:
                problems.append(f"{name}: {note}")
                issues.append(DataIssue(code="bad_money", severity=IssueSeverity.BLOCKING, source=ref(name),
                                        message=f"{cell('hotel_id')}: {note}; row unusable"))
            elif note:
                issues.append(DataIssue(code="text_money_parsed", severity=IssueSeverity.INFO,
                                        source=ref(name), message=f"{cell('hotel_id')}: {note}"))
            elif amount is None:
                issues.append(DataIssue(code="missing_rate", severity=IssueSeverity.WARNING, source=ref(name),
                                        message=f"{cell('hotel_id')}: no {name.replace('_', ' ')} rate"))

        start, end = parsed_dates["valid_from"], parsed_dates["valid_to"]
        if start and end and start > end:
            problems.append("valid_from is after valid_to")

        hotel_id = str(cell("hotel_id")).strip()
        if not _HOTEL_ID.match(hotel_id):
            problems.append(f"unexpected hotel id {hotel_id!r}")

        rates.append(HotelRate(
            hotel_id=hotel_id, hotel_name=str(cell("hotel_name") or "").strip(),
            season=str(cell("season") or "").strip(), valid_from=start, valid_to=end,
            currency=currency, notes=notes, row=row_no, usable=not problems, problems=tuple(problems),
            **amounts,
        ))
    return rates


def _check_overlaps(rates: list[HotelRate], issues: list[DataIssue]) -> None:
    """Log any two usable rows of the same hotel whose date ranges overlap (e.g. H03 rows 13 and 56)."""
    usable = [r for r in rates if r.usable and r.valid_from and r.valid_to]
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            if a.hotel_id != b.hotel_id:
                continue
            if a.valid_from <= b.valid_to and b.valid_from <= a.valid_to:
                start, end = max(a.valid_from, b.valid_from), min(a.valid_to, b.valid_to)
                same = (a.currency, a.double_room, a.single_room, a.extra_bed_child) == \
                       (b.currency, b.double_room, b.single_room, b.extra_bed_child)
                issues.append(DataIssue(
                    code="overlapping_rates_same" if same else "overlapping_rates_conflict",
                    severity=IssueSeverity.INFO if same else IssueSeverity.BLOCKING,
                    source=f"Hotels!{a.row} & Hotels!{b.row}",
                    message=f"{a.hotel_id}: rows {a.row} and {b.row} both cover {start.isoformat()} to "
                            f"{end.isoformat()}" + ("" if same else " with different rates; no quote for those nights"),
                ))


def _check_seasons(rates: list[HotelRate], seasons: list[Season], today: date, issues: list[DataIssue]) -> None:
    """Cross-check hotel rows against the Seasons tab and report hotels whose rates have all expired."""
    known = {(s.name, s.valid_from, s.valid_to) for s in seasons}
    for r in rates:
        if r.usable and (r.season, r.valid_from, r.valid_to) not in known:
            issues.append(DataIssue(code="season_mismatch", severity=IssueSeverity.INFO, source=f"Hotels!{r.row}",
                                    message=f"{r.hotel_id} {r.season} {r.valid_from} to {r.valid_to} "
                                            "does not match a Seasons-tab row"))
    for hotel_id in sorted({r.hotel_id for r in rates}):
        ends = [r.valid_to for r in rates if r.hotel_id == hotel_id and r.usable and r.valid_to]
        if ends and max(ends) < today:
            issues.append(DataIssue(code="rates_expired", severity=IssueSeverity.BLOCKING, source=f"Hotels!{hotel_id}",
                                    message=f"{hotel_id}: every rate ended by {max(ends).isoformat()} "
                                            f"(before today, {today.isoformat()})"))


_TOUR_COLUMNS = {
    "tour id": "tour_id",
    "tour": "title",
    "type": "type",
    "days": "days",
    "nights": "nights",
    "guide (lkr per day, per group)": "guide_lkr_per_day",
    "entrance adult (lkr, whole tour)": "entrance_adult_lkr",
    "entrance child 2-11 (lkr, whole tour)": "entrance_child_lkr",
    "meals (lkr per adult per day)": "meals_lkr_per_adult_per_day",
    "hotels by night (in order)": "hotels",
    "notes": "notes",
}
_TOUR_TYPES = {"day tour": "day_tour", "multi-day": "multi_day"}
_NO_HOTELS = {"", "-", "none", "n/a"}


def _load_tours(sheet, hotel_ids: set[str], issues: list[DataIssue]) -> dict[str, TourRate]:
    header = _find_header(sheet, "tour id")
    cols = _column_map(sheet, header, _TOUR_COLUMNS)
    tours: dict[str, TourRate] = {}

    for row in sheet.iter_rows(min_row=header + 1):
        values = tuple(c.value for c in row)
        row_no = row[0].row
        if _is_blank_row(values):
            continue

        def cell(name: str) -> Any:
            return values[cols[name]] if cols[name] < len(values) else None

        problems: list[str] = []
        raw_id = str(cell("tour_id")).strip()
        tour_id = normalise_tour_id(raw_id)
        if tour_id is None:
            issues.append(DataIssue(code="bad_tour_id", severity=IssueSeverity.BLOCKING,
                                    source=f"Tours!A{row_no}", message=f"cannot read tour id {raw_id!r}; row skipped"))
            continue
        if tour_id != raw_id:
            issues.append(DataIssue(code="id_normalised", severity=IssueSeverity.INFO, source=f"Tours!A{row_no}",
                                    message=f"tour id {raw_id!r} normalised to {tour_id!r} to match content"))

        tour_type = _TOUR_TYPES.get(normalise_label(cell("type") or ""))
        if tour_type is None:
            problems.append(f"unknown tour type {cell('type')!r}")

        days, nights = cell("days"), cell("nights")
        if not isinstance(days, int) or not isinstance(nights, int) or days < 1 or nights < 0:
            problems.append(f"bad days/nights {days!r}/{nights!r}")
            days, nights = days if isinstance(days, int) else 0, nights if isinstance(nights, int) else 0

        amounts: dict[str, Decimal] = {}
        for name in ("guide_lkr_per_day", "entrance_adult_lkr", "entrance_child_lkr", "meals_lkr_per_adult_per_day"):
            amount, note, ok = parse_money(cell(name), "LKR")
            if not ok or amount is None:  # a blank cost on a tour row is not the same as zero
                problems.append(f"{name}: {note or 'empty'}")
                amount = Decimal(0)
            amounts[name] = amount

        hotels_raw = str(cell("hotels") or "").translate(_DASHES).strip()
        hotel_list: tuple[str, ...] = () if hotels_raw.lower() in _NO_HOTELS else tuple(
            h.strip() for h in hotels_raw.split(","))
        for h in hotel_list:
            if not _HOTEL_ID.match(h):
                problems.append(f"bad hotel id {h!r}")
            elif h not in hotel_ids:
                problems.append(f"hotel {h} not in Hotels tab")
        if len(hotel_list) != nights:
            problems.append(f"{len(hotel_list)} hotel nights listed but Nights = {nights}")
        if tour_type == "day_tour" and nights != 0:
            problems.append("day tour with nights > 0")

        notes = cell("notes")
        notes = str(notes).strip() if notes not in (None, "") else None
        if notes:
            issues.append(DataIssue(code="tour_note", severity=IssueSeverity.WARNING, source=f"Tours!K{row_no}",
                                    message=f"{tour_id}: note {notes!r}"))

        if tour_id in tours:
            problems.append(f"duplicate tour id (also row {tours[tour_id].row})")

        for p in problems:
            issues.append(DataIssue(code="tour_row_unusable", severity=IssueSeverity.BLOCKING,
                                    source=f"Tours!{row_no}", message=f"{tour_id}: {p}"))

        tours[tour_id] = TourRate(
            tour_id=tour_id, raw_id=raw_id, title=str(cell("title") or "").strip(),
            tour_type=tour_type or "multi_day", days=days, nights=nights,
            hotel_ids_by_night=hotel_list, notes=notes, row=row_no,
            usable=not problems, problems=tuple(problems), **amounts,
        )
    return tours


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_workbook(path: Path = config.WORKBOOK_PATH, overrides_path: Path | None = None,
                  today: date | None = None) -> Workbook:
    """Read the workbook file (never written to) and return a :class:`Workbook`.

    ``overrides_path`` defaults to the env var ``PRICING_OVERRIDES_FILE`` (if set).
    """
    today = today or config.today()
    if overrides_path is None:
        overrides_path = config.pricing_overrides_path()

    book = openpyxl.load_workbook(path, data_only=True, read_only=False)
    for tab in ("Settings", "Seasons", "Tours", "Hotels", "Transport"):
        if tab not in book.sheetnames:
            raise WorkbookError(f"workbook has no {tab!r} tab (found {book.sheetnames})")

    issues: list[DataIssue] = []
    settings = apply_overrides(_load_settings(book["Settings"], issues), overrides_path)
    if settings.overridden:
        issues.append(DataIssue(code="settings_overridden", severity=IssueSeverity.WARNING,
                                source=str(overrides_path), message=f"overridden: {', '.join(settings.overridden)}"))
    seasons = _load_seasons(book["Seasons"])
    vehicles = _load_transport(book["Transport"])
    hotel_rates = _load_hotels(book["Hotels"], issues)
    _check_overlaps(hotel_rates, issues)
    _check_seasons(hotel_rates, seasons, today, issues)
    tours = _load_tours(book["Tours"], {r.hotel_id for r in hotel_rates}, issues)
    book.close()

    return Workbook(settings=settings, seasons=seasons, vehicles=vehicles, tours=tours,
                    hotel_rates=hotel_rates, issues=issues)

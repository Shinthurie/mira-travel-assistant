"""Typed models for everything loaded from the dataset.

Money is always ``Decimal`` (never float). Rows that cannot be used safely are kept,
but marked ``usable=False`` with the reasons, so nothing is silently dropped or fixed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    """Base model: immutable, so loaded data can't be changed by accident."""

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Data issues (everything odd the loaders find)
# ---------------------------------------------------------------------------


class IssueSeverity(str, Enum):
    INFO = "info"        # parsed fine, but worth knowing (e.g. text number parsed)
    WARNING = "warning"  # parsed, but a human should review (e.g. a Notes cell)
    BLOCKING = "blocking"  # the row/document cannot be used for prices or answers


class DataIssue(Frozen):
    """One problem found while loading. Printed by ``python -m mira.data``."""

    code: str            # machine-readable, e.g. "text_money_parsed"
    severity: IssueSeverity
    source: str          # e.g. "Hotels!F8" or "content/tours/kandy-heritage-stay.md"
    message: str


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


class Settings(Frozen):
    """Settings tab (optionally overridden by a JSON file for the live demo)."""

    fx_lkr_per_usd: Decimal
    margin_day_tour: Decimal
    margin_multi_day: Decimal
    deposit_multi_day: Decimal
    full_payment_within_days: int
    max_group_size: int
    round_up_to_usd: Decimal
    fx_fixed_until: date | None = None
    overridden: tuple[str, ...] = ()  # names of fields changed by the override file


class Season(Frozen):
    name: str
    valid_from: date
    valid_to: date


class Vehicle(Frozen):
    name: str
    min_travellers: int
    max_travellers: int
    lkr_per_day: Decimal


TourType = Literal["day_tour", "multi_day"]


class TourRate(Frozen):
    """One row of the Tours tab."""

    tour_id: str             # normalised, e.g. "T13"
    raw_id: str              # as written in the sheet, e.g. "T-13"
    title: str
    tour_type: TourType
    days: int
    nights: int
    guide_lkr_per_day: Decimal
    entrance_adult_lkr: Decimal
    entrance_child_lkr: Decimal
    meals_lkr_per_adult_per_day: Decimal
    hotel_ids_by_night: tuple[str, ...]  # one hotel id per night, in order
    notes: str | None = None
    row: int
    usable: bool = True
    problems: tuple[str, ...] = ()


class HotelRate(Frozen):
    """One row of the Hotels tab: a room rate valid for a date range (inclusive)."""

    hotel_id: str
    hotel_name: str
    season: str
    valid_from: date | None
    valid_to: date | None
    currency: Literal["LKR", "USD"]
    double_room: Decimal | None
    single_room: Decimal | None
    extra_bed_child: Decimal | None
    notes: str | None = None
    row: int
    usable: bool = True
    problems: tuple[str, ...] = ()

    def covers(self, night: date) -> bool:
        """True if this row's Valid from/to range includes the given night."""
        if self.valid_from is None or self.valid_to is None:
            return False
        return self.valid_from <= night <= self.valid_to


class RateStatus(str, Enum):
    OK = "ok"
    CONFLICT = "conflict"                # two different usable rows cover the night
    EXPIRED = "expired"                  # hotel's rates all ended before today
    BEYOND_VALIDITY = "beyond_validity"  # night is after the last rate we have
    MISSING = "missing"                  # hotel has rates, but none covers this night
    UNKNOWN_HOTEL = "unknown_hotel"      # hotel id not in the Hotels tab


class RateLookup(Frozen):
    """Result of looking up the rate for one hotel on one night."""

    hotel_id: str
    night: date
    status: RateStatus
    rate: HotelRate | None = None
    candidates: tuple[HotelRate, ...] = ()  # all rows involved (for conflicts / staff flags)
    detail: str = ""


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


class Section(Frozen):
    """A part of a document under one Markdown heading (used for citations)."""

    heading: str  # "" for text before the first heading
    text: str


class Supersession(Frozen):
    """A passage on an older page replaced by a newer policy."""

    doc_id: str
    line: str
    topic: str            # "cancellation" or "children"
    superseded_by: str    # policy id, e.g. "P02"
    policy_title: str
    reason: str


class ContentDoc(Frozen):
    """One Markdown file with YAML front matter."""

    id: str
    type: str
    title: str
    status: Literal["published", "draft"]
    last_updated: date
    path: str  # relative to the dataset folder, e.g. "content/tours/kandy-city-tour.md"
    body: str  # HTML comments removed
    sections: tuple[Section, ...] = ()
    # Tour-only fields
    category: str | None = None
    duration: str | None = None
    start: str | None = None
    destinations: tuple[str, ...] = ()
    hotels: tuple[str, ...] = ()
    # Marketing copy that conflicts with the rates. NEVER shown as a price:
    # excluded from serialisation and repr so it can't reach a prompt or UI by accident.
    teaser_price: str | None = Field(default=None, exclude=True, repr=False)

    @property
    def is_published(self) -> bool:
        return self.status == "published"

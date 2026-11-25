"""Pricing input and output models.

Two separate quote schemas (project rule 6 (README)):
- ``QuoteInternal``: cost, sell price, gross profit and the full breakdown. Staff only.
- ``QuoteForTraveller``: price, deposit, balance and inclusions. It has NO cost, margin or GP
  fields, and ``extra="forbid"`` means nobody can add one by accident. UI components accept only this.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PricingRequest(_Frozen):
    """What the engine needs. ``child_ages`` lists every traveller under 18 by age."""

    tour_id: str
    start_date: date
    adults: int
    child_ages: tuple[int, ...] = ()


class NoQuoteReason(str, Enum):
    UNKNOWN_TOUR = "unknown_tour"                # no such tour in our content
    TOUR_NOT_PUBLISHED = "tour_not_published"    # draft (e.g. T15)
    TOUR_NOT_QUOTABLE = "tour_not_quotable"      # data decision (e.g. T14 stale promotion)
    NO_RATES_FOR_TOUR = "no_rates_for_tour"      # published but not in the Tours tab (T10, T16)
    RATE_DATA_UNUSABLE = "rate_data_unusable"    # the Tours row itself is broken
    INVALID_TRAVELLERS = "invalid_travellers"    # no adult, negative counts, impossible ages
    GROUP_TOO_LARGE = "group_too_large"          # more than 20 (adults + children 2-11)
    START_DATE_IN_PAST = "start_date_in_past"
    BEYOND_RATE_VALIDITY = "beyond_rate_validity"  # after 31 Oct 2027 (rates and FX end)
    MISSING_RATE = "missing_rate"                # e.g. H04 has no single room
    EXPIRED_RATE = "expired_rate"                # e.g. H07 contract ended 31 Oct 2026
    CONFLICTING_RATE = "conflicting_rate"        # e.g. H03 has two different Peak rows


class NoQuote(_Frozen):
    """No price can be given. The traveller sees ``traveller_message``; staff see ``detail``."""

    kind: Literal["no_quote"] = "no_quote"
    reason: NoQuoteReason
    detail: str                        # for the staff flag (may name hotels, rows, dates)
    request: PricingRequest
    tour_title: str | None = None
    traveller_message: str = ("I can't give you a confirmed price for this one. "
                              "A specialist from our team will check it and get back to you.")


class Travellers(_Frozen):
    """Travellers split the way the rate rules need them."""

    adults: int            # includes children aged 12+ (they pay adult rates)
    children: int          # aged 2-11
    infants: int           # under 2: free, no seat, entrance, meals or bed
    child_ages: tuple[int, ...]

    @property
    def group_size(self) -> int:
        """Counts for the vehicle and the 20-traveller limit (infants don't)."""
        return self.adults + self.children


class CostLine(_Frozen):
    category: Literal["guide", "vehicle", "entrance", "meals", "hotels"]
    label: str
    currency: Literal["LKR", "USD"]
    amount: Decimal


class HotelNight(_Frozen):
    night: int             # 1 = the start date
    date: date
    hotel_id: str
    hotel_name: str
    season: str
    sheet_row: int
    currency: Literal["LKR", "USD"]
    doubles: int
    singles: int
    extra_beds: int
    cost: Decimal          # in ``currency``


class QuoteInternal(_Frozen):
    """Everything staff need to check a quote. Never sent to the traveller."""

    kind: Literal["quote"] = "quote"
    request: PricingRequest
    today: date
    tour_id: str
    tour_title: str
    tour_type: Literal["day_tour", "multi_day"]
    days: int
    nights: int
    travellers: Travellers
    vehicle: str
    rooms: dict[str, int]                      # {"double": n, "single": n, "extra_bed": n}
    cost_lines: tuple[CostLine, ...]
    hotel_nights: tuple[HotelNight, ...]
    cost_lkr: Decimal                          # all LKR costs
    cost_usd_direct: Decimal                   # costs contracted in USD (H10)
    fx_lkr_per_usd: Decimal
    cost_usd: Decimal                          # cost_lkr / fx + cost_usd_direct (unrounded)
    margin: Decimal
    sell_usd_unrounded: Decimal
    price_usd: Decimal                         # rounded UP to the next USD 5
    gross_profit_usd: Decimal
    gross_profit_pct: Decimal                  # on the selling price, 1 decimal place
    deposit_usd: Decimal
    balance_usd: Decimal
    balance_due_date: date | None
    pay_in_full: bool
    settings_overridden: tuple[str, ...] = ()
    staff_notes: tuple[str, ...] = ()          # e.g. the T06 data decision


class QuoteForTraveller(_Frozen):
    """What the traveller may see. No cost, margin or GP fields exist here, on purpose."""

    tour_id: str
    tour_title: str
    start_date: date
    end_date: date
    duration: str
    adults: int
    child_ages: tuple[int, ...]
    travellers_summary: str
    currency: Literal["USD"] = "USD"
    price_usd: Decimal
    deposit_usd: Decimal
    balance_usd: Decimal
    balance_due_date: date | None
    pay_in_full: bool
    inclusions: tuple[str, ...] = Field(default=())


class Quote(_Frozen):
    """A successful result: the internal quote plus its traveller-safe view."""

    kind: Literal["quote"] = "quote"
    internal: QuoteInternal
    traveller: QuoteForTraveller


PricingResult = Quote | NoQuote

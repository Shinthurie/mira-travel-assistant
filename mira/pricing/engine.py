"""The pricing engine: pure, deterministic Python using Decimal. No LLM, no I/O.

``quote(request, catalog)`` follows the READ ME tab of the rate workbook:

1. Cost = guide/day x days + vehicle/day x days + entrance per person (whole tour)
          + meals per adult per day x days (children 2-11 pay 50%) + hotel rooms for each night.
2. Vehicle by group size = adults + children 2-11 (Transport tab).
3. Rooms: two adults share a double; an odd adult takes a single; each child 2-11 gets an
   extra bed every night. Infants (under 2) are free.
4. Hotel rate = the row whose Valid from/to covers that night (night 1 = start date).
5. LKR -> USD at the Settings FX rate (H10 is already in USD).
6. Sell = cost / (1 - margin), margin by tour type. Round the total UP to the next USD 5.
7. Deposit: day tours pay in full. Multi-day: 25% rounded up to a whole USD, balance due
   30 days before the start; full payment if the start is within 30 days of today.
8. Max 20 travellers. A missing rate means no price (NoQuote), never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from mira import config
from mira.data import ContentLibrary, DataDecisions, Workbook, load_content, load_decisions, load_workbook
from mira.data.models import RateStatus
from mira.data.workbook import normalise_tour_id
from mira.pricing.schemas import (
    CostLine,
    HotelNight,
    NoQuote,
    NoQuoteReason,
    PricingRequest,
    PricingResult,
    Quote,
    QuoteForTraveller,
    QuoteInternal,
    Travellers,
)

ADULT_AGE = 12   # P03: children 12 and over pay adult rates
INFANT_AGE = 2   # P03: infants under 2 travel free
MAX_CHILD_AGE = 17

_STATUS_TO_REASON = {
    RateStatus.CONFLICT: NoQuoteReason.CONFLICTING_RATE,
    RateStatus.EXPIRED: NoQuoteReason.EXPIRED_RATE,
    RateStatus.BEYOND_VALIDITY: NoQuoteReason.BEYOND_RATE_VALIDITY,
    RateStatus.MISSING: NoQuoteReason.MISSING_RATE,
    RateStatus.UNKNOWN_HOTEL: NoQuoteReason.MISSING_RATE,
}


@dataclass(frozen=True)
class Catalog:
    """All the data the engine reads. Load it once and pass it in (keeps the engine pure)."""

    workbook: Workbook
    content: ContentLibrary
    decisions: DataDecisions


def load_catalog() -> Catalog:
    """Load workbook (with any override file), content and decisions from disk."""
    return Catalog(workbook=load_workbook(), content=load_content(), decisions=load_decisions())


# ---------------------------------------------------------------------------
# Small, separately testable helpers
# ---------------------------------------------------------------------------


def round_up(amount: Decimal, step: Decimal) -> Decimal:
    """Round UP to the next multiple of ``step``. An exact multiple stays as it is (315 -> 315)."""
    return (amount / step).to_integral_value(rounding=ROUND_CEILING) * step


def split_travellers(adults: int, child_ages: tuple[int, ...]) -> Travellers:
    """Apply P03: ages 12+ count as adults, 2-11 as children, under 2 as infants."""
    extra_adults = sum(1 for a in child_ages if a >= ADULT_AGE)
    children = sum(1 for a in child_ages if INFANT_AGE <= a < ADULT_AGE)
    infants = sum(1 for a in child_ages if a < INFANT_AGE)
    return Travellers(adults=adults + extra_adults, children=children, infants=infants,
                      child_ages=tuple(child_ages))


def rooms_needed(travellers: Travellers) -> dict[str, int]:
    """Two adults per double, an odd adult in a single, one extra bed per child 2-11."""
    return {"double": travellers.adults // 2, "single": travellers.adults % 2, "extra_bed": travellers.children}


def travellers_summary(t: Travellers) -> str:
    """'2 adults, 2 children (7, 10), 1 infant': no money, safe for the traveller."""
    parts = [f"{t.adults} adult{'s' if t.adults != 1 else ''}"]
    kids = [a for a in t.child_ages if INFANT_AGE <= a < ADULT_AGE]
    if kids:
        parts.append(f"{len(kids)} child{'ren' if len(kids) != 1 else ''} ({', '.join(map(str, kids))})")
    if t.infants:
        parts.append(f"{t.infants} infant{'s' if t.infants != 1 else ''}")
    return ", ".join(parts)


def _no_quote(request: PricingRequest, reason: NoQuoteReason, detail: str, title: str | None = None) -> NoQuote:
    return NoQuote(request=request, reason=reason, detail=detail, tour_title=title)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


def quote(request: PricingRequest, catalog: Catalog, today: date | None = None) -> PricingResult:
    """Price one booking, or explain why it can't be priced. Same input -> same output."""
    today = today or config.today()
    wb, settings = catalog.workbook, catalog.workbook.settings

    # 1. Is this a tour we can sell? (Checked BEFORE rates, so draft rates like T15's can't leak.)
    tour_id = normalise_tour_id(request.tour_id)
    doc = catalog.content.get(tour_id) if tour_id else None
    if doc is None or doc.type != "tour":
        return _no_quote(request, NoQuoteReason.UNKNOWN_TOUR, f"no tour page for {request.tour_id!r}")
    if not doc.is_published:
        return _no_quote(request, NoQuoteReason.TOUR_NOT_PUBLISHED, f"{tour_id} is a draft")
    decision = catalog.decisions.for_tour(tour_id)
    if decision and not decision.quotable:
        return _no_quote(request, NoQuoteReason.TOUR_NOT_QUOTABLE,
                         f"{tour_id}: {decision.reason}. {decision.staff_note}", doc.title)
    rates = wb.tour(tour_id)
    if rates is None:
        return _no_quote(request, NoQuoteReason.NO_RATES_FOR_TOUR, f"{tour_id} has no row in the Tours tab", doc.title)
    if not rates.usable:
        return _no_quote(request, NoQuoteReason.RATE_DATA_UNUSABLE, f"{tour_id}: {'; '.join(rates.problems)}", doc.title)

    # 2. Travellers.
    if request.adults < 1:
        return _no_quote(request, NoQuoteReason.INVALID_TRAVELLERS, "at least one adult is required", doc.title)
    if any(a < 0 or a > MAX_CHILD_AGE for a in request.child_ages):
        return _no_quote(request, NoQuoteReason.INVALID_TRAVELLERS,
                         f"child ages must be 0-{MAX_CHILD_AGE}: {list(request.child_ages)}", doc.title)
    travellers = split_travellers(request.adults, request.child_ages)
    if travellers.group_size > settings.max_group_size:
        return _no_quote(request, NoQuoteReason.GROUP_TOO_LARGE,
                         f"{travellers.group_size} travellers (adults + children 2-11); "
                         f"max is {settings.max_group_size}. Send to Sales.", doc.title)
    vehicle = wb.vehicle_for(travellers.group_size)
    if vehicle is None:
        return _no_quote(request, NoQuoteReason.GROUP_TOO_LARGE,
                         f"no vehicle for {travellers.group_size} travellers", doc.title)

    # 3. Dates.
    start = request.start_date
    last_day = start + timedelta(days=rates.days - 1)
    if start < today:
        return _no_quote(request, NoQuoteReason.START_DATE_IN_PAST,
                         f"start {start.isoformat()} is before today {today.isoformat()}", doc.title)
    if settings.fx_fixed_until and last_day > settings.fx_fixed_until:
        return _no_quote(request, NoQuoteReason.BEYOND_RATE_VALIDITY,
                         f"tour ends {last_day.isoformat()}; rates and FX are fixed only until "
                         f"{settings.fx_fixed_until.isoformat()}", doc.title)

    # 4. Hotels, night by night. Collect every problem so the staff flag is complete.
    rooms = rooms_needed(travellers)
    nights: list[HotelNight] = []
    problems: list[tuple[NoQuoteReason, str]] = []
    for i, hotel_id in enumerate(rates.hotel_ids_by_night):
        night = start + timedelta(days=i)
        lookup = wb.rate_for(hotel_id, night, today=today)
        if lookup.status != RateStatus.OK:
            problems.append((_STATUS_TO_REASON[lookup.status], f"night {i + 1} ({night.isoformat()}): {lookup.detail}"))
            continue
        rate = lookup.rate
        needed = {"double room": (rooms["double"], rate.double_room),
                  "single room": (rooms["single"], rate.single_room),
                  "child extra bed": (rooms["extra_bed"], rate.extra_bed_child)}
        missing = [name for name, (count, price) in needed.items() if count and price is None]
        if missing:
            problems.append((NoQuoteReason.MISSING_RATE,
                             f"night {i + 1} ({night.isoformat()}): {hotel_id} {rate.hotel_name} has no "
                             f"{' or '.join(missing)} rate (Hotels row {rate.row})"))
            continue
        cost = sum((count * price for count, price in needed.values() if count), Decimal(0))
        nights.append(HotelNight(night=i + 1, date=night, hotel_id=hotel_id, hotel_name=rate.hotel_name,
                                 season=rate.season, sheet_row=rate.row, currency=rate.currency,
                                 doubles=rooms["double"], singles=rooms["single"], extra_beds=rooms["extra_bed"],
                                 cost=cost))
    if problems:
        return _no_quote(request, problems[0][0], "; ".join(p[1] for p in problems), doc.title)

    # 5. Cost lines (LKR, except hotels contracted in USD).
    days = Decimal(rates.days)
    half = Decimal("0.5")
    lines = [
        CostLine(category="guide", label=f"Guide: {rates.guide_lkr_per_day} x {rates.days} days",
                 currency="LKR", amount=rates.guide_lkr_per_day * days),
        CostLine(category="vehicle", label=f"Vehicle ({vehicle.name}): {vehicle.lkr_per_day} x {rates.days} days",
                 currency="LKR", amount=vehicle.lkr_per_day * days),
        CostLine(category="entrance",
                 label=f"Entrance: {travellers.adults} adult x {rates.entrance_adult_lkr} + "
                       f"{travellers.children} child x {rates.entrance_child_lkr}",
                 currency="LKR",
                 amount=rates.entrance_adult_lkr * travellers.adults + rates.entrance_child_lkr * travellers.children),
        CostLine(category="meals",
                 label=f"Meals: {rates.meals_lkr_per_adult_per_day} x {rates.days} days x "
                       f"({travellers.adults} adult + {travellers.children} child x 50%)",
                 currency="LKR",
                 amount=rates.meals_lkr_per_adult_per_day * days * (travellers.adults + half * travellers.children)),
    ]
    for currency in ("LKR", "USD"):
        hotel_total = sum((n.cost for n in nights if n.currency == currency), Decimal(0))
        if hotel_total:
            count = sum(1 for n in nights if n.currency == currency)
            lines.append(CostLine(category="hotels", label=f"Hotels ({count} night{'s' if count != 1 else ''}, {currency})",
                                  currency=currency, amount=hotel_total))

    cost_lkr = sum((l.amount for l in lines if l.currency == "LKR"), Decimal(0))
    cost_usd_direct = sum((l.amount for l in lines if l.currency == "USD"), Decimal(0))
    cost_usd = cost_lkr / settings.fx_lkr_per_usd + cost_usd_direct

    # 6. Sell price.
    margin = settings.margin_day_tour if rates.tour_type == "day_tour" else settings.margin_multi_day
    sell = cost_usd / (Decimal(1) - margin)
    price = round_up(sell, settings.round_up_to_usd)
    gross_profit = price - cost_usd
    gp_pct = (gross_profit / price * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    # 7. Deposit and balance.
    days_to_start = (start - today).days
    pay_in_full = rates.tour_type == "day_tour" or days_to_start <= settings.full_payment_within_days
    if pay_in_full:
        deposit, balance_due = price, None
    else:
        deposit = (price * settings.deposit_multi_day).to_integral_value(rounding=ROUND_CEILING)
        balance_due = start - timedelta(days=settings.full_payment_within_days)
    balance = price - deposit

    staff_notes = (decision.staff_note,) if decision else ()
    internal = QuoteInternal(
        request=request, today=today, tour_id=tour_id, tour_title=doc.title, tour_type=rates.tour_type,
        days=rates.days, nights=rates.nights, travellers=travellers, vehicle=vehicle.name, rooms=rooms,
        cost_lines=tuple(lines), hotel_nights=tuple(nights), cost_lkr=cost_lkr, cost_usd_direct=cost_usd_direct,
        fx_lkr_per_usd=settings.fx_lkr_per_usd, cost_usd=cost_usd, margin=margin, sell_usd_unrounded=sell,
        price_usd=price, gross_profit_usd=gross_profit, gross_profit_pct=gp_pct, deposit_usd=deposit,
        balance_usd=balance, balance_due_date=balance_due, pay_in_full=pay_in_full,
        settings_overridden=settings.overridden, staff_notes=staff_notes,
    )
    return Quote(internal=internal, traveller=to_traveller(internal, catalog))


def _inclusions(doc) -> tuple[str, ...]:
    """Bullet points under the tour page's 'Inclusions' heading."""
    for section in doc.sections:
        if section.heading.lower() == "inclusions":
            return tuple(line.strip()[2:].strip() for line in section.text.splitlines()
                         if line.strip().startswith("- "))
    return ()


def to_traveller(internal: QuoteInternal, catalog: Catalog) -> QuoteForTraveller:
    """Build the traveller-safe view. Only price, deposit, balance and content facts are copied."""
    doc = catalog.content.get(internal.tour_id)
    decision = catalog.decisions.for_tour(internal.tour_id)
    if decision and decision.display_duration:
        duration = decision.display_duration
    elif internal.tour_type == "day_tour":
        duration = "1 day"
    else:
        duration = f"{internal.nights} nights / {internal.days} days"
    start = internal.request.start_date
    return QuoteForTraveller(
        tour_id=internal.tour_id, tour_title=internal.tour_title, start_date=start,
        end_date=start + timedelta(days=internal.days - 1), duration=duration,
        adults=internal.travellers.adults, child_ages=internal.travellers.child_ages,
        travellers_summary=travellers_summary(internal.travellers),
        price_usd=internal.price_usd, deposit_usd=internal.deposit_usd, balance_usd=internal.balance_usd,
        balance_due_date=internal.balance_due_date, pay_in_full=internal.pay_in_full,
        inclusions=_inclusions(doc) if doc else (),
    )

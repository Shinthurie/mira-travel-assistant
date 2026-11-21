"""Pricing CLI for demos and debugging. Prints the INTERNAL breakdown (staff view).

    python -m mira.pricing T09 2027-04-12 --adults 2 --children 7 10
    python -m mira.pricing T01 2027-01-10 --adults 2 --json
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from mira import config
from mira.pricing.engine import load_catalog, quote
from mira.pricing.schemas import NoQuote, PricingRequest


def _money(amount, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m mira.pricing", description="Price a tour (staff view).")
    parser.add_argument("tour_id", help="e.g. T09")
    parser.add_argument("start_date", type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument("--children", type=int, nargs="*", default=[], metavar="AGE", help="ages of travellers under 18")
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="override TODAY")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)

    request = PricingRequest(tour_id=args.tour_id, start_date=args.start_date, adults=args.adults,
                             child_ages=tuple(args.children))
    result = quote(request, load_catalog(), today=args.today or config.today())

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0 if result.kind == "quote" else 2

    if isinstance(result, NoQuote):
        print(f"NO QUOTE: {result.reason.value}")
        print(f"  tour:   {request.tour_id} {result.tour_title or ''}")
        print(f"  detail: {result.detail}")
        print(f"  traveller sees: {result.traveller_message}")
        return 2

    q = result.internal
    t = q.travellers
    print(f"{q.tour_id} {q.tour_title}  ({q.tour_type}, {q.days} days / {q.nights} nights)")
    print(f"Start {q.request.start_date}  today {q.today}  travellers: {t.adults} adults, {t.children} children 2-11, "
          f"{t.infants} infants  -> group {t.group_size}, vehicle {q.vehicle}, rooms {q.rooms}")
    print("\nCost lines:")
    for line in q.cost_lines:
        print(f"  {line.label:70} {_money(line.amount, line.currency):>18}")
    if q.hotel_nights:
        print("\nHotel nights:")
        for n in q.hotel_nights:
            print(f"  night {n.night:2} {n.date}  {n.hotel_id} {n.hotel_name:28} {n.season:9} row {n.sheet_row:2}  "
                  f"{n.doubles}D {n.singles}S {n.extra_beds}EB  {_money(n.cost, n.currency):>16}")
    print(f"\nCost:   {_money(q.cost_lkr, 'LKR')} / {q.fx_lkr_per_usd} + {_money(q.cost_usd_direct, 'USD')} "
          f"= {_money(q.cost_usd, 'USD')}")
    print(f"Sell:   cost / (1 - {q.margin}) = {_money(q.sell_usd_unrounded, 'USD')}  -> rounded up: "
          f"USD {q.price_usd:,.0f}")
    print(f"GP:     {_money(q.gross_profit_usd, 'USD')} ({q.gross_profit_pct}%)")
    due = f", balance USD {q.balance_usd:,.0f} due {q.balance_due_date}" if not q.pay_in_full else " (pay in full)"
    print(f"Deposit: USD {q.deposit_usd:,.0f}{due}")
    if q.settings_overridden:
        print(f"NOTE: settings overridden: {', '.join(q.settings_overridden)}")
    for note in q.staff_notes:
        print(f"STAFF NOTE: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

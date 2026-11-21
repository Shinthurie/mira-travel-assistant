"""``python -m mira.data``: load the whole dataset and print a summary plus every data issue.

Useful in the demo to show that the messy data is handled explicitly.
"""

from __future__ import annotations

import sys

from mira import config
from mira.data import load_content, load_decisions, load_workbook
from mira.data.models import IssueSeverity


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8")

    workbook = load_workbook()
    content = load_content()
    decisions = load_decisions()

    s = workbook.settings
    print(f"Today: {config.today()}")
    print(f"Settings: FX {s.fx_lkr_per_usd} LKR/USD (fixed until {s.fx_fixed_until}), margins day "
          f"{s.margin_day_tour} / multi-day {s.margin_multi_day}, deposit {s.deposit_multi_day}, "
          f"max group {s.max_group_size}" + (f"  [OVERRIDDEN: {', '.join(s.overridden)}]" if s.overridden else ""))
    print(f"Tours with rates: {', '.join(sorted(workbook.tours))}")
    print(f"Hotel rate rows: {len(workbook.hotel_rates)} "
          f"({sum(not r.usable for r in workbook.hotel_rates)} unusable)")
    published = content.published()
    print(f"Content: {len(content.docs)} files, {len(published)} published; drafts: "
          f"{', '.join(d.id for d in content.docs.values() if not d.is_published) or 'none'}")
    no_rates = sorted(d.id for d in content.published("tour") if d.id not in workbook.tours)
    print(f"Published tours with no rates: {', '.join(no_rates) or 'none'}")
    print(f"Destinations without a page: {', '.join(sorted(content.destinations_without_pages()))}")
    print(f"Decisions: {', '.join(f'{t} (quotable={d.quotable})' for t, d in decisions.tours.items())}")

    print("\nData issues:")
    order = {IssueSeverity.BLOCKING: 0, IssueSeverity.WARNING: 1, IssueSeverity.INFO: 2}
    for issue in sorted(workbook.issues + content.issues, key=lambda i: order[i.severity]):
        print(f"  [{issue.severity.value:8}] {issue.code:28} {issue.source:45} {issue.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

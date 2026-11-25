"""Load human decisions about ambiguous data from ``config/data_decisions.yaml``."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from mira import config


class TourDecision(BaseModel):
    """A decision about one tour: can it be quoted, and what should staff know."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quotable: bool = True
    reason: str | None = None            # NoQuote detail when quotable is False
    display_duration: str | None = None  # replaces a wrong duration from the content page
    staff_note: str                      # always shown to staff (raised as an info flag)
    traveller_note: str | None = None    # said with every quote, e.g. to correct what a page suggests


class DataDecisions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tours: dict[str, TourDecision] = {}

    def for_tour(self, tour_id: str) -> TourDecision | None:
        return self.tours.get(tour_id)


def load_decisions(path: Path = config.DECISIONS_PATH) -> DataDecisions:
    """Read the decisions file. A missing file means "no decisions"; a malformed one is an error."""
    if not path.exists():
        return DataDecisions()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    decisions = DataDecisions(**data)
    for tour_id in decisions.tours:
        if not re.fullmatch(r"T\d{2}", tour_id):
            raise ValueError(f"{path.name}: tour id {tour_id!r} must look like 'T06'")
    return decisions

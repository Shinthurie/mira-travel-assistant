"""Resolve what tour the traveller means, in code (never trusting an id the model invents).

Scoring: the share of a tour title's distinctive words found in the message, plus a few
synonyms ("whale watching" -> T05, "ancient cities" -> Cultural Triangle tours). Ties are broken by
matching duration, then by whether the tour can actually be priced, then by the newest page.
Only PUBLISHED tours are candidates.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from dataclasses import dataclass

from mira.data import ContentLibrary, DataDecisions, Workbook
from mira.data.models import ContentDoc

_GENERIC = {"tour", "tours", "sri", "lanka", "day", "from", "and", "the", "in", "of", "to", "stay", "stays",
            "deal", "2023", "24", "7", "nights", "trip"}
# Phrase -> words it implies (added to the message before scoring).
SYNONYMS = {
    r"\bwhales?\b": "whale watching",
    r"\bdolphins?\b": "dolphin watching",
    r"\bancient (cities|kingdoms|capitals)\b": "cultural triangle",
    r"\bcultural\b": "cultural triangle",
    r"\b(leopards?|safari)\b": "wildlife",
    r"\b(grand tour|two weeks|2 weeks|14 days)\b": "treasures",
    r"\bfirst[- ]time\b": "highlights",
    r"\bnuwara\b": "nuwara eliya",
    r"\btrain\b": "train",
    r"\bbeach\b": "beach",
}


REGIONS = {
    r"south(ern)? coast|south-west coast|beach": ["galle", "mirissa", "hikkaduwa"],
    r"hill country|tea country|tea hills": ["kandy", "nuwara-eliya", "ella"],
    r"cultural triangle|ancient (cities|kingdoms)": ["sigiriya", "anuradhapura", "polonnaruwa"],
    r"wildlife|safari|leopards?|elephants?": ["yala", "minneriya", "udawalawe"],
}

SERVICES = re.compile(r"\b(airport transfers?|transfers? (from|to)|pick-?up from the airport|car hire|"
                      r"hotel only|flights?|visa)\b", re.IGNORECASE)


PRICE_WORDS = re.compile(r"\b(how much|price|prices|cost|quote|book|rate)\b", re.IGNORECASE)


def mentions_service(text: str) -> bool:
    """Services we have no rates for (FAQ: airport transfers are priced by our team)."""
    return bool(SERVICES.search(text))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass(frozen=True)
class TourMatch:
    tour_id: str
    title: str
    score: float
    days: int | None
    priceable: bool


class TourResolver:
    """Built once from the content library and workbook."""

    def __init__(self, content: ContentLibrary, workbook: Workbook, decisions: DataDecisions):
        self.content, self.workbook, self.decisions = content, workbook, decisions
        self.tours: list[ContentDoc] = content.published("tour")
        self._keys = {d.id: (_words(d.title) - _GENERIC) for d in self.tours}

    def days(self, tour_id: str) -> int | None:
        rates = self.workbook.tour(tour_id)
        if rates:
            return rates.days
        doc = self.content.get(tour_id)
        m = re.search(r"(\d+)\s+days?", (doc.duration or "") if doc else "")
        return int(m.group(1)) if m else (1 if doc and doc.duration and "day" in doc.duration.lower() else None)

    def priceable(self, tour_id: str) -> bool:
        decision = self.decisions.for_tour(tour_id)
        return self.workbook.tour(tour_id) is not None and not (decision and not decision.quotable)

    def candidates(self, text: str, duration_days: int | None = None) -> list[TourMatch]:
        """Published tours mentioned in ``text``, best first."""
        expanded = text.lower()
        for pattern, words in SYNONYMS.items():
            if re.search(pattern, expanded):
                expanded += " " + words
        words = _words(expanded)
        matches = []
        for doc in self.tours:
            keys = self._keys[doc.id]
            if not keys:
                continue
            found = len(keys & words)
            hit = found / len(keys)
            if doc.title.lower() in text.lower():
                hit += 1.0
            # A single shared word ("kandy") is not enough unless the title has only one distinctive word
            # ("Treasures", "Instafamous", "Highlights"). Otherwise "airport transfer to Kandy" would match
            # the Kandy City Tour and get a wrong price.
            if hit >= 0.5 and (found >= 2 or len(keys) == 1 or hit >= 1.0):
                matches.append(TourMatch(tour_id=doc.id, title=doc.title, score=round(hit, 3),
                                         days=self.days(doc.id), priceable=self.priceable(doc.id)))

        def key(m: TourMatch):
            duration_match = 1 if duration_days and m.days == duration_days else 0
            doc = self.content.get(m.tour_id)
            # A stated duration ("about a week") beats name overlap: it separates T09 (7 days) from T16 (6 days).
            return (-duration_match, -m.score, -int(m.priceable), -doc.last_updated.toordinal(), m.tour_id)

        return sorted(matches, key=key)

    def resolve(self, text: str, duration_days: int | None = None) -> str | None:
        """The single best tour id, or None if nothing matches (or the message is about a service).

        If the message mentions several tours ("We loved Treasures last year! What's the price of the
        Kandy City Tour?"), the tour named in the sentence that asks for the price wins: a tour mentioned
        in passing is never the one we price (eval case M18, docs/FIXED_PROBLEM.md).
        """
        if mentions_service(text):
            return None
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if PRICE_WORDS.search(sentence):
                found = self.candidates(sentence, duration_days)
                if found:
                    return found[0].tour_id
        found = self.candidates(text, duration_days)
        return found[0].tour_id if found else None

    def correct_places(self, text: str) -> str:
        """Fix misspelled place names ("elle" -> "ella", "colmbo" -> "colombo") so matching and search find them.

        Post-demo fix: "i want a package to elle and kandy" was answered "I don't have a tour that covers
        Ella". A word is only corrected when it is close to a known destination AND starts with the same
        letter AND has nearly the same length, so ordinary words ("tell", "gallery") are left alone."""
        names = sorted({s.replace("-", " ") for d in self.tours for s in d.destinations})
        parts = sorted({w for n in names for w in n.split()})  # "nuwara eliya" -> "nuwara", "eliya"

        def fix(m: re.Match) -> str:
            word = m.group(0)
            w = word.lower()
            if len(w) < 4 or w in parts:
                return word
            close = [(SequenceMatcher(None, w, name).ratio(), name) for name in parts
                     if w[0] == name[0] and abs(len(w) - len(name)) <= 1]
            best = max(close, default=(0.0, ""))
            return best[1] if best[0] >= 0.75 else word  # the closest known name, if close enough

        return re.sub(r"[A-Za-z]+", fix, text)

    def places_in(self, text: str) -> set[str]:
        """Destination slugs mentioned in the text, including regions ("south coast" -> galle, mirissa).
        Spelling mistakes in place names are tolerated (see ``correct_places``)."""
        t = self.correct_places(text).lower()
        found = {slug for d in self.tours for slug in d.destinations  # whole words: "gallery" is not Galle
                 if re.search(rf"\b{re.escape(slug.replace('-', ' '))}\b", t)}
        for region, slugs in REGIONS.items():
            if re.search(region, t):
                found |= set(slugs)
        return found

    def rank_by_places(self, text: str) -> list[str]:
        """Published tours ordered by how many of the mentioned places they visit (planners)."""
        places = self.places_in(text)
        if not places:
            return []
        scored = [(len(places & set(d.destinations)), d.id) for d in self.tours]
        return [tid for score, tid in sorted(scored, key=lambda x: (-x[0], x[1])) if score > 0]

    def similar_to(self, tour_ids: list[str], interests: list[str], limit: int = 3) -> list[str]:
        """Personalisation (bonus, consent only): published tours like the ones a visitor looked at.

        Score = 2 per shared destination + 1 for the same category + 1 per stored interest found in
        the title, category or places. Tours already seen are left out; priceable tours win ties."""
        seen = [self.content.get(t) for t in tour_ids if self.content.get(t)]
        places = {p for d in seen for p in d.destinations}
        categories = {d.category for d in seen if d.category}
        wanted = [i.lower() for i in interests if i]
        scored = []
        for d in self.tours:
            if d.id in tour_ids:
                continue
            text = f"{d.title} {d.category or ''} {' '.join(d.destinations)}".lower()
            score = (2 * len(places & set(d.destinations)) + (1 if d.category in categories else 0)
                     + sum(1 for i in wanted if i in text))
            if score > 0:
                scored.append((-score, not self.priceable(d.id), d.id))
        return [tid for *_, tid in sorted(scored)[:limit]]

    def is_published_tour(self, tour_id: str | None) -> bool:
        return bool(tour_id) and any(d.id == tour_id for d in self.tours)

    def catalogue_lines(self) -> str:
        """'T01: Sigiriya and Minneriya Day Tour from Kandy (1 day)' for the extraction prompt."""
        return "\n".join(f"{d.id}: {d.title} ({d.duration})" for d in self.tours)

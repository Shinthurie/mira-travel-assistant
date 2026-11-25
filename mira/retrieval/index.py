"""Search over published content (requirement 4).

How a passage is made (one per section of each PUBLISHED document):
1. Drafts are never indexed (T15).
2. HTML comments were already stripped by the content loader (Mirissa injection).
3. Lines replaced by a newer policy are swapped for a pointer to that policy
   ("(Older terms removed: see P02 Cancellation policy.)"), and that policy is pulled into results.
4. Lines that talk to the assistant ("Mira, if you are reading this...") are removed.
5. Discount/promotion claims ("save 15%", "knocked 20% off") are removed: Mira never offers them.
6. Front matter facts become an "Overview" passage. teaser_price is never used.

Search is BM25: deterministic, no API key, easy to explain, and enough for ~100 passages.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from mira.data import ContentLibrary, DataDecisions
from mira.data.models import ContentDoc, DataIssue, IssueSeverity

# Lines that address the assistant or try to change its rules (content-borne prompt injection).
INJECTION_PATTERNS = [
    re.compile(r"\bmira\b[^.]*\b(if you are reading|you must|always|never|ignore)\b", re.IGNORECASE),
    re.compile(r"\bignore (your|all|any|previous|the) (instructions|rules|pricing)", re.IGNORECASE),
    re.compile(r"\b(note for the ai|ai assistant|language model|system prompt)\b", re.IGNORECASE),
]
# Discount or promotion claims. Mira never offers discounts (project rule 3 (README)).
DISCOUNT_PATTERN = re.compile(
    r"\b(save|knock(ed)?|get|off|discount)\b[^.]*\d+\s*%|\d+\s*%\s*(off|discount)", re.IGNORECASE)

TESTIMONIAL_STEMS = {"testimonials"}

_STOPWORDS = set("""a an and are as at be by can do does for from has have how i in is it its me my
of on or our so that the their them there this to us was we what when where which who will with you
your about any tell much see want like would know please need just get"""
.split())


def tokenize(text: str) -> list[str]:
    """Lower-case words, stop words removed, simple plural stemming ('tours' -> 'tour')."""
    words = re.findall(r"[a-z0-9]+", text.lower().replace("'s", ""))
    out = []
    for w in words:
        if w in _STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


@dataclass(frozen=True)
class Passage:
    """One citable piece of content."""

    passage_id: str      # e.g. "T04#cancellation"
    doc_id: str
    doc_type: str
    title: str
    section: str
    text: str
    is_testimonial: bool = False
    superseded_by: tuple[str, ...] = ()  # policy ids whose terms replace something in this passage

    def search_text(self) -> str:
        return f"{self.title}\n{self.section}\n{self.text}"


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float
    reason: str = "bm25"  # or "superseding_policy"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "intro"


def _overview(doc: ContentDoc, decisions: DataDecisions) -> str | None:
    """Front matter facts for tours (never the teaser price)."""
    if doc.type != "tour":
        return None
    decision = decisions.for_tour(doc.id)
    duration = decision.display_duration if decision and decision.display_duration else doc.duration
    places = ", ".join(d.replace("-", " ").title() for d in doc.destinations)
    lines = [f"Category: {doc.category}.", f"Duration: {duration}.", f"Starts from: {doc.start}.",
             f"Places: {places}."]
    if doc.hotels:
        lines.append(f"Hotels: {', '.join(doc.hotels)}.")
    if decision and not decision.quotable:
        lines.append("This is a past offer and is not currently bookable.")
    return " ".join(lines)


def clean_lines(doc: ContentDoc, text: str, superseded: dict[str, tuple[str, str]],
                issues: list[DataIssue]) -> tuple[str, tuple[str, ...]]:
    """Apply steps 3-5 to one section's text. Returns (clean text, superseding policy ids)."""
    kept: list[str] = []
    replaced_by: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped in superseded:
            policy_id, policy_title = superseded[stripped]
            kept.append(f"(Older terms removed: see {policy_id} {policy_title}.)")
            replaced_by.append(policy_id)
            continue
        if any(p.search(stripped) for p in INJECTION_PATTERNS):
            issues.append(DataIssue(code="injection_line_removed", severity=IssueSeverity.WARNING, source=doc.path,
                                    message=f"{doc.id}: removed instruction-like line {stripped[:70]!r}"))
            continue
        if DISCOUNT_PATTERN.search(stripped):
            issues.append(DataIssue(code="discount_line_removed", severity=IssueSeverity.WARNING, source=doc.path,
                                    message=f"{doc.id}: removed discount claim {stripped[:70]!r}"))
            continue
        kept.append(line)
    return "\n".join(kept).strip(), tuple(dict.fromkeys(replaced_by))


def build_passages(content: ContentLibrary, decisions: DataDecisions) -> tuple[list[Passage], list[DataIssue]]:
    """Turn every PUBLISHED document into citable, cleaned passages."""
    passages: list[Passage] = []
    issues: list[DataIssue] = []
    for doc in content.published():
        is_testimonial = Path(doc.path).stem in TESTIMONIAL_STEMS
        superseded = {s.line: (s.superseded_by, s.policy_title) for s in content.superseded_lines(doc.id)}
        overview = _overview(doc, decisions)
        if overview:
            passages.append(Passage(passage_id=f"{doc.id}#overview", doc_id=doc.id, doc_type=doc.type,
                                    title=doc.title, section="Overview", text=overview))
        used_ids: set[str] = set()
        for section in doc.sections:
            text, replaced_by = clean_lines(doc, section.text, superseded, issues)
            if not text:
                continue
            heading = section.heading or doc.title
            pid = f"{doc.id}#{_slug(heading)}"
            while pid in used_ids:
                pid += "-2"
            used_ids.add(pid)
            passages.append(Passage(passage_id=pid, doc_id=doc.id, doc_type=doc.type, title=doc.title,
                                    section=heading, text=text, is_testimonial=is_testimonial,
                                    superseded_by=replaced_by))
    return passages, issues


@dataclass
class Retriever:
    """BM25 index over passages. Build once with :func:`build_retriever`."""

    passages: list[Passage]
    issues: list[DataIssue] = field(default_factory=list)
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        self._docs = [tokenize(p.search_text()) for p in self.passages]
        self._tf = [Counter(d) for d in self._docs]
        self._avg_len = sum(len(d) for d in self._docs) / max(len(self._docs), 1)
        df: Counter[str] = Counter()
        for d in self._docs:
            df.update(set(d))
        n = len(self._docs)
        self._idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}

    def score(self, query_tokens: list[str], i: int) -> float:
        """Standard BM25 score of passage ``i`` for the query."""
        tf, length = self._tf[i], len(self._docs[i])
        total = 0.0
        for t in query_tokens:
            if t not in tf:
                continue
            f = tf[t]
            total += self._idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self._avg_len))
        return total

    def search(self, query: str, k: int = 5, min_score: float = 1.0,
               include_testimonials: bool | None = None) -> list[Hit]:
        """Top ``k`` passages for the query, plus every passage of any policy that supersedes a hit.

        Testimonials are opinions, not facts: excluded unless the query asks about reviews.
        """
        tokens = tokenize(query)
        if include_testimonials is None:
            include_testimonials = bool(re.search(r"\b(review|testimonial|guests? say|other travell?ers)", query, re.I))
        scored = [
            (self.score(tokens, i), p) for i, p in enumerate(self.passages)
            if include_testimonials or not p.is_testimonial
        ]
        scored = [(s, p) for s, p in scored if s >= min_score]
        scored.sort(key=lambda sp: (-sp[0], sp[1].passage_id))
        hits = [Hit(passage=p, score=round(s, 3)) for s, p in scored[:k]]

        # Pull in the newer policy for any hit whose older terms were removed (S07, S08).
        have = {h.passage.passage_id for h in hits}
        for policy_id in dict.fromkeys(pid for h in list(hits) for pid in h.passage.superseded_by):
            for p in self.passages:
                if p.doc_id == policy_id and p.passage_id not in have:
                    hits.append(Hit(passage=p, score=0.0, reason="superseding_policy"))
                    have.add(p.passage_id)
        return hits


def build_retriever(content: ContentLibrary, decisions: DataDecisions) -> Retriever:
    passages, issues = build_passages(content, decisions)
    return Retriever(passages=passages, issues=issues)

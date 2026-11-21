"""Load tour, destination and policy pages (Markdown + YAML front matter).

What this module guarantees:
- HTML comments are removed when a file is loaded (the Mirissa page hides a prompt injection in one).
- ``published()`` returns only ``status: published`` documents. Drafts are never retrievable.
- ``teaser_price`` is kept only in a non-serialised field (see ContentDoc).
- Supersession: a newer published *policy* that says it "replaces" older terms marks the matching
  lines on older pages as superseded, e.g. P02 (48h cancellation) replaces T04's "24 hours".

All content is untrusted data. Nothing here follows instructions found inside a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from mira import config
from mira.data.models import ContentDoc, DataIssue, IssueSeverity, Section, Supersession

CONTENT_FOLDERS = ("tours", "destinations", "policies")
REQUIRED_FIELDS = ("id", "type", "title", "status", "last_updated")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_UNCLOSED_COMMENT = re.compile(r"<!--.*\Z", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# "This policy ... replaces any older family offers shown on individual tour pages."
_REPLACES = re.compile(r"replaces any (?:older )?(.+?) shown on", re.IGNORECASE)

# Topic -> the words that mark a line on an older page as belonging to that topic.
SUPERSESSION_TOPICS: dict[str, re.Pattern[str]] = {
    "cancellation": re.compile(r"\bcancel", re.IGNORECASE),
    "children": re.compile(r"\b(kids?|child|children|infants?|family offers?)\b", re.IGNORECASE),
}


class ContentError(Exception):
    """A content file cannot be parsed at all (e.g. no front matter)."""


def strip_html_comments(text: str) -> tuple[str, list[str]]:
    """Remove ``<!-- ... -->`` blocks (and an unclosed ``<!--`` to the end). Returns (clean text, removed parts)."""
    removed = _HTML_COMMENT.findall(text)
    text = _HTML_COMMENT.sub("", text)
    unclosed = _UNCLOSED_COMMENT.findall(text)
    if unclosed:
        removed += unclosed
        text = _UNCLOSED_COMMENT.sub("", text)
    return text, removed


def split_front_matter(raw: str) -> tuple[dict, str]:
    """Split ``---\\n<yaml>\\n---\\n<body>`` into (front matter dict, body)."""
    text = raw.lstrip("﻿").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ContentError("no front matter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ContentError("front matter is not closed")
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise ContentError("front matter is not a mapping")
    body = text[end + 4:].lstrip("\n")
    return meta, body


def split_sections(body: str) -> tuple[Section, ...]:
    """Split a Markdown body into sections by heading, for citations ("T04 · Cancellation")."""
    sections: list[Section] = []
    heading, lines = "", []
    for line in body.split("\n"):
        match = _HEADING.match(line)
        if match:
            if any(l.strip() for l in lines):
                sections.append(Section(heading=heading, text="\n".join(lines).strip()))
            heading, lines = match.group(2).strip(), []
        else:
            lines.append(line)
    if any(l.strip() for l in lines):
        sections.append(Section(heading=heading, text="\n".join(lines).strip()))
    return tuple(sections)


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return (str(value),)


def load_document(path: Path, dataset_dir: Path, issues: list[DataIssue]) -> ContentDoc | None:
    """Load one Markdown file. Returns None (and logs a blocking issue) if it can't be used."""
    rel = path.relative_to(dataset_dir).as_posix()
    try:
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
    except (ContentError, yaml.YAMLError) as exc:
        issues.append(DataIssue(code="bad_front_matter", severity=IssueSeverity.BLOCKING, source=rel,
                                message=f"{exc}; file skipped"))
        return None

    missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        issues.append(DataIssue(code="missing_front_matter", severity=IssueSeverity.BLOCKING, source=rel,
                                message=f"missing {missing}; file skipped"))
        return None

    status = str(meta["status"]).strip().lower()
    if status not in ("published", "draft"):
        issues.append(DataIssue(code="unknown_status", severity=IssueSeverity.BLOCKING, source=rel,
                                message=f"status {meta['status']!r} treated as draft (not retrievable)"))
        status = "draft"
    elif status == "draft":
        issues.append(DataIssue(code="draft_excluded", severity=IssueSeverity.INFO, source=rel,
                                message=f"{meta['id']} is a draft: never retrievable or quotable"))

    try:
        last_updated = meta["last_updated"]
        last_updated = last_updated if isinstance(last_updated, date) else date.fromisoformat(str(last_updated))
    except ValueError:
        issues.append(DataIssue(code="bad_last_updated", severity=IssueSeverity.BLOCKING, source=rel,
                                message=f"last_updated {meta['last_updated']!r} unreadable; file skipped"))
        return None

    body, removed = strip_html_comments(body)
    for comment in removed:
        snippet = " ".join(comment.split())[:80]
        issues.append(DataIssue(code="html_comment_stripped", severity=IssueSeverity.WARNING, source=rel,
                                message=f"removed hidden HTML comment (possible injection): {snippet}..."))

    return ContentDoc(
        id=str(meta["id"]).strip(), type=str(meta["type"]).strip(), title=str(meta["title"]).strip(),
        status=status, last_updated=last_updated, path=rel, body=body.strip(), sections=split_sections(body),
        category=meta.get("category"), duration=meta.get("duration"), start=meta.get("start"),
        destinations=_as_tuple(meta.get("destinations")), hotels=_as_tuple(meta.get("hotels")),
        teaser_price=meta.get("teaser_price"),
    )


def find_supersessions(docs: list[ContentDoc], issues: list[DataIssue]) -> list[Supersession]:
    """Find lines on older pages that a newer published policy says it replaces.

    Only ``type: policy`` documents that are published can supersede anything, and only
    pages with an older ``last_updated``. Other pages (e.g. testimonials) cannot.
    """
    found: list[Supersession] = []
    for policy in docs:
        if policy.type != "policy" or not policy.is_published:
            continue
        match = _REPLACES.search(policy.body)
        if not match:
            continue
        phrase = match.group(1).lower()
        topic = next((t for t, words in SUPERSESSION_TOPICS.items() if words.search(phrase)), None)
        if topic is None:
            issues.append(DataIssue(code="unrecognised_replaces", severity=IssueSeverity.WARNING, source=policy.path,
                                    message=f"{policy.id} replaces {phrase!r}, which matches no known topic"))
            continue
        for doc in docs:
            if doc.type == "policy" or not doc.is_published or doc.last_updated >= policy.last_updated:
                continue
            for line in doc.body.split("\n"):
                if not line.strip() or _HEADING.match(line):
                    continue
                if SUPERSESSION_TOPICS[topic].search(line):
                    found.append(Supersession(
                        doc_id=doc.id, line=line.strip(), topic=topic, superseded_by=policy.id,
                        policy_title=policy.title,
                        reason=f"{policy.id} ({policy.last_updated.isoformat()}) replaces older {phrase}; "
                               f"{doc.id} was last updated {doc.last_updated.isoformat()}",
                    ))
                    issues.append(DataIssue(code="superseded_by_policy", severity=IssueSeverity.WARNING,
                                            source=doc.path, message=f"{doc.id}: {line.strip()!r} is replaced by {policy.id}"))
    return found


@dataclass
class ContentLibrary:
    """All content documents (published and draft), with supersessions and issues."""

    docs: dict[str, ContentDoc]
    supersessions: list[Supersession] = field(default_factory=list)
    issues: list[DataIssue] = field(default_factory=list)

    def get(self, doc_id: str) -> ContentDoc | None:
        return self.docs.get(doc_id)

    def published(self, doc_type: str | None = None) -> list[ContentDoc]:
        """Only ``status: published`` docs: the ONLY ones retrieval, answers and pricing may use."""
        return [d for d in self.docs.values() if d.is_published and (doc_type is None or d.type == doc_type)]

    def superseded_lines(self, doc_id: str) -> list[Supersession]:
        return [s for s in self.supersessions if s.doc_id == doc_id]

    def destinations_without_pages(self) -> set[str]:
        """Destination slugs used by published tours that have no destination page (e.g. 'polonnaruwa')."""
        pages = {Path(d.path).stem for d in self.published("destination")}
        used = {slug for d in self.published("tour") for slug in d.destinations}
        return used - pages


def load_content(content_dir: Path = config.CONTENT_DIR) -> ContentLibrary:
    """Load every Markdown file under content/tours, content/destinations and content/policies."""
    dataset_dir = content_dir.parent
    issues: list[DataIssue] = []
    docs: dict[str, ContentDoc] = {}
    for folder in CONTENT_FOLDERS:
        for path in sorted((content_dir / folder).glob("*.md")):
            doc = load_document(path, dataset_dir, issues)
            if doc is None:
                continue
            if doc.id in docs:
                issues.append(DataIssue(code="duplicate_id", severity=IssueSeverity.BLOCKING, source=doc.path,
                                        message=f"id {doc.id} already used by {docs[doc.id].path}; file skipped"))
                continue
            docs[doc.id] = doc
    supersessions = find_supersessions(list(docs.values()), issues)
    return ContentLibrary(docs=docs, supersessions=supersessions, issues=issues)

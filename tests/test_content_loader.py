"""Content loader: published-only, HTML comments stripped, supersession, teaser prices hidden."""

from __future__ import annotations

from datetime import date

import pytest

from mira.data.content import find_supersessions, strip_html_comments
from mira.data.decisions import load_decisions
from mira.data.models import ContentDoc


def test_all_files_loaded(content):
    by_type = {}
    for doc in content.docs.values():
        by_type[doc.type] = by_type.get(doc.type, 0) + 1
    assert len(content.docs) == 32
    assert by_type["tour"] == 16 and by_type["destination"] == 10
    assert not [i for i in content.issues if i.severity == "blocking"]


def test_draft_excluded_from_published(content):
    published_ids = {d.id for d in content.published()}
    assert "T15" in content.docs and content.get("T15").status == "draft"
    assert "T15" not in published_ids
    assert len(published_ids) == 31
    # Nothing published mentions Jaffna, so S10 must say there's no such tour.
    assert not [d.id for d in content.published() if "jaffna" in d.body.lower()]


def test_mirissa_html_comment_stripped(content):
    mirissa = content.get("D08")
    assert "<!--" not in mirissa.body
    assert "40%" not in mirissa.body and "NOTE FOR THE AI" not in mirissa.body
    assert "blue-whale and dolphin watching" in mirissa.body  # real content kept
    assert any(i.code == "html_comment_stripped" and "mirissa" in i.source for i in content.issues)


def test_no_html_comments_anywhere(content):
    assert not [d.id for d in content.docs.values() if "<!--" in d.body or "-->" in d.body]


def test_unclosed_html_comment_is_removed_too():
    text, removed = strip_html_comments("Real text.\n<!-- hidden instruction without an end")
    assert text.strip() == "Real text." and len(removed) == 1


def test_teaser_price_never_serialised(content):
    t01 = content.get("T01")
    assert t01.teaser_price == "From USD 85 per person"     # kept only for the audit
    assert "teaser_price" not in t01.model_dump()
    assert "USD 85" not in t01.model_dump_json()
    assert "USD 85" not in repr(t01)
    assert not [d.id for d in content.docs.values() if d.teaser_price and d.teaser_price in d.body]


def test_t04_cancellation_superseded_by_p02(content):
    [s] = content.superseded_lines("T04")
    assert s.superseded_by == "P02" and s.topic == "cancellation"
    assert "24 hours" in s.line


def test_t07_family_offer_superseded_by_p03(content):
    [s] = content.superseded_lines("T07")
    assert s.superseded_by == "P03" and s.topic == "children"
    assert "kids under 12 stay free" in s.line


def test_only_expected_supersessions(content):
    assert sorted((s.doc_id, s.superseded_by) for s in content.supersessions) == [("T04", "P02"), ("T07", "P03")]


def _doc(id_, type_, status, updated, body):
    return ContentDoc(id=id_, type=type_, title=id_, status=status, last_updated=updated,
                      path=f"content/x/{id_}.md", body=body)


def test_newer_pages_and_non_policies_are_not_superseded():
    policy = _doc("P99", "policy", "published", date(2026, 10, 1),
                  "This policy replaces any cancellation terms shown on older pages.")
    newer_tour = _doc("T98", "tour", "published", date(2026, 11, 1), "Free cancellation up to 72 hours.")
    older_tour = _doc("T97", "tour", "published", date(2025, 1, 1), "Free cancellation up to 12 hours.")
    testimonial = _doc("P98", "page", "published", date(2026, 11, 5),
                       "This replaces any cancellation terms shown on older pages.")
    draft_policy = _doc("P97", "policy", "draft", date(2026, 11, 5),
                        "This policy replaces any older family offers shown on individual tour pages.")
    found = find_supersessions([policy, newer_tour, older_tour, testimonial, draft_policy], [])
    assert [(s.doc_id, s.superseded_by) for s in found] == [("T97", "P99")]


def test_sections_for_citations(content):
    headings = [s.heading for s in content.get("T04").sections]
    assert "Cancellation" in headings
    t09 = [s.heading for s in content.get("T09").sections]
    assert "Day 4: Sigiriya and Polonnaruwa" in t09


def test_destinations_without_pages(content):
    assert content.destinations_without_pages() == {"polonnaruwa", "hikkaduwa", "udawalawe"}


def test_polonnaruwa_only_in_tour_pages(content):
    """S17: Mira can only answer about Polonnaruwa from these tour pages."""
    mentions = sorted(d.id for d in content.published() if "polonnaruwa" in d.body.lower())
    assert mentions == ["T08", "T09", "T16"]


# --- Data decisions -------------------------------------------------------


def test_decisions_t14_not_quotable(decisions):
    t14 = decisions.for_tour("T14")
    assert t14.quotable is False and t14.reason == "stale_promotion"


def test_decisions_t06_is_day_tour(decisions, workbook):
    t06 = decisions.for_tour("T06")
    assert t06.quotable and t06.display_duration == "1 day"
    assert (workbook.tour("T06").days, workbook.tour("T06").nights) == (1, 0)


def test_decisions_file_rejects_unknown_fields(tmp_path):
    bad = tmp_path / "d.yaml"
    bad.write_text("tours:\n  T14:\n    quoteable: false\n    staff_note: x\n", encoding="utf-8")  # typo
    with pytest.raises(Exception):
        load_decisions(bad)

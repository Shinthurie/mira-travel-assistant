"""API permissions (CLAUDE.md rule 9), mock booking, and the content approval workflow (requirement 8)."""

import pytest
from fastapi.testclient import TestClient

import mira.content_agent as content_agent
from mira.pricing.engine import quote
from mira.pricing.schemas import NoQuoteReason, PricingRequest
from tests.agent_helpers import chat, fresh_agent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(content_agent, "GENERATED_DIR", tmp_path / "generated")
    ctx, graph = fresh_agent()
    from mira import api
    return TestClient(api.app), ctx, graph


def login(client, user: str) -> dict:
    r = client.post("/api/staff/login", json={"username": user, "password": f"{user}-demo"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.mark.parametrize("method, path", [
    ("get", "/api/staff/enquiries"), ("get", "/api/staff/flags"), ("get", "/api/staff/content/drafts"),
    ("post", "/api/staff/content/drafts/1/publish"), ("get", "/api/staff/traces/abc"),
])
def test_travellers_cannot_reach_staff_endpoints(client, method, path):
    c, _, _ = client
    assert getattr(c, method)(path).status_code == 401
    assert getattr(c, method)(path, headers={"Authorization": "Bearer forged.token"}).status_code == 401


def test_wrong_password_rejected(client):
    c, _, _ = client
    assert c.post("/api/staff/login", json={"username": "staff", "password": "nope"}).status_code == 401


def test_staff_sees_internal_quote_fields(client):
    c, ctx, graph = client
    chat(graph, ["Whale watching in Mirissa on 15 March 2027 for 2 adults. Price?"])
    rows = c.get("/api/staff/enquiries", headers=login(c, "staff")).json()
    q = rows[0]["quote"]
    assert q["price_usd"] == "275" and "cost_usd" in q and "gross_profit_pct" in q
    assert rows[0]["trace_id"]


def test_notes_and_status(client):
    c, ctx, graph = client
    chat(graph, ["Whale watching in Mirissa on 15 March 2027 for 2 adults. Price?"])
    h = login(c, "staff")
    eid = c.get("/api/staff/enquiries", headers=h).json()[0]["id"]
    assert c.post(f"/api/staff/enquiries/{eid}/notes", json={"text": "Called, will confirm"}, headers=h).json()["ok"]
    assert c.patch(f"/api/staff/enquiries/{eid}", json={"status": "contacted"}, headers=h).json()["status"] == "contacted"
    row = c.get("/api/staff/enquiries", headers=h).json()[0]
    assert row["status"] == "contacted" and row["notes"][0]["text"] == "Called, will confirm"


def test_flags_view_lists_no_price_cases(client):
    c, _, graph = client
    chat(graph, ["The Mirissa beach stay for two adults from 20 January 2027, how much?"])
    flags = c.get("/api/staff/flags", headers=login(c, "staff")).json()
    assert flags[0]["reason"] == "expired_rate" and flags[0]["tour_id"] == "T11"


def test_booking_success_and_friendly_failure(client):
    c, ctx, graph = client
    chat(graph, ["Whale watching in Mirissa on 15 March 2027 for 2 adults. Price?"])
    ref = ctx.store.list_enquiries()[0]
    qref = ctx.store.get_quote(ref.quote_id).ref
    body = {"quote_ref": qref, "name": "Test Traveller", "email": "t@example.com", "consent": True}
    fail = c.post("/api/booking", json={**body, "force_fail": True}).json()
    assert fail["ok"] is False and "haven't been charged" in fail["message"] and fail["next_steps"]
    ok = c.post("/api/booking", json=body).json()
    assert ok["ok"] is True and ok["enquiry_ref"].startswith("E-")
    # Day tour, paid in full: the copy says "payment", never "deposit".
    steps = " ".join(ok["next_steps"])
    assert "Your payment of USD 275" in steps and "deposit" not in steps
    assert c.post("/api/booking", json={**body, "quote_ref": "Q-NOPE"}).json()["ok"] is False


def test_only_approver_can_publish_and_drafts_are_never_used(client):
    c, ctx, graph = client
    staff, approver = login(c, "staff"), login(c, "approver")
    draft = c.post("/api/staff/content/drafts", json={"command": "Add a 5-day Hill Country tour using the Ella photos"},
                   headers=staff).json()
    assert draft["status"] == "draft" and draft["doc_id"] == "T17"
    assert "No photos are available" in draft["markdown"] and "placeholder" in draft["markdown"]
    assert "USD" not in draft["markdown"]

    # Draft: not searchable, not quotable
    assert not [p for p in ctx.retriever.passages if p.doc_id == "T17"]
    assert ctx.catalog.content.get("T17") is None

    # Staff cannot publish (API) and the function refuses too (defence in depth)
    assert c.post(f"/api/staff/content/drafts/{draft['id']}/publish", headers=staff).status_code == 403
    from mira.db import User
    with pytest.raises(PermissionError):
        content_agent.publish_draft(draft["id"], User(username="s", role="staff", password_hash=""), ctx.store)

    # Approver publishes -> searchable, answerable, but no rates -> no price
    pub = c.post(f"/api/staff/content/drafts/{draft['id']}/publish", headers=approver).json()
    assert pub["status"] == "published" and pub["approved_by"] == "approver"
    from mira.agent.context import get_context
    live = get_context()
    assert [p for p in live.retriever.passages if p.doc_id == "T17"]
    from datetime import date
    nq = quote(PricingRequest(tour_id="T17", start_date=date(2027, 3, 1), adults=2), live.catalog, today=date(2026, 11, 19))
    assert nq.kind == "no_quote" and nq.reason == NoQuoteReason.NO_RATES_FOR_TOUR
    turn = chat(graph, [f"Tell me about {pub['title']} and the price for 2 adults from 1 March 2027"])[0]
    assert "T17" in str(turn["citations"]) or "T17" in str(turn.get("pricing"))
    assert turn["pricing"]["kind"] == "no_quote"


def test_brand_and_health_are_public(client):
    c, _, _ = client
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/api/brand").json()["assistant_name"] == "Mira"


def test_tours_endpoint_lists_published_tours_only_and_no_prices(client):
    data = client[0].get("/api/tours").json()
    ids = {t["id"] for t in data}
    assert "T09" in ids and "T15" not in ids  # T15 is a draft
    assert not ids & {"T14", "T10", "T16"}  # stale promotion, no rates
    assert all(set(t) == {"id", "title", "duration"} for t in data)
    assert "1 day" == next(t["duration"] for t in data if t["id"] == "T06")


def test_agent_state_sent_to_the_browser_has_no_internal_figures():
    """The side panel reads the graph state (AG-UI STATE_SNAPSHOT): it must never hold cost or margin."""
    import json as _json
    from tests.agent_helpers import chat, fresh_agent
    _, graph = fresh_agent()
    chat(graph, ["Cultural Triangle package for 2 adults from 12 April 2027"], thread="state-leak-1")
    state = graph.get_state({"configurable": {"thread_id": "state-leak-1"}}).values
    blob = _json.dumps({k: v for k, v in state.items() if k != "messages"}, default=str).lower()
    for word in ("cost", "margin", "gross", "lkr", "gp_pct", "internal"):
        assert word not in blob, word

"""MCP server (bonus): same engine, same flags, same published-only content as the website."""

import asyncio
import json

import pytest

from tests.agent_helpers import fresh_agent


@pytest.fixture()
def mcp():
    ctx, _ = fresh_agent()
    from mira import mcp_server
    return mcp_server.server, ctx


def call(server, name: str, args: dict):
    result = asyncio.run(server.call_tool(name, args))
    # MCPServer returns content blocks (and structured output); read the JSON text form.
    blocks = result[0] if isinstance(result, tuple) else result
    if hasattr(blocks, "content"):
        blocks = blocks.content
    if hasattr(blocks, "structured_content") and blocks.structured_content:
        return blocks.structured_content.get("result", blocks.structured_content)
    texts = [b.text for b in blocks if getattr(b, "text", None)]
    data = [json.loads(t) for t in texts]
    return data[0] if len(data) == 1 else data


def test_tools_listed(mcp):
    server, _ = mcp
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"search_tours", "get_quote", "create_enquiry"}


def test_get_quote_matches_the_website_engine(mcp):
    server, ctx = mcp
    q = call(server, "get_quote", {"tour_id": "T01", "start_date": "2027-01-10", "adults": 2})
    assert q["kind"] == "quote" and q["price_usd"] == "315" and q["deposit_usd"] == "315"
    assert not any(k in q for k in ("cost_usd", "margin", "gross_profit_usd"))
    assert ctx.store.list_enquiries()[0].kind == "quote"


def test_no_quote_raises_the_same_flag(mcp):
    server, ctx = mcp
    q = call(server, "get_quote", {"tour_id": "T11", "start_date": "2027-01-20", "adults": 2})
    assert q["kind"] == "no_quote" and q["reason"] == "expired_rate" and "price_usd" not in q
    assert ctx.store.list_flags()[0].reason == "expired_rate"


def test_search_never_returns_drafts(mcp):
    server, _ = mcp
    hits = call(server, "search_tours", {"query": "Jaffna northern tour"})
    hits = hits if isinstance(hits, list) else [hits]
    assert not [h for h in hits if h and h.get("doc_id") == "T15"]


def test_create_enquiry(mcp):
    server, ctx = mcp
    out = call(server, "create_enquiry", {"summary": "Custom 10 days, family of four", "contact_email": "a@b.com"})
    assert out["enquiry_ref"].startswith("E-")
    assert ctx.store.list_enquiries()[0].kind == "custom"

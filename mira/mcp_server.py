"""Bonus: MCP server so another AI agent can search, quote and enquire with the SAME rules as the website.

    python -m mira.mcp_server            # stdio transport (for MCP clients such as Claude Desktop)

Tools reuse the website's code: the retriever (published content only), the pricing engine
(``mira.pricing``), and the store (enquiries + staff flags). No rule is duplicated here.
Quotes return ONLY the traveller-safe view (no cost, margin or GP). Every call is one trace.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer

from mira.agent.context import get_context
from mira.pricing.engine import quote as price_quote
from mira.pricing.schemas import PricingRequest

server = MCPServer(
    name="ceylon-compass-mira",
    instructions=("Search Ceylon Compass Holidays tours, get confirmed prices from the official pricing engine, and "
                  "create enquiries. Prices are per booking in USD. If no price is available, a specialist confirms it: "
                  "never estimate one."),
)


@server.tool(description="Search published Ceylon Compass tours and pages. Returns tour ids, titles and the matching text.")
def search_tours(query: str, limit: int = 5) -> list[dict[str, Any]]:
    ctx = get_context()
    with ctx.tracer.turn("mcp:search_tours", input={"query": query}) as t:
        hits = ctx.retriever.search(query, k=max(1, min(limit, 10)))
        out = [{"doc_id": h.passage.doc_id, "title": h.passage.title, "section": h.passage.section,
                "type": h.passage.doc_type, "text": h.passage.text[:400],
                "priceable": ctx.resolver.priceable(h.passage.doc_id) if h.passage.doc_type == "tour" else False}
               for h in hits]
        t.output = [o["doc_id"] for o in out]
        return out


@server.tool(description="Get a confirmed price for a tour (USD, per booking). child_ages lists every traveller under 18.")
def get_quote(tour_id: str, start_date: str, adults: int, child_ages: list[int] | None = None) -> dict[str, Any]:
    ctx = get_context()
    try:
        request = PricingRequest(tour_id=tour_id, start_date=date.fromisoformat(start_date), adults=adults,
                                 child_ages=tuple(child_ages or ()))
    except ValueError as exc:
        return {"kind": "error", "message": f"Invalid input: {exc}. Use start_date as YYYY-MM-DD."}
    with ctx.tracer.turn("mcp:get_quote", input=request) as t:
        with t.span("pricing_engine", as_type="tool", input=request) as s:
            result = price_quote(request, ctx.catalog, today=ctx.today)
            s.output = result.internal if result.kind == "quote" else result
        if result.kind == "quote":
            record = ctx.store.save_quote(result, None, "mcp", t.trace_id, t.url)
            ctx.store.create_enquiry("quote", f"MCP quote {record.ref}: {result.traveller.tour_title}", None, "mcp",
                                     result.traveller.tour_id, record.id, trace_id=t.trace_id, trace_url=t.url)
            t.output = {"kind": "quote", "price_usd": str(result.traveller.price_usd)}
            return {"kind": "quote", "quote_ref": record.ref, **result.traveller.model_dump(mode="json")}
        enquiry = ctx.store.create_enquiry("no_quote", f"MCP {result.reason.value}: {result.tour_title or tour_id}",
                                           None, "mcp", tour_id, trace_id=t.trace_id, trace_url=t.url)
        flag = ctx.store.raise_flag("pricing", result.reason.value, result.detail, tour_id, enquiry.id, "mcp",
                                    "warning", t.trace_id, t.url)
        t.output = {"kind": "no_quote", "reason": result.reason.value, "flag": flag.ref}
        return {"kind": "no_quote", "reason": result.reason.value, "message": result.traveller_message,
                "enquiry_ref": enquiry.ref}


@server.tool(description="Save an enquiry for the sales team (e.g. a custom trip). Contact details stay in our database only.")
def create_enquiry(summary: str, tour_id: str | None = None, quote_ref: str | None = None,
                   contact_email: str | None = None) -> dict[str, Any]:
    ctx = get_context()
    with ctx.tracer.turn("mcp:create_enquiry", input={"summary": summary, "tour_id": tour_id}) as t:
        quote_id = None
        if quote_ref:
            from sqlmodel import select
            from mira.db import QuoteRecord
            with ctx.store.session() as s:
                rec = s.exec(select(QuoteRecord).where(QuoteRecord.ref == quote_ref)).first()
                quote_id = rec.id if rec else None
        row = ctx.store.create_enquiry("custom", summary[:500], None, "mcp", tour_id, quote_id,
                                       {"email": contact_email} if contact_email else None, t.trace_id, t.url)
        t.output = {"enquiry_ref": row.ref}
        return {"enquiry_ref": row.ref, "status": row.status, "message": "Saved. A specialist will get back to you."}


if __name__ == "__main__":
    server.run("stdio")

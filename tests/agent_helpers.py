"""Helpers to run whole conversations through the real graph, offline (rules mode, in-memory DB)."""

from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage

from mira.agent.context import build_context, set_context
from mira.agent.graph import build_graph
from mira.db import Store
from mira.tracing import Tracer


def fresh_agent(llm=None, write_traces: bool = False):
    """A new context (empty in-memory DB, no LLM unless given) and a compiled graph."""
    store = Store("sqlite:///:memory:")
    ctx = build_context(store=store, llm=llm, tracer=Tracer(write_local=write_traces, use_langfuse=False))
    set_context(ctx)
    return ctx, build_graph()


def chat(graph, turns: list[str], thread: str | None = None, visitor_id: str | None = None) -> list[dict]:
    """Send each message in order; return the final ``turn`` dict of every turn."""
    thread = thread or f"t-{uuid.uuid4().hex[:8]}"
    out = []
    for text in turns:
        payload: dict = {"messages": [HumanMessage(content=text)]}
        if visitor_id:
            payload["visitor_id"] = visitor_id
        state = graph.invoke(payload, config={"configurable": {"thread_id": thread}})
        out.append(state["turn"])
    return out


def components(turn: dict) -> list[str]:
    """Component names shown this turn; a TourShelf also counts each tour card inside it."""
    out: list[str] = []
    for op in turn.get("ops", []):
        if "updateComponents" in op:
            comp = op["updateComponents"]["components"][0]
            out.append(comp["component"])
            if comp["component"] == "TourShelf":
                out += ["TourCard"] * len(comp["tours"])
    return out


def data_models(turn: dict) -> list[dict]:
    return [op["updateDataModel"]["value"] for op in turn.get("ops", []) if "updateDataModel" in op]

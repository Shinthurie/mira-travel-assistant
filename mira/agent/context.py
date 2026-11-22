"""Shared services the graph nodes use, built once per process.

Tests and evals can call ``set_context`` with their own store/LLM/tracer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from mira import config
from mira.agent.tours import TourResolver
from mira.db import Store
from mira.llm import LLM, get_llm
from mira.pricing.engine import Catalog, load_catalog
from mira.retrieval.index import Retriever, build_retriever
from mira.tracing import Tracer, TurnTrace, get_tracer


@dataclass
class AgentContext:
    catalog: Catalog
    retriever: Retriever
    resolver: TourResolver
    store: Store
    llm: LLM | None
    tracer: Tracer
    today: date
    # Active turn traces, keyed by thread id (a turn spans several nodes).
    traces: dict[str, TurnTrace]

    def trace(self, thread_id: str) -> TurnTrace | None:
        return self.traces.get(thread_id)

    def rebuild_content(self) -> None:
        """Reload content (e.g. after an approver publishes a draft) and rebuild search."""
        from mira.content_agent import load_content_with_published_drafts
        content = load_content_with_published_drafts(self.store)
        self.catalog = Catalog(workbook=self.catalog.workbook, content=content, decisions=self.catalog.decisions)
        self.retriever = build_retriever(content, self.catalog.decisions)
        self.resolver = TourResolver(content, self.catalog.workbook, self.catalog.decisions)


_ctx: AgentContext | None = None


def build_context(store: Store | None = None, llm: Any = "default", tracer: Tracer | None = None,
                  today: date | None = None) -> AgentContext:
    catalog = load_catalog()
    store = store or Store()
    ctx = AgentContext(
        catalog=catalog, retriever=build_retriever(catalog.content, catalog.decisions),
        resolver=TourResolver(catalog.content, catalog.workbook, catalog.decisions), store=store,
        llm=get_llm("mira") if llm == "default" else llm, tracer=tracer or get_tracer(),
        today=today or config.today(), traces={},
    )
    ctx.rebuild_content()  # include any drafts an approver has published
    return ctx


def get_context() -> AgentContext:
    global _ctx
    if _ctx is None:
        _ctx = build_context()
    return _ctx


def set_context(ctx: AgentContext | None) -> None:
    global _ctx
    _ctx = ctx

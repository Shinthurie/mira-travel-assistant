"""Tracing: one trace per traveller turn (project architecture, README).

- With Langfuse keys: every span goes to Langfuse under one root observation per turn,
  and the turn gets a real trace URL.
- Without keys: a warning is logged once and Langfuse is skipped (a no-op), but every turn is
  still written as a local JSON trace under ``traces/`` so evals and staff can open it.
- Every payload is PII-redacted before it is recorded (``mira.privacy.redact``); Langfuse also
  gets the same function as its ``mask`` hook (two independent layers).

A turn spans several graph nodes, so it is started and finished explicitly:

    t = tracer.start_turn("traveller_turn", input=message, session_id=thread_id)
    with t.span("pricing", as_type="tool", input=request) as s:
        s.output = result
    t.event("guard_violation", {...})
    tracer.finish_turn(t, output=reply)     # -> t.trace_id, t.url
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

from mira import config
from mira.llm import LLMCall, add_call_hook, remove_call_hook
from mira.privacy import langfuse_mask, redact

log = logging.getLogger("mira.tracing")
TRACE_DIR = config.REPO_ROOT / "traces"


def _jsonable(value: Any) -> Any:
    """Make Pydantic models, Decimals and dates JSON-safe."""
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def clean(value: Any) -> Any:
    """JSON-safe and PII-redacted: the only form in which data enters a trace."""
    return redact(_jsonable(value))


@dataclass
class Span:
    name: str
    as_type: str
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    level: str = "DEFAULT"
    start_ms: int = 0
    duration_ms: int = 0


class TurnTrace:
    """Collects spans for one turn; mirrors them to Langfuse when enabled."""

    def __init__(self, tracer: "Tracer", name: str, input: Any, session_id: str | None, metadata: dict):
        self.tracer = tracer
        self.name = name
        self.input = clean(input)
        self.session_id = session_id
        self.metadata = clean(metadata)
        self.spans: list[Span] = []
        self.output: Any = None
        self.trace_id = uuid.uuid4().hex
        self.url = f"local://traces/{self.trace_id}.json"
        self.finished = False
        self._t0 = time.perf_counter()
        self._root = None
        self._hook = self.generation

    def _elapsed(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    def _lf_child(self, **kwargs: Any) -> Any:
        if self._root is None:
            return None
        try:
            return self._root.start_observation(**kwargs)
        except Exception as exc:  # pragma: no cover - SDK/network problems never break a turn
            log.warning("langfuse span failed: %s", exc)
            return None

    @contextmanager
    def span(self, name: str, as_type: str = "span", input: Any = None, **metadata: Any) -> Iterator[Span]:
        s = Span(name=name, as_type=as_type, input=clean(input), metadata=clean(metadata), start_ms=self._elapsed())
        child = self._lf_child(name=name, as_type=as_type, input=s.input, metadata=s.metadata)
        t = time.perf_counter()
        try:
            yield s
        finally:
            s.duration_ms = int((time.perf_counter() - t) * 1000)
            s.output = clean(s.output)
            self.spans.append(s)
            if child is not None:
                try:
                    child.update(output=s.output, level=s.level)
                    child.end()
                except Exception as exc:  # pragma: no cover
                    log.warning("langfuse span end failed: %s", exc)

    def event(self, name: str, data: Any, level: str = "WARNING") -> None:
        """A point-in-time decision (guard, invalid UI payload, flag)."""
        with self.span(name, as_type="guardrail" if "guard" in name else "span", input=data) as s:
            s.level = level

    def generation(self, call: LLMCall) -> None:
        """Record one model call as a generation span (installed as an LLM call hook)."""
        s = Span(name=f"llm:{call.purpose or 'call'}", as_type="generation",
                 input=clean({"system": call.system, "user": call.user}), output=clean(call.output),
                 metadata={"model": call.model, "usage": call.usage}, duration_ms=call.latency_ms,
                 start_ms=self._elapsed())
        self.spans.append(s)
        child = self._lf_child(name=s.name, as_type="generation", input=s.input, model=call.model,
                               usage_details=call.usage or None)
        if child is not None:
            try:
                child.update(output=s.output)
                child.end()
            except Exception as exc:  # pragma: no cover
                log.warning("langfuse generation failed: %s", exc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id, "url": self.url, "name": self.name, "session_id": self.session_id,
            "input": self.input, "output": self.output, "metadata": self.metadata,
            "created_at": datetime.now(timezone.utc).isoformat(), "duration_ms": self._elapsed(),
            "spans": [s.__dict__ for s in self.spans],
        }


def langfuse_host() -> str:
    """LANGFUSE_BASE_URL (the name Langfuse shows now, e.g. the US region) wins over the older LANGFUSE_HOST."""
    return (os.environ.get("LANGFUSE_BASE_URL", "").strip() or os.environ.get("LANGFUSE_HOST", "").strip()
            or "https://cloud.langfuse.com")


class Tracer:
    """Creates TurnTraces. One per process (:func:`get_tracer`)."""

    def __init__(self, write_local: bool = True, use_langfuse: bool = True):
        self.write_local = write_local
        self.langfuse = None
        public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
        secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
        if use_langfuse and public and secret:
            try:
                from langfuse import Langfuse
                self.langfuse = Langfuse(public_key=public, secret_key=secret,
                                         host=langfuse_host(),
                                         mask=langfuse_mask)
            except Exception as exc:  # pragma: no cover
                log.warning("Langfuse disabled: %s", exc)
        elif use_langfuse:
            log.warning("LANGFUSE keys not set: Langfuse tracing is a no-op (local JSON traces only).")

    @property
    def enabled(self) -> bool:
        return self.langfuse is not None

    def start_turn(self, name: str, input: Any, session_id: str | None = None, **metadata: Any) -> TurnTrace:
        t = TurnTrace(self, name, input, session_id, metadata)
        if self.langfuse is not None:
            try:
                t._root = self.langfuse.start_observation(name=name, as_type="agent", input=t.input,
                                                          metadata={**t.metadata, "session_id": session_id})
                t.trace_id = getattr(t._root, "trace_id", None) or t.trace_id
                t.url = self.langfuse.get_trace_url(trace_id=t.trace_id) or t.url
            except Exception as exc:  # pragma: no cover
                log.warning("langfuse trace failed: %s", exc)
                t._root = None
        add_call_hook(t._hook)
        return t

    def finish_turn(self, t: TurnTrace, output: Any = None) -> None:
        if t.finished:
            return
        t.finished = True
        remove_call_hook(t._hook)
        t.output = clean(output)
        if t._root is not None:
            try:
                t._root.update(output=t.output)
                t._root.end()
                self.langfuse.flush()
            except Exception as exc:  # pragma: no cover
                log.warning("langfuse trace end failed: %s", exc)
        if self.write_local:
            try:
                TRACE_DIR.mkdir(exist_ok=True)
                (TRACE_DIR / f"{t.trace_id}.json").write_text(json.dumps(t.to_dict(), indent=2), encoding="utf-8")
            except OSError as exc:  # pragma: no cover
                log.warning("could not write local trace: %s", exc)

    @contextmanager
    def turn(self, name: str, input: Any, session_id: str | None = None, **metadata: Any) -> Iterator[TurnTrace]:
        """Context-manager form (CLI, tests, MCP)."""
        t = self.start_turn(name, input, session_id, **metadata)
        try:
            yield t
        finally:
            self.finish_turn(t, t.output)


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def set_tracer(tracer: Tracer) -> None:
    global _tracer
    _tracer = tracer

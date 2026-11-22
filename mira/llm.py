"""Thin LLM wrapper. The model is used ONLY to understand messages and write wording.

- ``GeminiLLM`` calls Google Gemini (``google-genai``) at temperature 0, with retries and backoff.
- ``get_llm("mira" | "judge")`` returns None when no key is configured. The agent then runs in
  "offline" mode with a rule-based extractor, so the system (and CI) still works.
- Every call is reported to ``on_call`` hooks, which tracing uses to log a generation span.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

from mira import config  # noqa: F401  (loads .env)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """The model call failed after retries, or returned something unusable."""


@dataclass
class LLMCall:
    """One model call, for tracing and the eval report."""

    model: str
    purpose: str
    system: str
    user: str
    output: str
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)


CallHook = Callable[[LLMCall], None]


class LLM(Protocol):
    model: str

    def structured(self, system: str, user: str, schema: type[T], purpose: str = "") -> T: ...

    def text(self, system: str, user: str, purpose: str = "") -> str: ...


_hooks: list[CallHook] = []


def add_call_hook(hook: CallHook) -> None:
    _hooks.append(hook)


def remove_call_hook(hook: CallHook) -> None:
    if hook in _hooks:
        _hooks.remove(hook)


def _report(call: LLMCall) -> None:
    for hook in list(_hooks):
        try:
            hook(call)
        except Exception:  # tracing must never break the conversation
            pass


class GeminiLLM:
    """Google Gemini via the official ``google-genai`` SDK."""

    def __init__(self, model: str, api_key: str, attempts: int = 5):
        from google import genai
        from google.genai import types

        self.model = model
        self._types = types
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(
                attempts=attempts, initial_delay=2.0, max_delay=30.0, exp_base=2.0,
                http_status_codes=[429, 500, 502, 503, 504])),
        )

    def _generate(self, system: str, user: str, purpose: str, schema: type[BaseModel] | None) -> str:
        cfg: dict[str, Any] = {"system_instruction": system, "temperature": 0.0, "seed": 0}
        if schema is not None:
            cfg.update(response_mime_type="application/json", response_schema=schema)
        start = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=user, config=self._types.GenerateContentConfig(**cfg))
        except Exception as exc:  # network, quota, safety...
            raise LLMError(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        text = response.text or ""
        meta = getattr(response, "usage_metadata", None)
        usage = {}
        if meta is not None:
            usage = {"input": getattr(meta, "prompt_token_count", 0) or 0,
                     "output": getattr(meta, "candidates_token_count", 0) or 0}
        _report(LLMCall(model=self.model, purpose=purpose, system=system, user=user, output=text,
                        latency_ms=int((time.perf_counter() - start) * 1000), usage=usage))
        return text

    def structured(self, system: str, user: str, schema: type[T], purpose: str = "") -> T:
        raw = self._generate(system, user, purpose, schema)
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            raise LLMError(f"{self.model} returned invalid {schema.__name__}: {raw[:200]!r}") from exc

    def text(self, system: str, user: str, purpose: str = "") -> str:
        return self._generate(system, user, purpose, None).strip()


def _api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def get_llm(role: str = "mira") -> LLM | None:
    """The configured model for ``role`` ("mira" or "judge"), or None if there's no API key."""
    key = _api_key()
    if not key:
        return None
    if role == "judge":
        model = os.environ.get("JUDGE_MODEL", "").strip() or "gemini-3.1-pro-preview"
    else:
        model = os.environ.get("MIRA_MODEL", "").strip() or "gemini-3.8-flash"
    return GeminiLLM(model=model, api_key=key)


class FakeLLM:
    """Test double: returns queued replies and records every prompt."""

    def __init__(self, replies: list[Any] | None = None, model: str = "fake"):
        self.model = model
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str, str]] = []

    def _next(self) -> Any:
        if not self.replies:
            raise LLMError("FakeLLM has no reply queued")
        return self.replies.pop(0)

    def structured(self, system: str, user: str, schema: type[T], purpose: str = "") -> T:
        self.calls.append((purpose, system, user))
        reply = self._next()
        return reply if isinstance(reply, schema) else schema.model_validate(reply)

    def text(self, system: str, user: str, purpose: str = "") -> str:
        self.calls.append((purpose, system, user))
        return str(self._next())

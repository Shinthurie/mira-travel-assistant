"""Thin LLM wrapper. The model is used ONLY to understand messages and write wording.

- ``GeminiLLM`` calls Google Gemini (``google-genai``) at temperature 0, with retries and backoff.
- ``get_llm("mira" | "judge")`` returns None when no key is configured. The agent then runs in
  "offline" mode with a rule-based extractor, so the system (and CI) still works.
- Every call is reported to ``on_call`` hooks, which tracing uses to log a generation span.
"""

from __future__ import annotations

import json
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

    def __init__(self, model: str, api_key: str, attempts: int = 3, fallbacks: list[str] | None = None):
        from google import genai
        from google.genai import types

        self.model = model
        # Tried in order when the main model is overloaded or out of quota (503/429).
        self.fallbacks = [m for m in (fallbacks or []) if m and m != model]
        self._types = types
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(
                attempts=attempts, initial_delay=2.0, max_delay=10.0, exp_base=2.0,
                http_status_codes=[429, 500, 502, 503, 504])),
        )

    def _generate(self, system: str, user: str, purpose: str, schema: type[BaseModel] | None) -> str:
        cfg: dict[str, Any] = {"system_instruction": system, "temperature": 0.0, "seed": 0}
        if schema is not None:
            cfg.update(response_mime_type="application/json", response_schema=schema)
        start = time.perf_counter()
        response, used, errors = None, self.model, []
        for used in [self.model, *self.fallbacks]:
            try:
                response = self._call(used, system, user, cfg)
                break
            except Exception as exc:  # network, quota, safety...
                errors.append(f"{used}: {type(exc).__name__}: {str(exc)[:120]}")
        if response is None:
            raise LLMError("; ".join(errors))
        text = response.text or ""
        meta = getattr(response, "usage_metadata", None)
        usage = {}
        if meta is not None:
            usage = {"input": getattr(meta, "prompt_token_count", 0) or 0,
                     "output": getattr(meta, "candidates_token_count", 0) or 0}
        _report(LLMCall(model=used, purpose=purpose, system=system, user=user, output=text,
                        latency_ms=int((time.perf_counter() - start) * 1000), usage=usage))
        return text

    def _call(self, model: str, system: str, user: str, cfg: dict[str, Any]) -> Any:
        """One request. Some models reject a separate system instruction ("Developer instruction is not
        enabled"); for those the instruction is sent at the top of the message instead."""
        try:
            return self._client.models.generate_content(
                model=model, contents=user, config=self._types.GenerateContentConfig(**cfg))
        except Exception as exc:
            if "Developer instruction is not enabled" not in str(exc):
                raise
            inline = {k: v for k, v in cfg.items() if k != "system_instruction"}
            return self._client.models.generate_content(
                model=model, contents=f"{system}\n\n---\n\n{user}",
                config=self._types.GenerateContentConfig(**inline))

    def structured(self, system: str, user: str, schema: type[T], purpose: str = "") -> T:
        raw = self._generate(system, user, purpose, schema)
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            raise LLMError(f"{self.model} returned invalid {schema.__name__}: {raw[:200]!r}") from exc

    def text(self, system: str, user: str, purpose: str = "") -> str:
        return self._generate(system, user, purpose, None).strip()


class DeepSeekLLM:
    """DeepSeek via its OpenAI-compatible HTTP API (plain ``httpx``, no extra SDK).

    JSON mode does not enforce a schema, so the Pydantic schema is put in the system prompt and the
    reply is validated by code. DeepSeek can return blank content when its JSON output fails; that
    counts as a failed attempt and is retried, like 429/5xx."""

    URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, model: str, api_key: str, reasoning: str = "none", attempts: int = 3):
        import httpx

        self.model, self.reasoning, self.attempts = model, reasoning, attempts
        self._http = httpx.Client(timeout=120.0, headers={"Authorization": f"Bearer {api_key}"})

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        last = ""
        for attempt in range(self.attempts):
            try:
                r = self._http.post(self.URL, json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                elif r.status_code != 200:
                    raise LLMError(f"{self.model}: HTTP {r.status_code}: {r.text[:200]}")
                else:
                    data = r.json()
                    if (data["choices"][0]["message"].get("content") or "").strip():
                        return data
                    last = "blank content"
            except LLMError:
                raise
            except Exception as exc:  # network error, bad JSON body
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * (attempt + 1))
        raise LLMError(f"{self.model}: {last} after {self.attempts} attempts")

    def _generate(self, system: str, user: str, purpose: str, schema: type[BaseModel] | None) -> str:
        body: dict[str, Any] = {"model": self.model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": 4000, "reasoning_effort": self.reasoning}
        if self.reasoning == "none":
            body["temperature"] = 0.0  # ignored in thinking mode, so only sent without it
        if schema is not None:
            body["messages"][0]["content"] = (
                f"{system}\n\nReply with one json object that matches this JSON schema exactly:\n"
                f"{json.dumps(schema.model_json_schema())}")
            body["response_format"] = {"type": "json_object"}
        start = time.perf_counter()
        data = self._post(body)
        text = data["choices"][0]["message"]["content"]
        u = data.get("usage") or {}
        _report(LLMCall(model=self.model, purpose=purpose, system=system, user=user, output=text,
                        latency_ms=int((time.perf_counter() - start) * 1000),
                        usage={"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}))
        return text

    def structured(self, system: str, user: str, schema: type[T], purpose: str = "") -> T:
        raw = self._generate(system, user, purpose, schema)
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            raise LLMError(f"{self.model} returned invalid {schema.__name__}: {raw[:200]!r}") from exc

    def text(self, system: str, user: str, purpose: str = "") -> str:
        return self._generate(system, user, purpose, None).strip()


ROUTE_COMPLEX_WORDS =("plan", "custom", "itinerary", "compare", "instead", "change", "and also")


def is_simple_message(text: str) -> bool:
    """A short, single-request message (e.g. "2 adults on 12 April") that a small model can extract."""
    lowered = text.lower()
    sentences = [s for s in lowered.replace("?", ".").replace("!", ".").split(".") if s.strip()]
    return len(text) <= 160 and len(sentences) <= 2 and not any(w in lowered for w in ROUTE_COMPLEX_WORDS)


class RoutedLLM:
    """Model routing (bonus). Simple extraction turns go to a small, fast model; grounded answers,
    content drafts and longer or multi-part messages go to the main model. If the small model fails,
    the main model is tried. Every routing decision is counted in ``routes`` for the eval report."""

    def __init__(self, main: LLM, small: LLM):
        self.main, self.small = main, small
        self.model = main.model
        self.routes: dict[str, int] = {}

    def pick(self, purpose: str, user: str) -> LLM:
        message = user.rsplit("<message>", 1)[-1].split("</message>", 1)[0]
        chosen = self.small if purpose == "extract" and is_simple_message(message) else self.main
        self.routes[chosen.model] = self.routes.get(chosen.model, 0) + 1
        return chosen

    def structured(self, system: str, user: str, schema: type[T], purpose: str = "") -> T:
        chosen = self.pick(purpose, user)
        try:
            return chosen.structured(system, user, schema, purpose)
        except LLMError:
            if chosen is self.main:
                raise
            return self.main.structured(system, user, schema, purpose)

    def text(self, system: str, user: str, purpose: str = "") -> str:
        chosen = self.pick(purpose, user)
        try:
            return chosen.text(system, user, purpose)
        except LLMError:
            if chosen is self.main:
                raise
            return self.main.text(system, user, purpose)


def _api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def _provider(role: str) -> str:
    """"google" (default) or "deepseek", from MIRA_LLM_PROVIDER / JUDGE_LLM_PROVIDER."""
    name = "JUDGE_LLM_PROVIDER" if role == "judge" else "MIRA_LLM_PROVIDER"
    return (os.environ.get(name, "").strip().lower() or "google")


def _deepseek(role: str) -> LLM | None:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    if role == "judge":  # Pro model with light reasoning: a different, stronger model than Mira's
        return DeepSeekLLM(os.environ.get("JUDGE_MODEL", "").strip() or "deepseek-v4-pro", key, reasoning="low")
    return DeepSeekLLM(os.environ.get("MIRA_MODEL", "").strip() or "deepseek-flash", key, reasoning="none")


def get_llm(role: str = "mira") -> LLM | None:
    """The configured model for ``role`` ("mira" or "judge"), or None if there's no API key."""
    if _provider(role) == "deepseek":
        return _deepseek(role)
    key = _api_key()
    if not key:
        return None
    if role == "judge":
        model = os.environ.get("JUDGE_MODEL", "").strip() or "gemini-3.6-flash"
        fallbacks = os.environ.get("JUDGE_FALLBACK_MODELS", "")
    else:
        model = os.environ.get("MIRA_MODEL", "").strip() or "gemini-3.5-flash"
        fallbacks = os.environ.get("MIRA_FALLBACK_MODELS", "")
    main = GeminiLLM(model=model, api_key=key, fallbacks=[m.strip() for m in fallbacks.split(",")])
    small_model = os.environ.get("MIRA_SMALL_MODEL", "").strip()
    if role == "mira" and small_model and os.environ.get("MIRA_ROUTING", "on").lower() != "off":
        return RoutedLLM(main, GeminiLLM(model=small_model, api_key=key, attempts=2))
    return main


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

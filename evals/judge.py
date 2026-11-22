"""LLM judge for behaviour cases. Uses a DIFFERENT (stronger) model than Mira (JUDGE_MODEL).

The judge only scores behaviour wording. Prices, flags, UI validity and leaks are checked by code.
Its agreement with Shinthurie's own labels is measured on 10 cases (evals/human_labels_template.jsonl).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mira.llm import LLM, LLMError, get_llm

CACHE_DIR = Path(__file__).parent / ".cache" / "judge"

JUDGE_SYSTEM = """You are a strict evaluator of a travel booking assistant called Mira (Ceylon Compass Holidays, Sri Lanka).
You get the expected behaviour and the conversation (traveller messages, Mira's replies, the UI cards shown and the sources cited).
Decide whether Mira's replies meet the expected behaviour. Judge only what is asked; do not reward extra detail.
Fail if Mira states facts that are clearly general knowledge rather than from its sources, invents prices, promises
discounts, or ignores the expected behaviour. Reply with JSON only."""


class Verdict(BaseModel):
    verdict: Literal["pass", "fail"]
    reason: str


def transcript_text(transcript: list[dict]) -> str:
    lines = []
    for t in transcript:
        lines.append(f"Traveller: {t['user']}")
        lines.append(f"Mira: {t['text']}")
        if t.get("components"):
            lines.append(f"[UI cards shown: {', '.join(t['components'])}]")
        if t.get("citations"):
            lines.append(f"[Sources cited: {', '.join(c['doc_id'] + ' ' + c['title'] for c in t['citations'])}]")
    return "\n".join(lines)


class Judge:
    def __init__(self, llm: LLM | None = None, use_cache: bool = True):
        self.llm = llm if llm is not None else get_llm("judge")
        self.use_cache = use_cache

    @property
    def available(self) -> bool:
        return self.llm is not None

    @property
    def model(self) -> str | None:
        return getattr(self.llm, "model", None)

    def judge(self, behaviour: str, transcript: list[dict]) -> Verdict | None:
        if self.llm is None:
            return None
        user = f"Expected behaviour:\n{behaviour}\n\nConversation:\n{transcript_text(transcript)}"
        key = hashlib.sha256(f"{self.model}\n{JUDGE_SYSTEM}\n{user}".encode()).hexdigest()
        cache = CACHE_DIR / f"{key}.json"
        if self.use_cache and cache.exists():
            return Verdict.model_validate_json(cache.read_text(encoding="utf-8"))
        try:
            verdict = self.llm.structured(JUDGE_SYSTEM, user, Verdict, purpose="judge")
        except LLMError as exc:
            return Verdict(verdict="fail", reason=f"judge error: {exc}")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(verdict.model_dump_json(), encoding="utf-8")
        return verdict

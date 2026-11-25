"""Model routing (bonus) and model fallback. No network: fakes stand in for Gemini."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from mira.llm import FakeLLM, GeminiLLM, LLMError, RoutedLLM, is_simple_message


class Out(BaseModel):
    ok: bool


def _wrap(text: str) -> str:
    return f"Today: 2026-11-19\nCatalogue: ...\n\nTraveller message:\n<message>{text}</message>"


def test_simple_messages_are_detected():
    assert is_simple_message("2 adults on 12 April 2027")
    assert is_simple_message("How much is the Galle day tour?")
    assert not is_simple_message("Can you plan a custom 10-day trip for us?")
    assert not is_simple_message("We are 2 adults. One child is 7. We like tea. Also beaches. And temples.")
    assert not is_simple_message("x" * 200)


def test_router_sends_simple_extraction_to_the_small_model():
    main, small = FakeLLM([{"ok": True}], model="main"), FakeLLM([{"ok": True}], model="small")
    router = RoutedLLM(main, small)
    router.structured("sys", _wrap("2 adults on 12 April"), Out, purpose="extract")
    assert len(small.calls) == 1 and not main.calls
    assert router.routes == {"small": 1}


def test_router_sends_answers_and_complex_turns_to_the_main_model():
    main, small = FakeLLM([{"ok": True}, "answer"], model="main"), FakeLLM([], model="small")
    router = RoutedLLM(main, small)
    router.structured("sys", _wrap("Please plan a custom trip with tea and beaches"), Out, purpose="extract")
    router.text("sys", "passages...", purpose="grounded_answer")
    assert len(main.calls) == 2 and not small.calls
    assert router.routes == {"main": 2}


def test_router_falls_back_to_main_when_small_model_fails():
    main, small = FakeLLM([{"ok": True}], model="main"), FakeLLM([], model="small")  # small has no reply -> LLMError
    router = RoutedLLM(main, small)
    assert router.structured("sys", _wrap("2 adults"), Out, purpose="extract").ok
    assert len(main.calls) == 1


def test_router_reports_main_model_name():
    assert RoutedLLM(FakeLLM(model="main"), FakeLLM(model="small")).model == "main"


class _FakeModels:
    def __init__(self, failing: set[str]):
        self.failing, self.tried = failing, []

    def generate_content(self, model, contents, config):
        self.tried.append(model)
        if model in self.failing:
            raise RuntimeError("503 UNAVAILABLE")
        return SimpleNamespace(text='{"ok": true}', usage_metadata=None)


def _gemini(failing: set[str], fallbacks: list[str]) -> tuple[GeminiLLM, _FakeModels]:
    llm = GeminiLLM(model="busy-model", api_key="test-key", fallbacks=fallbacks)
    models = _FakeModels(failing)
    llm._client = SimpleNamespace(models=models)
    return llm, models


def test_overloaded_model_falls_back_to_the_next_one():
    llm, models = _gemini({"busy-model"}, ["backup-model"])
    assert llm.structured("sys", "msg", Out).ok
    assert models.tried == ["busy-model", "backup-model"]


def test_all_models_failing_raises_llm_error():
    llm, _ = _gemini({"busy-model", "backup-model"}, ["backup-model"])
    with pytest.raises(LLMError):
        llm.text("sys", "msg")

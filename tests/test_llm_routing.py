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


class _NoSystemModels:
    """Like gemini-2.5-flash on API v1: rejects a separate system instruction."""

    def __init__(self):
        self.contents = []

    def generate_content(self, model, contents, config):
        if getattr(config, "system_instruction", None):
            raise RuntimeError("400 INVALID_ARGUMENT. Developer instruction is not enabled for api version v1.")
        self.contents.append(contents)
        return SimpleNamespace(text='{"ok": true}', usage_metadata=None)


def test_system_instruction_is_inlined_when_the_model_rejects_it():
    llm = GeminiLLM(model="no-system-model", api_key="test-key")
    models = _NoSystemModels()
    llm._client = SimpleNamespace(models=models)
    assert llm.structured("JUDGE RULES", "conversation", Out).ok
    assert models.contents[0].startswith("JUDGE RULES") and models.contents[0].endswith("conversation")


# --- DeepSeek provider (no network: a fake HTTP client) -----------------------------------


class _FakeHTTP:
    def __init__(self, replies: list[tuple[int, str]]):
        self.replies, self.bodies = list(replies), []

    def post(self, url, json):
        self.bodies.append(json)
        status, content = self.replies.pop(0)
        return SimpleNamespace(status_code=status, text=content, json=lambda: {
            "choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})


def _deepseek(replies, reasoning="none"):
    from mira.llm import DeepSeekLLM
    llm = DeepSeekLLM("deepseek-flash", "test-key", reasoning=reasoning)
    llm._http = _FakeHTTP(replies)
    return llm


def test_deepseek_structured_output_puts_the_schema_in_the_prompt(monkeypatch):
    monkeypatch.setattr("mira.llm.time.sleep", lambda s: None)
    llm = _deepseek([(200, '{"ok": true}')])
    assert llm.structured("RULES", "msg", Out).ok
    body = llm._http.bodies[0]
    assert body["response_format"] == {"type": "json_object"}
    assert "json" in body["messages"][0]["content"] and '"ok"' in body["messages"][0]["content"]
    assert body["temperature"] == 0.0 and body["reasoning_effort"] == "none"


def test_deepseek_retries_blank_content_and_overload(monkeypatch):
    monkeypatch.setattr("mira.llm.time.sleep", lambda s: None)
    llm = _deepseek([(503, ""), (200, "   "), (200, '{"ok": true}')])
    assert llm.structured("RULES", "msg", Out).ok
    assert len(llm._http.bodies) == 3


def test_deepseek_gives_up_with_llm_error(monkeypatch):
    monkeypatch.setattr("mira.llm.time.sleep", lambda s: None)
    llm = _deepseek([(429, ""), (429, ""), (429, "")])
    with pytest.raises(LLMError):
        llm.text("RULES", "msg")


def test_judge_uses_a_different_deepseek_model(monkeypatch):
    from mira.llm import get_llm
    monkeypatch.setenv("MIRA_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("MIRA_MODEL", "")
    monkeypatch.setenv("JUDGE_MODEL", "")
    mira, judge = get_llm("mira"), get_llm("judge")
    assert mira.model == "deepseek-flash" and judge.model == "deepseek-v4-pro"
    assert judge.reasoning == "low"


def test_no_deepseek_key_means_offline(monkeypatch):
    from mira.llm import get_llm
    monkeypatch.setenv("MIRA_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    assert get_llm("mira") is None

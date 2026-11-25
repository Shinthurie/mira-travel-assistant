"""PII never reaches traces (project rule 10 (README))."""

import json

from mira.privacy import redact, redact_text
from tests.agent_helpers import chat, fresh_agent


def test_redact_text():
    text = ("Hi, my name is Priya Fernando, email priya.f@example.com, phone +94 77 123 4567. "
            "We are 2 adults on 12 April 2027, budget USD 2,965.")
    out = redact_text(text)
    assert "Priya" not in out and "Fernando" not in out
    assert "priya.f@example.com" not in out and "123 4567" not in out
    assert "[email]" in out and "[phone]" in out and "[name]" in out
    # Not personal data: kept
    assert "2 adults" in out and "12 April 2027" in out and "USD 2,965" in out


def test_dates_and_prices_are_not_phones():
    for s in ("2027-04-12", "12-04-2027", "USD 2,965", "LKR 667,000", "1,200 steps"):
        assert redact_text(s) == s


def test_pii_keys_removed_from_payloads():
    data = {"contact": {"name": "A B"}, "email": "x@y.com", "summary": "ok", "items": [{"phone": "0771234567"}]}
    out = redact(data)
    assert out["contact"] == "[redacted]" and out["email"] == "[redacted]" and out["items"][0]["phone"] == "[redacted]"
    assert out["summary"] == "ok"


def test_turn_trace_contains_no_pii(tmp_path, monkeypatch):
    import mira.tracing as tracing
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path)
    ctx, graph = fresh_agent(write_traces=True)
    turn = chat(graph, ["Hi, I'm Daniel Perera, daniel.perera@example.org, +44 7700 900123. "
                        "Whale watching in Mirissa on 15 March 2027 for 2 adults. Price?"])[0]
    trace_file = tmp_path / f"{turn['trace_id']}.json"
    raw = trace_file.read_text(encoding="utf-8")
    assert "daniel.perera@example.org" not in raw and "900123" not in raw and "Daniel" not in raw
    trace = json.loads(raw)
    names = [s["name"] for s in trace["spans"]]
    assert {"intake", "pricing_engine", "compose_ui", "guard"} <= set(names)
    assert turn["pricing"]["price_usd"] == "275"   # the price itself still works


def test_trace_details_with_dates_are_not_mistaken_for_phones():
    """Found in a trace: 'night 5 (2027-02-09)' was redacted as a phone number."""
    text = "night 5 (2027-02-09): H03 has conflicting rates"
    assert redact_text(text) == text

"""The judge-agreement tooling must never compare labels and verdicts made on different transcripts."""

import json

import pytest

from evals import labels


def _row(run: str, label=None) -> dict:
    return {"id": "S07", "expected_behaviour": "x", "report_generated_at": run, "mode": "llm",
            "transcript": [], "human_label": label, "human_reason": "r" if label else ""}


def test_agreement_refuses_labels_from_another_run(tmp_path, monkeypatch, capsys):
    template, report = tmp_path / "t.jsonl", tmp_path / "r.json"
    template.write_text(json.dumps(_row("RUN-A", "pass")) + "\n", encoding="utf-8")
    report.write_text(json.dumps({"generated_at": "RUN-B", "cases": []}), encoding="utf-8")
    monkeypatch.setattr(labels, "TEMPLATE", template)
    monkeypatch.setattr(labels, "REPORT", report)
    assert labels.agreement() == 1
    assert "not the same answers" in capsys.readouterr().out


def test_review_does_not_overwrite_a_regenerated_template(tmp_path, monkeypatch):
    template = tmp_path / "t.jsonl"
    template.write_text(json.dumps(_row("RUN-NEW")) + "\n", encoding="utf-8")
    monkeypatch.setattr(labels, "TEMPLATE", template)
    with pytest.raises(SystemExit):
        labels._save([_row("RUN-OLD", "pass")])
    assert json.loads(template.read_text(encoding="utf-8"))["report_generated_at"] == "RUN-NEW"

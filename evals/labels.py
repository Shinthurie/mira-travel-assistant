"""Human labels for judge calibration (10 behaviour cases, labelled by Shinthurie, never by an AI).

    python -m evals.labels make         # write evals/human_labels_template.jsonl from the latest report
    python -m evals.labels agreement    # after labelling: judge vs human agreement -> reports/judge_agreement.md

Each line has Mira's transcript and ``"human_label": null``. Fill in "pass" or "fail" and a one-line
``human_reason`` yourself. The template deliberately does NOT show the judge's verdict (no anchoring).
"""

from __future__ import annotations

import argparse
import json
import sys

from mira import config

TEMPLATE = config.REPO_ROOT / "evals" / "human_labels_template.jsonl"
REPORT = config.REPO_ROOT / "reports" / "eval_report.json"  # --report picks another run, e.g. the LLM subset
AGREEMENT = config.REPO_ROOT / "reports" / "judge_agreement.md"
LABEL_CASES = ["S01", "S07", "S08", "S09", "S12", "S14", "S16", "S17", "M23", "M28"]


def make(force: bool) -> int:
    if TEMPLATE.exists() and not force:
        existing = [json.loads(l) for l in TEMPLATE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if any(r.get("human_label") for r in existing):
            print(f"{TEMPLATE.name} already has labels. Use --force to overwrite (this erases them).")
            return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in report["cases"]}
    from evals.run import load_cases
    behaviours = {c["id"]: c["expected"].get("behaviour") for c in load_cases()}
    lines = []
    for cid in LABEL_CASES:
        c = cases.get(cid)
        if c is None:
            print(f"warning: {cid} not in the latest report; run the full suite first")
            continue
        lines.append(json.dumps({
            "id": cid, "expected_behaviour": behaviours[cid], "report_generated_at": report["generated_at"],
            "mode": report["mode"],
            "transcript": [{"traveller": t["user"], "mira": t["text"], "ui": t["components"],
                            "sources": [f"{s['doc_id']} {s['title']} ({s['section']})" for s in t["citations"]]}
                           for t in c["transcript"]],
            "human_label": None, "human_reason": "",
        }, ensure_ascii=False))
    TEMPLATE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} cases to {TEMPLATE.relative_to(config.REPO_ROOT)}. Label them yourself: "
          f'"human_label": "pass" or "fail", plus a one-line "human_reason".')
    return 0


def agreement() -> int:
    rows = [json.loads(l) for l in TEMPLATE.read_text(encoding="utf-8").splitlines() if l.strip()]
    unlabelled = [r["id"] for r in rows if r.get("human_label") not in ("pass", "fail")]
    if unlabelled:
        print(f"Not labelled yet: {', '.join(unlabelled)}. Fill in human_label first.")
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    judge = {c["id"]: next((x for x in c["checks"] if x["name"] == "judge_behaviour"), None) for c in report["cases"]}
    compared, agree, disagreements = 0, 0, []
    for r in rows:
        j = judge.get(r["id"])
        if j is None or j["passed"] is None:
            continue
        compared += 1
        judge_label = "pass" if j["passed"] else "fail"
        if judge_label == r["human_label"]:
            agree += 1
        else:
            disagreements.append((r["id"], r["human_label"], judge_label, r["human_reason"], j["detail"]))
    if compared == 0:
        print("The latest report has no judge verdicts (no judge API key). Run `python -m evals.run` with a key first.")
        return 1
    lines = ["# Judge vs human agreement", "",
             f"- Judge model: {report.get('judge_model')} · report {report['generated_at']} (git {report['git_sha']})",
             f"- Agreement: **{100 * agree / compared:.0f}%** ({agree}/{compared} cases)", "",
             "## Disagreements", ""]
    lines += [f"- **{cid}**: human {h}, judge {jl}. Human: {hr}. Judge: {jr}" for cid, h, jl, hr, jr in disagreements] or ["None."]
    lines += ["", "## Limits", "",
              "- 10 cases is a small sample: one disagreement moves agreement by 10 points.",
              "- The judge sees text, card names and sources, not the rendered UI.",
              "- Prices, flags, leaks and UI validity are never judged by the LLM; code checks them."]
    AGREEMENT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Agreement {agree}/{compared}. Written to {AGREEMENT.relative_to(config.REPO_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m evals.labels")
    p.add_argument("command", choices=["make", "agreement"])
    p.add_argument("--force", action="store_true")
    p.add_argument("--report", default="eval_report", help="which run to use: reports/<name>.json")
    a = p.parse_args(argv)
    global REPORT
    REPORT = config.REPO_ROOT / "reports" / f"{a.report}.json"
    return make(a.force) if a.command == "make" else agreement()


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluation suite: ``python -m evals.run [--tag pricing] [--max-cases N] [--repeats 3] [--no-judge] [--offline]``

- Loads the 17 seed cases UNCHANGED from the dataset, plus evals/cases/*.jsonl (our own).
- Runs each case through the real LangGraph agent (fresh in-memory DB per run).
- Code checks wherever there is an exact answer; the LLM judge (different model) for behaviour.
- Price and flag cases run ``--repeats`` times; the WORST run counts.
- Writes reports/eval_report.md + .json and keeps every run in reports/history/.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from mira import config

EVAL_DIR = Path(__file__).parent
REPORT_DIR = config.REPO_ROOT / "reports"
SEED_META: dict[str, tuple[list[int], list[str]]] = {
    "S01": ([1], ["discovery"]), "S02": ([5, 3], ["pricing", "golden"]),
    "S03": ([5, 3, 1], ["pricing", "golden", "multi_turn"]), "S04": ([6], ["pricing", "flag"]),
    "S05": ([6], ["pricing", "flag"]), "S06": ([6, 4], ["pricing", "flag", "grounding"]),
    "S07": ([4], ["grounding"]), "S08": ([4], ["grounding"]), "S09": ([4], ["grounding"]),
    "S10": ([4], ["grounding"]), "S11": ([6], ["pricing", "flag"]), "S12": ([5], ["injection"]),
    "S13": ([1, 5], ["pricing", "golden", "multi_turn"]), "S14": ([1], ["off_topic"]),
    "S15": ([5], ["pricing", "golden"]), "S16": ([4, 6], ["grounding"]), "S17": ([4], ["grounding"]),
}
REPEAT_TAGS = {"pricing", "flag"}
LEAK = re.compile(r"\b(LKR|margin|gross profit|GP ?%|cost_usd|cost_lkr)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def load_cases() -> list[dict]:
    cases = []
    for line in config.EVAL_SEED_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            seed = json.loads(line)  # unchanged from the dataset
            reqs, tags = SEED_META[seed["id"]]
            cases.append({**seed, "requirements": reqs, "tags": tags, "source": "seed"})
    for path in sorted((EVAL_DIR / "cases").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append({**json.loads(line), "source": path.name})
    return cases


# ---------------------------------------------------------------------------
# Running one case
# ---------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    passed: bool | None          # None = skipped
    detail: str = ""
    kind: str = "code"           # code | judge


@dataclass
class RunResult:
    case_id: str
    repeat: int
    transcript: list[dict] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    error: str | None = None
    first_quote_ms: int | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed is not False for c in self.checks)


def _setup(ctx, case: dict, gen_dir: Path) -> dict:
    """Case set-up steps (returning visitor, content drafts). Returns values the checks need."""
    import mira.content_agent as ca
    from mira.db import User
    info: dict[str, Any] = {}
    setup = case.get("setup")
    if setup == "consent_visitor":
        info["visitor_id"] = f"eval-visitor-{uuid.uuid4().hex[:8]}"
        ctx.store.give_consent(info["visitor_id"])
    if setup in ("draft_only", "draft_published"):
        ca.GENERATED_DIR = gen_dir
        staff = User(username="staff", role="staff", password_hash="")
        draft = ca.create_draft("Add a 5-day Hill Country tour using the Ella photos", staff, ctx.catalog.content,
                                ctx.retriever, ctx.store, ctx.llm, ctx.today)
        info["draft_id"] = draft.doc_id
        if setup == "draft_published":
            ca.publish_draft(draft.id, User(username="approver", role="approver", password_hash=""), ctx.store)
            ctx.rebuild_content()
    return info


def run_case(case: dict, repeat: int, use_llm: bool) -> RunResult:
    from mira.agent.context import build_context, set_context
    from mira.agent.graph import build_graph
    from mira.db import Store
    from mira.llm import get_llm
    from mira.tracing import Tracer

    result = RunResult(case_id=case["id"], repeat=repeat)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store("sqlite:///:memory:")
        ctx = build_context(store=store, llm=get_llm("mira") if use_llm else None, tracer=Tracer())
        set_context(ctx)
        graph = build_graph()
        info = _setup(ctx, case, Path(tmp) / "generated")
        thread = f"eval-{case['id']}-{repeat}-{uuid.uuid4().hex[:6]}"
        t0 = time.perf_counter()
        try:
            for raw in case["turns"]:
                text = raw
                if raw.startswith("@new_conversation"):
                    thread = f"{thread}-b"
                    text = raw.removeprefix("@new_conversation").strip()
                payload: dict = {"messages": [HumanMessage(content=text)]}
                if info.get("visitor_id"):
                    payload["visitor_id"] = info["visitor_id"]
                start = time.perf_counter()
                state = graph.invoke(payload, config={"configurable": {"thread_id": thread}})
                turn = state["turn"]
                latency = int((time.perf_counter() - start) * 1000)
                comps = []
                for op in turn.get("ops", []):
                    if "updateComponents" in op:
                        comp = op["updateComponents"]["components"][0]
                        comps.append(comp["component"])
                        if comp["component"] == "TourShelf":  # count the cards inside a shelf
                            comps += ["TourCard"] * len(comp["tours"])
                result.transcript.append({
                    "user": text, "text": turn.get("final_text", ""), "components": comps, "ops": turn.get("ops", []),
                    "pricing": turn.get("pricing"), "citations": turn.get("citations", []), "guard": turn.get("guard"),
                    "ui_fallbacks": turn.get("ui_fallbacks", []), "question_slot": turn.get("question_slot"),
                    "trace_id": turn.get("trace_id"), "trace_url": turn.get("trace_url"), "latency_ms": latency,
                    "mode": turn.get("mode"), "thread": thread,
                })
                if result.first_quote_ms is None and (turn.get("pricing") or {}).get("kind") == "quote":
                    result.first_quote_ms = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:  # a crash is a failure, reported with its message
            result.error = f"{type(exc).__name__}: {exc}"
            return result
        result.checks = code_checks(case, result, ctx, info)
    return result


# ---------------------------------------------------------------------------
# Code checks
# ---------------------------------------------------------------------------


def _engine(request: dict, ctx):
    from mira.pricing.engine import quote
    from mira.pricing.schemas import PricingRequest
    return quote(PricingRequest.model_validate(request), ctx.catalog, today=ctx.today)


def code_checks(case: dict, run: RunResult, ctx, info: dict) -> list[Check]:
    from mira.agent.guard import amounts_in, find_money
    from mira.ui.a2ui import validate_operations

    exp = case["expected"]
    checks: list[Check] = []
    tr = run.transcript
    quotes = [t for t in tr if (t["pricing"] or {}).get("kind") == "quote"]

    # 1. Every UI payload valid against the catalog
    errors = [e for t in tr for e in validate_operations(t["ops"])] + [f for t in tr for f in t["ui_fallbacks"]]
    checks.append(Check("ui_payloads_valid", not errors, "; ".join(errors)[:300]))

    # 2. No cost / margin / LKR leaks to the traveller
    leaks = [m.group(0) for t in tr for m in LEAK.finditer(t["text"] + json.dumps(t["ops"]))]
    checks.append(Check("no_internal_leak", not leaks, ", ".join(leaks)))

    # 3. No draft / unpublished content used
    banned = {"T15"} | ({info["draft_id"]} if "draft_id" in info and case.get("setup") == "draft_only" else set())
    roots = [op["updateComponents"]["components"][0] for t in tr for op in t["ops"] if "updateComponents" in op]
    shown_tours = [r.get("tour_id") for r in roots] + [x.get("tour_id") for r in roots for x in r.get("tours", [])] \
        + [op["updateDataModel"]["value"].get("tour_id") for t in tr for op in t["ops"] if "updateDataModel" in op]
    used = {c["doc_id"] for t in tr for c in t["citations"]} | {x for x in shown_tours if isinstance(x, str)}
    checks.append(Check("no_unapproved_content", not (used & banned), ", ".join(sorted(used & banned))))

    # 4. No invented amounts: every money mention is an engine value from this conversation
    engine_values: set[Decimal] = set()
    for t in quotes:
        engine_values |= {Decimal(t["pricing"]["price_usd"]), Decimal(t["pricing"]["deposit_usd"])}
        r = _engine(t["pricing"]["request"], ctx)
        if r.kind == "quote":
            engine_values.add(r.traveller.balance_usd)
    cited = [p.text for p in ctx.retriever.passages if p.passage_id in {c["passage_id"] for t in tr for c in t["citations"]}]
    policy_values = amounts_in(cited)
    invented = [m.text for t in tr for m in find_money(t["text"])
                if not (m.kind == "amount" and m.currency == "USD" and m.value in engine_values | policy_values)]
    checks.append(Check("no_invented_amounts", not invented, ", ".join(invented)))

    # 5. Consistency: each shown price equals the engine's output for the extracted parameters
    for i, t in enumerate(quotes):
        r = _engine(t["pricing"]["request"], ctx)
        ok = r.kind == "quote" and str(r.traveller.price_usd) == t["pricing"]["price_usd"] and \
            str(r.traveller.deposit_usd) == t["pricing"]["deposit_usd"]
        card = next((op["updateDataModel"]["value"] for op in t["ops"] if "updateDataModel" in op
                     and "price_usd" in op["updateDataModel"]["value"]), None)
        ok = ok and card is not None and card["price_usd"] == t["pricing"]["price_usd"]
        checks.append(Check(f"price_consistency_{i + 1}", ok,
                            f"shown {t['pricing']['price_usd']}/{t['pricing']['deposit_usd']} engine "
                            f"{getattr(getattr(r, 'traveller', None), 'price_usd', r.kind)}"))

    etype = exp.get("type")
    # 6. Golden: engine output equals the brief's expected values
    golden: list[dict] = []
    if etype == "quote" and "price_usd" in exp:
        golden = [exp]
    elif etype == "quote_sequence":
        golden = exp["quotes"]
    if golden:
        got = [(t["pricing"]["tour_id"], int(Decimal(t["pricing"]["price_usd"])), int(Decimal(t["pricing"]["deposit_usd"])))
               for t in quotes]
        want = [(g["tour"], g["price_usd"], g["deposit_usd"]) for g in golden]
        checks.append(Check("golden_price", got == want, f"got {got} want {want}"))
    elif etype in ("quote", "quote_then_behaviour") and exp.get("tour"):
        checks.append(Check("quoted_expected_tour", bool(quotes) and quotes[0]["pricing"]["tour_id"] == exp["tour"],
                            f"quotes: {[q['pricing']['tour_id'] for q in quotes]}"))
    if etype == "quote_sequence_consistency":
        checks.append(Check("quote_count", len(quotes) >= exp["quotes"], f"{len(quotes)} quotes"))

    # 7. Flag / no price
    if etype == "flag_no_price":
        money = [m.text for t in tr for m in find_money(t["text"])]
        cards = [op for t in tr for op in t["ops"] if "updateDataModel" in op and "price_usd" in op["updateDataModel"]["value"]]
        checks.append(Check("no_price_shown", not money and not cards and not quotes, ", ".join(money)))
        threads = {t["thread"] for t in tr}
        flags = [f for f in ctx.store.list_flags() if f.thread_id in threads and f.source == "pricing"]
        checks.append(Check("staff_flag_raised", bool(flags), ", ".join(f.reason for f in flags)))
        if exp.get("reason"):
            checks.append(Check("flag_reason", any(f.reason == exp["reason"] for f in flags),
                                f"want {exp['reason']}, got {[f.reason for f in flags]}"))
        checks.append(Check("handoff_card", any("SpecialistHandoff" in t["components"] for t in tr)))

    if exp.get("no_money") or etype == "planner":
        money = [m.text for t in tr for m in find_money(t["text"])]
        checks.append(Check("no_money_amounts", not money and not quotes, ", ".join(money)))
    if exp.get("no_teaser"):
        teaser = [m.text for t in tr for m in find_money(t["text"]) if m.value == Decimal(exp["no_teaser"])]
        checks.append(Check("teaser_not_shown", not teaser, ", ".join(teaser)))
    if etype == "planner":
        tours = sum(t["components"].count("TourCard") for t in tr)
        checks.append(Check("closest_tours_shown", tours >= 2, f"{tours} tour cards"))
        checks.append(Check("custom_enquiry_saved", any(e.kind == "custom" for e in ctx.store.list_enquiries())))
    if exp.get("must_cite_any"):
        want = {info.get("draft_id") if d == "@draft" else d for d in exp["must_cite_any"]}
        cited_docs = {c["doc_id"] for t in tr for c in t["citations"]}
        checks.append(Check("cites_expected_source", bool(cited_docs & want), f"cited {sorted(cited_docs)}"))
    if exp.get("no_citation_of"):
        bad = {info.get("draft_id") if d == "@draft" else d for d in exp["no_citation_of"]}
        cited_docs = {c["doc_id"] for t in tr for c in t["citations"]}
        checks.append(Check("does_not_cite", not (cited_docs & bad), f"cited {sorted(cited_docs)}"))
    if exp.get("components_include"):
        shown = {c for t in tr for c in t["components"]}
        missing = set(exp["components_include"]) - shown
        checks.append(Check("components_shown", not missing, f"missing {sorted(missing)}"))
    if exp.get("shows_useful_within_questions"):
        n = exp["shows_useful_within_questions"]
        useful = any("TourCard" in t["components"] or "PriceBreakdown" in t["components"] for t in tr[:n])
        asked = [t["question_slot"] for t in tr if t["question_slot"]]
        checks.append(Check("useful_within_3_questions", useful, f"asked {asked}"))
        checks.append(Check("no_repeated_question", len(asked) == len(set(asked)), f"asked {asked}"))
    if etype == "returning":
        second = [t for t in tr if t["thread"].endswith("-b")]
        ok = bool(second) and "Welcome back" in second[0]["text"] and (second[0]["pricing"] or {}).get("kind") == "quote"
        checks.append(Check("returning_greeted_with_last_quote", ok, second[0]["text"][:120] if second else "no 2nd conversation"))
        checks.append(Check("not_asked_again", bool(second) and second[0]["question_slot"] is None))
    if exp.get("enquiry_saved"):
        checks.append(Check("enquiry_saved", any(e.kind == "quote" and e.quote_id for e in ctx.store.list_enquiries())))
    if exp.get("pii_not_in_trace"):
        from mira.tracing import TRACE_DIR
        raw = "".join((TRACE_DIR / f"{t['trace_id']}.json").read_text(encoding="utf-8") for t in tr
                      if (TRACE_DIR / f"{t['trace_id']}.json").exists())
        found = [s for s in exp["pii_not_in_trace"] if s in raw]
        checks.append(Check("pii_not_in_trace", bool(raw) and not found, f"found {found}" if found else ""))
    return checks


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=config.REPO_ROOT).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=config.REPO_ROOT).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}% ({a}/{b})" if b else "n/a"


MODEL_CALLS: list[tuple[str, str, int]] = []  # (model, purpose, latency_ms) for every LLM call in the run


def model_call_summary() -> list[dict]:
    """Calls and latency per (model, purpose): shows how model routing split the work."""
    groups: dict[tuple[str, str], list[int]] = {}
    for model, purpose, ms in MODEL_CALLS:
        groups.setdefault((model, purpose), []).append(ms)
    return [{"model": m, "purpose": p, "calls": len(v), "median_ms": statistics.median(v), "max_ms": max(v)}
            for (m, p), v in sorted(groups.items())]


def summarise(cases: list[dict], results: dict[str, list[RunResult]], judge_info: dict, args) -> dict:
    from mira.agent.context import get_context
    rows = []
    for case in cases:
        runs = results[case["id"]]
        worst = next((r for r in runs if not r.passed), runs[0])
        rows.append({
            "id": case["id"], "category": case.get("category"), "requirements": case["requirements"], "tags": case["tags"],
            "source": case["source"], "turns": len(case["turns"]), "runs": len(runs), "passed": all(r.passed for r in runs),
            "error": worst.error, "checks": [c.__dict__ for c in worst.checks],
            "trace_urls": [t["trace_url"] for t in worst.transcript],
            "latencies_ms": [t["latency_ms"] for r in runs for t in r.transcript],
            "modes": [t["mode"] for r in runs for t in r.transcript],
            "first_quote_ms": [r.first_quote_ms for r in runs if r.first_quote_ms is not None],
            "transcript": [{k: t[k] for k in ("user", "text", "components", "citations", "pricing")} for t in worst.transcript],
        })

    def checks_named(prefix: str) -> list[bool]:
        out = []
        for case in cases:
            for r in results[case["id"]]:
                out += [c.passed for c in r.checks if c.name.startswith(prefix) and c.passed is not None]
        return out

    per_req: dict[int, list[bool]] = {}
    for row in rows:
        for req in row["requirements"]:
            per_req.setdefault(req, []).append(row["passed"])
    golden, consistency = checks_named("golden_price"), checks_named("price_consistency")
    invented = sum(1 for case in cases for r in results[case["id"]] for c in r.checks
                   if c.name == "no_invented_amounts" and c.passed is False)
    flag_rows = [r for r in rows if any(c["name"] == "staff_flag_raised" for c in r["checks"])]
    lat = [x for r in rows for x in r["latencies_ms"]]
    fq = [x for r in rows for x in r["first_quote_ms"]]
    judge_checks = [c for r in rows for c in r["checks"] if c["kind"] == "judge"]
    ctx = get_context()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_sha": git_sha(),
        "mode": "llm" if args.use_llm else "offline-rules", "mira_model": judge_info.get("mira_model"),
        "routing_small_model": judge_info.get("small_model"),
        "judge_model": judge_info.get("judge_model"), "today": config.today().isoformat(),
        "settings_overridden": list(ctx.catalog.workbook.settings.overridden),
        "margins": {"day_tour": str(ctx.catalog.workbook.settings.margin_day_tour),
                    "multi_day": str(ctx.catalog.workbook.settings.margin_multi_day)},
        "filters": {"tags": args.tag, "max_cases": args.max_cases, "repeats": args.repeats},
        "totals": {"cases": len(rows), "passed": sum(r["passed"] for r in rows),
                   "multi_turn": sum(1 for r in rows if r["turns"] > 1),
                   "seed_cases": sum(1 for r in rows if r["source"] == "seed")},
        "per_requirement": {str(k): {"passed": sum(v), "total": len(v)} for k, v in sorted(per_req.items())},
        "targets": {
            "price_accuracy_golden": {"passed": sum(golden), "total": len(golden)},
            "price_consistency": {"passed": sum(consistency), "total": len(consistency)},
            "invented_prices": invented,
            "missing_expired_rate_handling": {"passed": sum(r["passed"] for r in flag_rows), "total": len(flag_rows)},
        },
        "latency_ms": {"turns": len(lat), "p50": statistics.median(lat) if lat else None,
                       "p95": sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else None, "max": max(lat) if lat else None},
        "time_to_first_quote_ms": {"median": statistics.median(fq) if fq else None, "max": max(fq) if fq else None,
                                   "under_60s": sum(1 for x in fq if x < 60000), "total": len(fq)},
        "model_calls": model_call_summary(),
        "turn_modes": {m: sum(1 for r in rows for x in r["modes"] if x == m) for m in ("llm", "rules")},
        "judge": {"model": judge_info.get("judge_model"), "available": judge_info.get("available"),
                  "passed": sum(1 for c in judge_checks if c["passed"] is True),
                  "failed": sum(1 for c in judge_checks if c["passed"] is False),
                  "skipped": sum(1 for c in judge_checks if c["passed"] is None)},
        "cases": rows,
    }


def write_report(summary: dict) -> Path:
    s = summary
    t = s["targets"]
    lines = [
        "# Mira evaluation report", "",
        f"- Generated: {s['generated_at']} · git `{s['git_sha']}` · today = {s['today']}",
        f"- Mode: **{s['mode']}** · Mira model: {s['mira_model'] or 'none (rule-based extraction)'} · "
        f"judge: {s['judge_model'] or 'not available (no API key)'} · routing: "
        f"{('simple turns -> ' + s['routing_small_model']) if s.get('routing_small_model') else 'off'}",
        f"- Margins: day {s['margins']['day_tour']}, multi-day {s['margins']['multi_day']}"
        + (f" · **settings overridden: {', '.join(s['settings_overridden'])}**" if s['settings_overridden'] else ""),
        f"- Cases: {s['totals']['cases']} ({s['totals']['seed_cases']} seed, {s['totals']['multi_turn']} multi-turn) · "
        f"price/flag cases run {s['filters']['repeats']}x (worst run counts)", "",
        "## Targets", "",
        "| Target | Result |", "|---|---|",
        f"| Price accuracy (golden: engine = brief's expected values) | {pct(t['price_accuracy_golden']['passed'], t['price_accuracy_golden']['total'])} |",
        f"| Price consistency (shown price = engine for extracted parameters) | {pct(t['price_consistency']['passed'], t['price_consistency']['total'])} |",
        f"| Invented prices (runs with an amount not from the engine) | **{t['invented_prices']}** |",
        f"| Missing / expired / no-rate handling (no price + staff flag) | {pct(t['missing_expired_rate_handling']['passed'], t['missing_expired_rate_handling']['total'])} |",
        f"| Overall cases passed | {pct(s['totals']['passed'], s['totals']['cases'])} |", "",
        "## Pass rate per requirement", "", "| Requirement | Passed |", "|---|---|",
    ]
    names = {1: "1 Discover the trip", 2: "2 Returning visitors", 3: "3 Generated UI", 4: "4 Content only",
             5: "5 Correct prices", 6: "6 Missing/expired rates", 7: "7 Private enquiries", 8: "8 Approved content"}
    for k, v in s["per_requirement"].items():
        lines.append(f"| {names.get(int(k), k)} | {pct(v['passed'], v['total'])} |")
    lat, fq, j = s["latency_ms"], s["time_to_first_quote_ms"], s["judge"]
    lines += ["", "## Speed", "",
              f"- Per turn: median {lat['p50']} ms, p95 {lat['p95']} ms, max {lat['max']} ms ({lat['turns']} turns)",
              f"- Time to first quote: median {fq['median']} ms, max {fq['max']} ms; under 60 s: {fq['under_60s']}/{fq['total']}", "",
              "## How each turn was understood", "",
              f"- By the LLM: {s['turn_modes']['llm']} turns · by the rule-based fallback: {s['turn_modes']['rules']} turns"
              + (" (in LLM mode a rules turn means every model call failed, e.g. quota or overload)"
                 if s['mode'] == 'llm' and s['turn_modes']['rules'] else ""), "",
              "## Model calls (routing)", "",
              "| Model | Purpose | Calls | Median ms | Max ms |", "|---|---|---|---|---|",
              *([f"| {r['model']} | {r['purpose']} | {r['calls']} | {r['median_ms']} | {r['max_ms']} |"
                 for r in s.get("model_calls", [])] or ["| none (offline mode) | | | | |"]), "",
              "## LLM judge (behaviour cases)", "",
              f"- Judge model: {j['model'] or 'none'} · passed {j['passed']}, failed {j['failed']}, skipped {j['skipped']}",
              "- Behaviour cases without a judge are **skipped, not passed**; their code checks still apply.", ""]
    failing = [c for c in s["cases"] if not c["passed"]]
    lines += ["## Failing cases", ""]
    if not failing:
        lines.append("None.")
    for c in failing:
        bad = [f"{x['name']}: {x['detail']}" for x in c["checks"] if x["passed"] is False]
        lines.append(f"- **{c['id']}** ({c['category']}, req {c['requirements']}): {c['error'] or '; '.join(bad)}")
        lines.append(f"  - traces: {', '.join(u for u in c['trace_urls'] if u)}")
    lines += ["", "## All cases", "", "| Case | Req | Result | Checks |", "|---|---|---|---|"]
    for c in s["cases"]:
        ok = sum(1 for x in c["checks"] if x["passed"] is True)
        sk = sum(1 for x in c["checks"] if x["passed"] is None)
        lines.append(f"| {c['id']} | {c['requirements']} | {'pass' if c['passed'] else '**FAIL**'} | "
                     f"{ok}/{len(c['checks'])} passed{f', {sk} skipped' if sk else ''} |")
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "history").mkdir(exist_ok=True)
    md, js = "\n".join(lines) + "\n", json.dumps(s, indent=2, default=str)
    (REPORT_DIR / "eval_report.md").write_text(md, encoding="utf-8")
    (REPORT_DIR / "eval_report.json").write_text(js, encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (REPORT_DIR / "history" / f"{stamp}_{s['git_sha']}.md").write_text(md, encoding="utf-8")
    (REPORT_DIR / "history" / f"{stamp}_{s['git_sha']}.json").write_text(js, encoding="utf-8")
    return REPORT_DIR / "eval_report.md"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import logging
    logging.disable(logging.WARNING)
    p = argparse.ArgumentParser(prog="python -m evals.run")
    p.add_argument("--tag", action="append", help="only cases with this tag (repeatable), e.g. --tag pricing")
    p.add_argument("--max-cases", type=int, default=None)
    p.add_argument("--repeats", type=int, default=3, help="runs for price/flag cases (worst counts)")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--offline", action="store_true", help="force rule-based mode even if a key is set")
    args = p.parse_args(argv)

    from mira.llm import add_call_hook, get_llm
    from evals.judge import Judge
    add_call_hook(lambda call: MODEL_CALLS.append((call.model, call.purpose, call.latency_ms)))
    args.use_llm = not args.offline and get_llm("mira") is not None
    judge = Judge() if not args.no_judge else Judge(llm=None)
    if judge.available and args.use_llm and judge.model == getattr(get_llm("mira"), "model", None):
        print("WARNING: judge model equals Mira's model; set a different JUDGE_MODEL.")

    cases = load_cases()
    if args.tag:
        cases = [c for c in cases if set(args.tag) & set(c["tags"])]
    if args.max_cases:
        cases = cases[: args.max_cases]

    results: dict[str, list[RunResult]] = {}
    for case in cases:
        n = args.repeats if set(case["tags"]) & REPEAT_TAGS else 1
        runs = [run_case(case, i, args.use_llm) for i in range(n)]
        behaviour = case["expected"].get("behaviour")
        if behaviour and runs[0].error is None:
            for run in runs[:1]:
                v = judge.judge(behaviour, run.transcript)
                run.checks.append(Check("judge_behaviour", None if v is None else v.verdict == "pass",
                                        (judge.last_error or "no judge model (no API key or --no-judge)") if v is None else v.reason, kind="judge"))
            for run in runs[1:]:
                run.checks.append(runs[0].checks[-1])
        results[case["id"]] = runs
        status = "pass" if all(r.passed for r in runs) else "FAIL"
        print(f"{case['id']:4} {status:4} ({n} run{'s' if n > 1 else ''})"
              + ("" if status == "pass" else "  " + "; ".join(
                  f"{c.name}: {c.detail}" for r in runs for c in r.checks if c.passed is False)[:200]
                 + (f" {runs[0].error}" if runs[0].error else "")))

    mira_llm = get_llm("mira") if args.use_llm else None
    summary = summarise(cases, results, {"mira_model": getattr(mira_llm, "model", None),
                                         "small_model": getattr(getattr(mira_llm, "small", None), "model", None),
                                         "judge_model": judge.model, "available": judge.available}, args)
    path = write_report(summary)
    t = summary["targets"]
    print(f"\n{summary['totals']['passed']}/{summary['totals']['cases']} cases passed · golden "
          f"{t['price_accuracy_golden']['passed']}/{t['price_accuracy_golden']['total']} · consistency "
          f"{t['price_consistency']['passed']}/{t['price_consistency']['total']} · invented prices {t['invented_prices']}")
    print(f"Report: {path.relative_to(config.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

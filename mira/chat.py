"""``python -m mira.chat``: talk to Mira in the terminal (same graph as the website).

    python -m mira.chat                 interactive
    python -m mira.chat --seed S03      replay a seed conversation from eval_seed.jsonl
    python -m mira.chat --all-seeds     replay all 17 seeds
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from langchain_core.messages import HumanMessage

from mira import config


def run_turn(graph, thread_id: str, text: str, visitor_id: str | None = None) -> dict:
    """Send one message through the graph; return the final state."""
    payload: dict = {"messages": [HumanMessage(content=text)]}
    if visitor_id:
        payload["visitor_id"] = visitor_id
    return graph.invoke(payload, config={"configurable": {"thread_id": thread_id}})


def show(state: dict) -> None:
    turn = state.get("turn") or {}
    print(f"\nMira: {turn.get('final_text', '')}")
    for op in turn.get("ops") or []:
        if "updateComponents" in op:
            comp = op["updateComponents"]["components"][0]
            print(f"  [UI] {comp['component']}", end="")
        if "updateDataModel" in op:
            v = op["updateDataModel"]["value"]
            if "price_usd" in v:
                print(f"  price USD {v['price_usd']} / deposit USD {v['deposit_usd']}", end="")
            print()
        elif "updateComponents" in op:
            comp = op["updateComponents"]["components"][0]
            print(f"  {comp.get('title', comp.get('prompt', ''))}")
    meta = {"mode": turn.get("mode"), "route": (turn.get("extraction") or {}).get("intent"),
            "pricing": (turn.get("pricing") or {}).get("kind"), "guard": (turn.get("guard") or {}).get("passed"),
            "trace": turn.get("trace_url")}
    print(f"  ({json.dumps(meta)})")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m mira.chat")
    parser.add_argument("--seed", help="replay one seed case, e.g. S03")
    parser.add_argument("--all-seeds", action="store_true")
    args = parser.parse_args(argv)

    from mira.agent.graph import build_graph
    graph = build_graph()

    if args.seed or args.all_seeds:
        seeds = [json.loads(l) for l in config.EVAL_SEED_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        for seed in seeds:
            if args.seed and seed["id"] != args.seed:
                continue
            print(f"\n===== {seed['id']} ({seed['category']}) expected: {json.dumps(seed['expected'])}")
            thread = f"cli-{seed['id']}-{uuid.uuid4().hex[:6]}"
            for text in seed["turns"]:
                print(f"\nYou:  {text}")
                show(run_turn(graph, thread, text))
        return 0

    thread = f"cli-{uuid.uuid4().hex[:8]}"
    print("Chat with Mira (Ctrl+C to quit).")
    try:
        while True:
            text = input("\nYou:  ").strip()
            if text:
                show(run_turn(graph, thread, text))
    except (KeyboardInterrupt, EOFError):
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

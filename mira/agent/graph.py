"""The Mira LangGraph.

    START -> intake -> (route) -> respond / answer / pricing / discovery / planner / booking / enquiry /
             service_handoff / no_tour_handoff  (any number, in route order)
          -> compose -> guard -> persist -> [render_ui tool] -> END

``render_mira_ui`` is a real LangChain tool run by a ToolNode, so ag-ui-langgraph emits a
TOOL_CALL_RESULT carrying ``{"a2ui_operations": [...]}``. It reads the operations from state
(already validated and price-guarded); the model never writes them.
"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode

from mira.agent import nodes
from mira.agent.state import GraphState

ACTION_NODES = ["respond", "answer", "pricing", "discovery", "planner", "booking", "enquiry",
                "service_handoff", "no_tour_handoff"]


@tool(nodes.RENDER_TOOL)
def render_mira_ui(state: Annotated[dict, InjectedState]) -> str:
    """Render this turn's validated Mira UI components (A2UI v0.9 operations)."""
    ops = (state.get("turn") or {}).get("ops") or []
    return json.dumps({"a2ui_operations": ops})


def _after_persist(state: dict) -> str:
    return "render_ui" if (state.get("turn") or {}).get("ops") else END


def build_graph(checkpointer=None):
    g = StateGraph(GraphState)
    g.add_node("intake", nodes.intake)
    for name in ACTION_NODES:
        g.add_node(name, getattr(nodes, name))
    g.add_node("compose", nodes.compose)
    g.add_node("guard", nodes.guard)
    g.add_node("persist", nodes.persist)
    g.add_node("render_ui", ToolNode([render_mira_ui]))

    targets = {name: name for name in ACTION_NODES} | {"compose": "compose"}
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", nodes.next_step, targets)
    for name in ACTION_NODES:
        g.add_conditional_edges(name, nodes.next_step, targets)
    g.add_edge("compose", "guard")
    g.add_edge("guard", "persist")
    g.add_conditional_edges("persist", _after_persist, {"render_ui": "render_ui", END: END})
    g.add_edge("render_ui", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())


graph = None


def get_graph():
    global graph
    if graph is None:
        graph = build_graph()
    return graph

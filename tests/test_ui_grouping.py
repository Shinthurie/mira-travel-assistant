"""UI composition: tour shelves, itinerary days, and the AG-UI text-before-cards fix."""

import asyncio

from mira.agent.nodes import group_tour_cards
from mira.agent.state import UIComponent
from mira.ui.a2ui import validate_operations
from tests.agent_helpers import chat, components, fresh_agent


def _card(tid: str, accent: str = "teal") -> UIComponent:
    return UIComponent(component="TourCard", props={
        "tour_id": tid, "title": tid, "category": "Round trip", "duration": "1 day", "places": ["Kandy"],
        "summary": "s", "priceable": True, "image": "placeholder", "source_ref": f"{tid}#overview", "accent": accent})


def test_two_or_more_tour_cards_become_one_shelf_in_place():
    other = UIComponent(component="EnquiryConfirmation", props={"enquiry_ref": "E-1", "summary": "x", "next_steps": [], "accent": "leaf"})
    out = group_tour_cards([_card("T01"), _card("T02", "sky"), other, _card("T03", "leaf")])
    assert [c.component for c in out] == ["TourShelf", "EnquiryConfirmation"]
    assert [t["tour_id"] for t in out[0].props["tours"]] == ["T01", "T02", "T03"]
    assert [t["accent"] for t in out[0].props["tours"]] == ["teal", "sky", "leaf"]  # one accent per card kept


def test_single_tour_card_stays_a_card():
    assert [c.component for c in group_tour_cards([_card("T01")])] == ["TourCard"]


def test_planner_shelf_is_valid_a2ui():
    _, graph = fresh_agent()
    turn = chat(graph, ["We're a family of four and want a custom 10 days across Kandy, Ella and the south coast."])[0]
    assert "TourShelf" in components(turn) and validate_operations(turn["ops"]) == []


def test_multi_day_tour_days_are_inside_the_one_tour_box():
    """One box per tour: the day-by-day plan is in the card's Details, not separate day cards."""
    _, graph = fresh_agent()
    turn = chat(graph, ["Tell me about the Cultural Triangle Sri Lanka Package"])[0]
    assert components(turn).count("ItineraryDay") == 0
    card = next(c for c in turn["components"] if c["component"] == "TourCard")
    days = card["props"]["details"]["days"]
    assert [d["day"] for d in days][:3] == [1, 2, 3] and days[0]["title"] == "Colombo to Anuradhapura"
    assert validate_operations(turn["ops"]) == []


def test_agui_agent_turns_manual_emit_into_text_events():
    """Workaround for copilotkit 0.1.97 dropping these events (mira/agui.py)."""
    from mira.agent.graph import build_graph
    from mira.agui import EMIT_MESSAGE, MiraAGUIAgent
    agent = MiraAGUIAgent(name="mira", description="t", graph=build_graph())
    agent.active_run = {}
    event = {"event": "on_custom_event", "name": EMIT_MESSAGE, "data": {"message": "Hello", "message_id": "msg_1"}}

    async def collect():
        return [e async for e in agent._handle_single_event(event, {})]

    out = asyncio.run(collect())
    assert [e.type.value for e in out] == ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]
    assert out[1].delta == "Hello" and all(e.message_id == "msg_1" for e in out)

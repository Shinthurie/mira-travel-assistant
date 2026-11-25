"""Typed shared state for the LangGraph agent.

LangGraph channels are a TypedDict, because CopilotKit/AG-UI also write their own keys
(``messages``, ``tools``, ``copilotkit``, ``ag-ui``). Our own state is the Pydantic model
``MiraSession`` stored under ``session``, and ``TurnState`` under ``turn`` (reset every turn).
Nodes always go through ``load_session`` / ``load_turn`` so they work with typed objects.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Intent(str, Enum):
    GREETING = "greeting"            # hi / what can you do
    QUOTE = "quote"                  # wants a price (or gives details for one)
    INFO = "info"                    # question about tours, places, policies
    PLAN_CUSTOM = "plan_custom"      # wants a custom multi-day itinerary
    PRICE_VARIANT = "price_variant"  # per person / other currency / discount
    BOOK = "book"                    # wants to book the quoted tour
    ENQUIRY = "enquiry"              # wants a specialist to contact them
    OFF_TOPIC = "off_topic"
    INJECTION = "injection"          # tries to change Mira's rules
    FORGET_ME = "forget_me"


class PriceVariant(str, Enum):
    NONE = "none"
    PER_PERSON = "per_person"
    CURRENCY = "currency"
    DISCOUNT = "discount"
    TEASER = "teaser"                # "is it really from USD 85?"


class Extraction(BaseModel):
    """What the model (or the rule-based fallback) understood from ONE traveller message.

    Every field is optional: null means "not mentioned in this message". Code merges it into
    the session and validates every value; the model never sets prices.
    """

    intent: Intent
    wants_price: bool = False
    wants_info: bool = False
    price_variant: PriceVariant = PriceVariant.NONE
    tour_id: Optional[str] = Field(None, description="Tour id from the catalogue list, e.g. T09, if one is clearly meant")
    tour_mention: Optional[str] = Field(None, description="The words the traveller used for a tour or place")
    trip_type: Optional[Literal["day_tour", "multi_day", "custom"]] = None
    traveller_type: Optional[Literal["solo", "couple", "family", "group"]] = None
    adults: Optional[int] = None
    child_ages: Optional[list[int]] = Field(None, description="Ages of ALL travellers under 18, if given")
    add_child_ages: Optional[list[int]] = Field(None, description="Ages of children being ADDED to the group")
    start_date: Optional[date] = None
    duration_days: Optional[int] = None
    places: Optional[list[str]] = None
    interests: Optional[list[str]] = None


class Slots(BaseModel):
    """What Mira knows about the trip so far."""

    trip_type: Optional[Literal["day_tour", "multi_day", "custom"]] = None
    traveller_type: Optional[Literal["solo", "couple", "family", "group"]] = None
    adults: Optional[int] = None
    child_ages: list[int] = Field(default_factory=list)
    children_known: bool = False     # True once we know the child count (even if zero)
    start_date: Optional[date] = None
    tour_id: Optional[str] = None
    suggested_tour_id: Optional[str] = None
    duration_days: Optional[int] = None
    places: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)


class QuoteRef(BaseModel):
    """A quote shown in this conversation (traveller-safe values only)."""

    quote_id: int | None = None
    ref: str
    tour_id: str
    tour_title: str
    start_date: date
    adults: int
    child_ages: list[int]
    price_usd: str
    deposit_usd: str
    balance_usd: str


class MiraSession(BaseModel):
    """Persists across turns of one conversation (thread)."""

    visitor_id: Optional[str] = None
    consent: bool = False
    stage: Literal["greeting", "discovery", "informing", "quoted", "handoff", "booking", "done"] = "greeting"
    slots: Slots = Field(default_factory=Slots)
    questions_asked: int = 0
    asked: list[str] = Field(default_factory=list)       # slot names Mira already asked about
    quotes: list[QuoteRef] = Field(default_factory=list)
    allowed_amounts: list[str] = Field(default_factory=list)  # every USD amount the guard may let through
    flags: list[str] = Field(default_factory=list)        # flag refs raised in this conversation
    enquiry_refs: list[str] = Field(default_factory=list)
    turns: int = 0
    greeted_returning: bool = False


class UIComponent(BaseModel):
    """One catalog component to render (validated against the catalog in mira.ui)."""

    component: str
    props: dict[str, Any]


class TurnState(BaseModel):
    """Scratch space for the current turn. Reset by the intake node."""

    user_text: str = ""
    extraction: Optional[Extraction] = None
    mode: Literal["llm", "rules"] = "rules"
    route: list[str] = Field(default_factory=list)
    reply_parts: list[str] = Field(default_factory=list)
    components: list[UIComponent] = Field(default_factory=list)
    shelf_title: str = "Tours that match"   # "Picked for you" for consented personalisation
    citations: list[dict[str, str]] = Field(default_factory=list)
    retrieved_ids: list[str] = Field(default_factory=list)
    pricing: Optional[dict[str, Any]] = None              # {"kind": "quote"|"no_quote", ...} for traces/evals
    question_slot: Optional[str] = None
    guard: dict[str, Any] = Field(default_factory=dict)
    ui_fallbacks: list[str] = Field(default_factory=list)
    final_text: str = ""
    ops: list[dict[str, Any]] = Field(default_factory=list)  # A2UI operations for this turn
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None


GraphState = TypedDict("GraphState", {
    "messages": Annotated[list[AnyMessage], add_messages],
    "session": dict,
    "turn": dict,
    "tools": list,
    "copilotkit": dict,
    "ag-ui": dict,
    "visitor_id": str,
}, total=False)


def load_session(state: dict) -> MiraSession:
    return MiraSession.model_validate(state.get("session") or {})


def load_turn(state: dict) -> TurnState:
    return TurnState.model_validate(state.get("turn") or {})

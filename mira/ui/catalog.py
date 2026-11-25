"""Our A2UI component catalog: one Pydantic props model per component.

Every component that leaves the server is validated here first (the browser validates again with
zod). Unknown components, unknown props or wrong types are rejected; the caller falls back to text.

Fixed-schema surfaces (layout by us, data only from code): PriceBreakdown, BookingForm,
SpecialistHandoff, EnquiryConfirmation. Dynamic-schema surfaces (chosen by the agent):
TourCard, ItineraryDay, TravellerPicker, SourceCitation.

Brand rule: every card has exactly ONE accent colour (``accent``).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Accent = Literal["teal", "leaf", "sun", "sky", "coral"]
CATALOG_ID = "https://ceylon-compass.example/a2ui/mira-catalog/v1"


class _Props(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    accent: Accent


# --- Fixed-schema components (money and bookings) ---------------------------------


class PriceBreakdownProps(_Props):
    """Built ONLY from QuoteForTraveller. There is no cost, margin or GP field."""

    quote_ref: str
    tour_id: str
    tour_title: str
    start_date: str
    end_date: str
    duration: str
    travellers_summary: str
    currency: Literal["USD"] = "USD"
    price_usd: str
    deposit_usd: str
    balance_usd: str
    balance_due_date: Optional[str] = None
    pay_in_full: bool
    inclusions: list[str] = Field(default_factory=list, max_length=12)


class BookingFormProps(_Props):
    quote_ref: str
    tour_title: str
    price_usd: str
    deposit_usd: str
    pay_in_full: bool
    consent_text: str


class SpecialistHandoffProps(_Props):
    title: str
    reason_text: str
    tour_title: Optional[str] = None
    flag_ref: Optional[str] = None
    enquiry_ref: Optional[str] = None
    cta_label: str = "Ask a specialist"


class EnquiryConfirmationProps(_Props):
    enquiry_ref: str
    summary: str
    next_steps: list[str] = Field(default_factory=list, max_length=5)


# --- Dynamic-schema components (content, never money) -----------------------------


class TourCardProps(_Props):
    """No price field on purpose: prices only appear in PriceBreakdown."""

    tour_id: str
    title: str
    category: str
    duration: str
    places: list[str] = Field(default_factory=list, max_length=10)
    summary: str
    priceable: bool
    image: Literal["placeholder"] = "placeholder"   # the dataset has no photos
    source_ref: str
    included: list[str] = Field(default_factory=list, max_length=12)  # from the page's Inclusions section


class ItineraryDayProps(_Props):
    tour_id: str
    day_number: int = Field(ge=1, le=30)
    title: str
    description: str
    meals: list[str] = Field(default_factory=list, max_length=4)
    accommodation: Optional[str] = None
    entrance: list[str] = Field(default_factory=list, max_length=10)
    source_ref: str


class TravellerPickerProps(_Props):
    prompt: str
    adults_default: int = Field(ge=1, le=20)
    child_ages_default: list[int] = Field(default_factory=list, max_length=19)
    max_group: int = Field(20, ge=1, le=20)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passage_id: str
    doc_id: str
    title: str
    section: str
    note: str = ""  # e.g. "Older page: terms replaced by P02"


class SourceCitationProps(_Props):
    sources: list[Source] = Field(min_length=1, max_length=8)


class TourShelfProps(BaseModel):
    """Dynamic. Several tour cards in one row (swipeable on mobile). Each card keeps its own single accent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str
    tours: list[TourCardProps] = Field(min_length=2, max_length=4)


CATALOG: dict[str, type[BaseModel]] = {
    "PriceBreakdown": PriceBreakdownProps,
    "BookingForm": BookingFormProps,
    "SpecialistHandoff": SpecialistHandoffProps,
    "EnquiryConfirmation": EnquiryConfirmationProps,
    "TourCard": TourCardProps,
    "ItineraryDay": ItineraryDayProps,
    "TravellerPicker": TravellerPickerProps,
    "SourceCitation": SourceCitationProps,
    "TourShelf": TourShelfProps,
}
FIXED_SCHEMA = {"PriceBreakdown", "BookingForm", "SpecialistHandoff", "EnquiryConfirmation"}
DYNAMIC_SCHEMA = set(CATALOG) - FIXED_SCHEMA
# Number-valued strings in fixed components that must be engine values (checked by the guard).
MONEY_FIELDS = {"PriceBreakdown": ("price_usd", "deposit_usd", "balance_usd"),
                "BookingForm": ("price_usd", "deposit_usd")}


class CatalogError(ValueError):
    pass


def validate_component(component: str, props: dict[str, Any]) -> dict[str, Any]:
    """Validate props against the catalog. Returns JSON-safe props or raises CatalogError."""
    model = CATALOG.get(component)
    if model is None:
        raise CatalogError(f"unknown component {component!r}")
    try:
        return model.model_validate(props).model_dump(mode="json")
    except ValidationError as exc:
        raise CatalogError(f"{component}: {exc.errors(include_url=False)}") from exc


def json_schemas() -> dict[str, Any]:
    """JSON Schema of every component (exported to the frontend so zod and Pydantic agree)."""
    return {name: model.model_json_schema() for name, model in CATALOG.items()}

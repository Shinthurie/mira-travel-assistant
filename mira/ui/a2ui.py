"""Build A2UI v0.9 operations from validated catalog components.

- Fixed-schema components (PriceBreakdown, BookingForm, SpecialistHandoff, EnquiryConfirmation):
  the layout is a JSON file WE wrote (``mira/ui/schemas/<Name>.json``) whose values are bound to the
  data model by ``{"path": "/field"}``. Only code fills the data model (from QuoteForTraveller etc.).
- Dynamic-schema components (TourCard, ItineraryDay, TravellerPicker, SourceCitation): the agent picks
  them and their props are sent as literal values.

Each component gets its own surface: createSurface -> updateComponents (-> updateDataModel).
The browser's CopilotKit A2UI renderer draws them with OUR catalog (frontend/lib/catalog).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from copilotkit import a2ui

from mira.agent.state import UIComponent
from mira.ui.catalog import CATALOG_ID, FIXED_SCHEMA, validate_component

SCHEMA_DIR = Path(__file__).parent / "schemas"


@lru_cache(maxsize=None)
def fixed_layout(component: str) -> list[dict[str, Any]]:
    return a2ui.load_schema(SCHEMA_DIR / f"{component}.json")


def surface_ops(surface_id: str, component: UIComponent) -> list[dict[str, Any]]:
    """Operations for one component, validated against the catalog first."""
    props = validate_component(component.component, component.props)
    ops = [a2ui.create_surface(surface_id, catalog_id=CATALOG_ID)]
    if component.component in FIXED_SCHEMA:
        layout = json.loads(json.dumps(fixed_layout(component.component)))  # copy
        layout[0]["accent"] = props["accent"]
        data = {k: v for k, v in props.items() if k != "accent"}
        ops.append(a2ui.update_components(surface_id, layout))
        ops.append(a2ui.update_data_model(surface_id, data))
    else:
        ops.append(a2ui.update_components(surface_id, [{"id": "root", "component": component.component, **props}]))
    return ops


def build_operations(components: list[UIComponent], turn_id: str) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for i, c in enumerate(components):
        ops += surface_ops(f"mira-{turn_id}-{i}-{c.component.lower()}", c)
    return ops


def validate_operations(ops: list[dict[str, Any]]) -> list[str]:
    """Server-side check of a full A2UI message list (used by tests and evals)."""
    errors: list[str] = []
    for op in ops:
        if op.get("version") != "v0.9":
            errors.append(f"bad version {op.get('version')!r}")
        kinds = [k for k in op if k != "version"]
        if len(kinds) != 1 or kinds[0] not in ("createSurface", "updateComponents", "updateDataModel", "deleteSurface"):
            errors.append(f"bad operation keys {kinds}")
            continue
        body = op[kinds[0]]
        if kinds[0] == "createSurface" and body.get("catalogId") != CATALOG_ID:
            errors.append(f"unknown catalog {body.get('catalogId')!r}")
        if kinds[0] == "updateComponents":
            for comp in body.get("components", []):
                name = comp.get("component")
                if name not in FIXED_SCHEMA:
                    props = {k: v for k, v in comp.items() if k not in ("id", "component")}
                    try:
                        validate_component(name, props)
                    except Exception as exc:
                        errors.append(str(exc))
        if kinds[0] == "updateDataModel":
            surface = body.get("surfaceId", "")
            name = next((n for n in FIXED_SCHEMA if surface.endswith(n.lower())), None)
            if name:
                try:
                    validate_component(name, {**body.get("value", {}), "accent": "teal"})
                except Exception as exc:
                    errors.append(str(exc))
    return errors

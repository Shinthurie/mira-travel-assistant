"""FastAPI backend: the AG-UI agent endpoint plus REST endpoints for booking, visitors and staff.

Permissions are enforced HERE in code (CLAUDE.md rule 9), never by the model:
- traveller endpoints need no login and only ever return traveller-safe data;
- /api/staff/* needs a staff or approver token; publishing content needs the approver role.

Run: ``uvicorn mira.api:app --port 8123`` (``python scripts/dev.py`` does this for you).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from decimal import Decimal
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mira import config
from mira.agent.context import get_context
from mira.agent.graph import get_graph
from mira.db import User
from mira.tracing import TRACE_DIR

log = logging.getLogger("mira.api")
app = FastAPI(title="Mira API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------------------
# AG-UI agent endpoint (LangGraph -> AG-UI events -> CopilotKit runtime -> browser)
# ---------------------------------------------------------------------------
try:
    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from copilotkit import LangGraphAGUIAgent

    add_langgraph_fastapi_endpoint(app, LangGraphAGUIAgent(
        name="mira", description="Mira, the Ceylon Compass Holidays booking assistant", graph=get_graph()),
        path="/agent")
except Exception as exc:  # pragma: no cover - keeps REST usable if the AG-UI SDK breaks
    log.error("AG-UI endpoint not mounted: %s", exc)


@app.exception_handler(Exception)
async def friendly_errors(request: Request, exc: Exception) -> JSONResponse:
    """Never an error page: a friendly message and a way forward."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=200, content={
        "ok": False, "message": "Something went wrong on our side. Your details are safe.",
        "next_steps": ["Try again in a minute", "Or ask Mira to pass your request to a specialist"]})


@app.get("/health")
def health() -> dict:
    ctx = get_context()
    return {"status": "ok", "today": ctx.today.isoformat(), "llm": getattr(ctx.llm, "model", None) or "offline-rules",
            "langfuse": ctx.tracer.enabled}


@app.get("/api/brand")
def brand() -> dict:
    """The brand pack, read from the dataset (the frontend turns it into CSS variables)."""
    return json.loads(config.BRAND_PACK_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Visitors (requirement 2): consent first, "forget me" any time
# ---------------------------------------------------------------------------


class VisitorIn(BaseModel):
    visitor_id: str = Field(min_length=8, max_length=64)


@app.post("/api/visitor/consent")
def visitor_consent(body: VisitorIn) -> dict:
    get_context().store.give_consent(body.visitor_id)
    return {"ok": True, "consent": True}


@app.post("/api/visitor/forget")
def visitor_forget(body: VisitorIn) -> dict:
    get_context().store.forget(body.visitor_id)
    return {"ok": True, "consent": False}


@app.get("/api/visitor/{visitor_id}")
def visitor_status(visitor_id: str) -> dict:
    ctx = get_context()
    v = ctx.store.get_visitor(visitor_id)
    if v is None or v.consent_given_at is None:
        return {"consent": False, "returning": False}
    last = ctx.store.get_quote(v.last_quote_id) if v.last_quote_id else None
    doc = ctx.catalog.content.get(last.tour_id) if last else None
    return {"consent": True, "returning": last is not None,
            "last_tour": doc.title if doc else None}  # no price here: Mira re-prices it fresh


# ---------------------------------------------------------------------------
# Mock booking + payment (forced-failure switch for the demo)
# ---------------------------------------------------------------------------


class BookingIn(BaseModel):
    quote_ref: str
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    notes: Optional[str] = Field(None, max_length=1000)
    consent: bool = False
    force_fail: bool = False


@app.post("/api/booking")
def book(body: BookingIn) -> dict:
    ctx = get_context()
    from sqlmodel import select
    from mira.db import QuoteRecord
    with ctx.store.session() as s:
        quote = s.exec(select(QuoteRecord).where(QuoteRecord.ref == body.quote_ref)).first()
    if quote is None:
        return {"ok": False, "message": "I couldn't find that quote. Ask Mira for a fresh price and try again.",
                "next_steps": ["Ask Mira to re-price your trip"]}
    if not body.consent:
        return {"ok": False, "message": "Please tick the box so we can use your details for this booking.",
                "next_steps": ["Tick the consent box and send again"]}
    fail = body.force_fail or os.environ.get("MOCK_PAYMENT_FAIL", "false").lower() == "true"
    contact = {"name": body.name, "email": body.email, "phone": body.phone, "notes": body.notes}
    enquiry = ctx.store.create_enquiry("booking", f"Booking request for quote {quote.ref} ({quote.tour_id})",
                                       quote.visitor_id, quote.thread_id, quote.tour_id, quote.id, contact,
                                       quote.trace_id, quote.trace_url)
    if fail:
        ctx.store.add_note(enquiry.id, "system", "Mock payment failed; customer asked to retry or be called back.")
        return {"ok": False, "enquiry_ref": enquiry.ref,
                "message": "Your payment didn't go through, and you haven't been charged. We've saved your booking "
                           "request, so nothing is lost.",
                "next_steps": ["Try the payment again", "Or wait for a specialist to contact you to finish the booking"]}
    ctx.store.update_enquiry(enquiry.id, status="contacted")
    ctx.store.add_note(enquiry.id, "system", "Mock payment succeeded.")
    return {"ok": True, "enquiry_ref": enquiry.ref, "summary": f"Booking request {enquiry.ref} received",
            "next_steps": ["We email your confirmation", f"Your deposit of USD {Decimal(quote.deposit_usd):,.0f} is taken by our secure payment link"]}


# ---------------------------------------------------------------------------
# Staff auth (HMAC-signed bearer tokens; roles checked in code)
# ---------------------------------------------------------------------------

SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
TOKEN_TTL = 8 * 3600


def make_token(user: User) -> str:
    payload = f"{user.username}|{user.role}|{int(time.time()) + TOKEN_TTL}"
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def read_token(token: str) -> User | None:
    try:
        username, role, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split("|")
    except Exception:
        return None
    expected = hmac.new(SECRET.encode(), f"{username}|{role}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected) or int(exp) < time.time():
        return None
    return User(username=username, role=role, password_hash="")


def current_user(authorization: str = Header(default="")) -> User:
    user = read_token(authorization.removeprefix("Bearer ").strip()) if authorization else None
    if user is None or user.role not in ("staff", "approver"):
        raise HTTPException(status_code=401, detail="Staff login required")
    return user


def approver(user: User = Depends(current_user)) -> User:
    if user.role != "approver":
        raise HTTPException(status_code=403, detail="Only an approver can do this")
    return user


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/staff/login")
def login(body: LoginIn) -> dict:
    user = get_context().store.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return {"token": make_token(user), "username": user.username, "role": user.role}


@app.get("/api/staff/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"username": user.username, "role": user.role}


def _quote_internal(quote_id: int | None) -> dict | None:
    if not quote_id:
        return None
    rec = get_context().store.get_quote(quote_id)
    if rec is None:
        return None
    internal = json.loads(rec.internal_json)
    return {"ref": rec.ref, "tour_id": rec.tour_id, "start_date": rec.start_date,
            "cost_usd": str(round(Decimal(internal["cost_usd"]), 2)), "price_usd": internal["price_usd"],
            "gross_profit_usd": str(round(Decimal(internal["gross_profit_usd"]), 2)),
            "gross_profit_pct": internal["gross_profit_pct"], "deposit_usd": internal["deposit_usd"],
            "cost_lines": internal["cost_lines"], "hotel_nights": internal["hotel_nights"],
            "settings_overridden": internal.get("settings_overridden", [])}


@app.get("/api/staff/enquiries")
def list_enquiries(user: User = Depends(current_user)) -> list[dict]:
    store = get_context().store
    out = []
    for e in store.list_enquiries():
        out.append({
            "id": e.id, "ref": e.ref, "kind": e.kind, "summary": e.summary, "tour_id": e.tour_id, "status": e.status,
            "created_at": e.created_at.isoformat(), "trace_id": e.trace_id, "trace_url": e.trace_url,
            "contact": json.loads(e.contact_json or "{}"), "quote": _quote_internal(e.quote_id),
            "flags": [{"ref": f.ref, "reason": f.reason, "detail": f.detail, "severity": f.severity}
                      for f in store.flags_for_enquiry(e.id)],
            "notes": [{"author": n.author, "text": n.text, "created_at": n.created_at.isoformat()}
                      for n in store.notes_for(e.id)],
        })
    return out


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/staff/enquiries/{enquiry_id}/notes")
def add_note(enquiry_id: int, body: NoteIn, user: User = Depends(current_user)) -> dict:
    store = get_context().store
    if store.get_enquiry(enquiry_id) is None:
        raise HTTPException(404, "No such enquiry")
    note = store.add_note(enquiry_id, user.username, body.text)
    return {"ok": True, "id": note.id}


class StatusIn(BaseModel):
    status: str = Field(pattern="^(new|contacted|won|lost)$")


@app.patch("/api/staff/enquiries/{enquiry_id}")
def set_status(enquiry_id: int, body: StatusIn, user: User = Depends(current_user)) -> dict:
    row = get_context().store.update_enquiry(enquiry_id, status=body.status)
    if row is None:
        raise HTTPException(404, "No such enquiry")
    return {"ok": True, "status": row.status}


@app.get("/api/staff/flags")
def list_flags(user: User = Depends(current_user)) -> list[dict]:
    return [{"ref": f.ref, "source": f.source, "reason": f.reason, "detail": f.detail, "tour_id": f.tour_id,
             "severity": f.severity, "enquiry_id": f.enquiry_id, "trace_url": f.trace_url,
             "created_at": f.created_at.isoformat()} for f in get_context().store.list_flags()]


@app.get("/api/staff/traces/{trace_id}")
def get_trace(trace_id: str, user: User = Depends(current_user)) -> dict:
    """Local JSON trace (already PII-redacted). With Langfuse configured, staff use the Langfuse URL."""
    if not trace_id.isalnum():
        raise HTTPException(400, "Bad trace id")
    path = TRACE_DIR / f"{trace_id}.json"
    if not path.exists():
        raise HTTPException(404, "Trace not found locally")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Content workflow (requirement 8): staff create drafts, ONLY approvers publish
# ---------------------------------------------------------------------------


class DraftIn(BaseModel):
    command: str = Field(min_length=5, max_length=300)


def _draft_out(d) -> dict:
    return {"id": d.id, "doc_id": d.doc_id, "title": d.title, "status": d.status, "command": d.command,
            "markdown": d.markdown, "sources": json.loads(d.sources_json), "created_by": d.created_by,
            "approved_by": d.approved_by}


@app.post("/api/staff/content/drafts")
def create_draft(body: DraftIn, user: User = Depends(current_user)) -> dict:
    from mira.content_agent import create_draft as make
    ctx = get_context()
    draft = make(body.command, user, ctx.catalog.content, ctx.retriever, ctx.store, ctx.llm, ctx.today)
    return _draft_out(draft)


@app.get("/api/staff/content/drafts")
def list_drafts(user: User = Depends(current_user)) -> list[dict]:
    return [_draft_out(d) for d in get_context().store.list_drafts()]


@app.post("/api/staff/content/drafts/{draft_id}/publish")
def publish(draft_id: int, user: User = Depends(approver)) -> dict:
    from mira.content_agent import publish_draft
    ctx = get_context()
    draft = publish_draft(draft_id, user, ctx.store)
    ctx.rebuild_content()
    return _draft_out(draft)


@app.post("/api/staff/content/drafts/{draft_id}/reject")
def reject(draft_id: int, user: User = Depends(approver)) -> dict:
    from mira.content_agent import reject_draft
    return _draft_out(reject_draft(draft_id, user, get_context().store))


def _ensure_http_errors_stay_http() -> None:
    """HTTPException must not be swallowed by the friendly handler (401/403/404 are real answers)."""
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)


_ensure_http_errors_stay_http()

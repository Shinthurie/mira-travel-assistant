"""SQLite storage (SQLModel): visitors, quotes, enquiries, notes, flags, users, content drafts.

Quotes store BOTH views: ``internal_json`` (cost, price, GP%: staff only) and ``traveller_json``.
Contact details live only here (never in traces). ``Store`` is the one place that writes rows,
so the agent, the staff API, the MCP server and the evals all use the same code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select

from mira import config  # noqa: F401  (loads .env)


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class Visitor(SQLModel, table=True):
    id: str = Field(primary_key=True)
    consent_given_at: Optional[datetime] = None
    known_slots_json: str = "{}"           # what Mira already knows (travellers, interests...)
    last_quote_id: Optional[int] = None
    forgotten_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)


class QuoteRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str = Field(index=True)
    visitor_id: Optional[str] = Field(default=None, index=True)
    thread_id: Optional[str] = None
    tour_id: str
    start_date: str
    adults: int
    child_ages_json: str = "[]"
    price_usd: str
    deposit_usd: str
    internal_json: str                     # QuoteInternal (cost, margin, GP) - staff only
    traveller_json: str                    # QuoteForTraveller
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    created_at: datetime = Field(default_factory=now)


class Enquiry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str = Field(index=True)
    visitor_id: Optional[str] = Field(default=None, index=True)
    thread_id: Optional[str] = None
    kind: str                              # quote | no_quote | custom | booking | question
    summary: str
    tour_id: Optional[str] = None
    quote_id: Optional[int] = None
    contact_json: str = "{}"               # local DB only, never traced
    status: str = "new"                    # new | contacted | won | lost
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class EnquiryNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    enquiry_id: int = Field(index=True)
    author: str
    text: str
    created_at: datetime = Field(default_factory=now)


class Flag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str = Field(index=True)
    enquiry_id: Optional[int] = Field(default=None, index=True)
    thread_id: Optional[str] = None
    source: str                            # pricing | guard | data_decision | content
    reason: str                            # NoQuoteReason value, "invented_price", ...
    detail: str
    tour_id: Optional[str] = None
    severity: str = "warning"              # info | warning | blocking
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    resolved: bool = False
    created_at: datetime = Field(default_factory=now)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: str                              # staff | approver


class ContentDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True)        # e.g. "T17"
    slug: str
    title: str
    markdown: str                          # full file: front matter + body
    command: str                           # the staff command that produced it
    sources_json: str = "[]"               # passage ids the draft was built from
    status: str = "draft"                  # draft | published | rejected
    created_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)


# ---------------------------------------------------------------------------
# Passwords (PBKDF2, standard library only)
# ---------------------------------------------------------------------------


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    salt, _, digest = stored.partition("$")
    return hmac.compare_digest(hash_password(password, salt), stored)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _dumps(value: Any) -> str:
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json()
    return json.dumps(value, default=str)


class Store:
    """All database reads and writes."""

    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL", "sqlite:///mira.db")
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and ":memory:" not in url:
            path = url.removeprefix("sqlite:///")
            if not os.path.isabs(path):
                url = f"sqlite:///{(config.REPO_ROOT / path).as_posix()}"
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        SQLModel.metadata.create_all(self.engine)
        self.seed_users()

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    # -- users ----------------------------------------------------------------
    def seed_users(self) -> None:
        """Demo users from env (no real personal data). Passwords default to demo values."""
        demo = [("staff", os.environ.get("STAFF_PASSWORD", "staff-demo"), "staff"),
                ("approver", os.environ.get("APPROVER_PASSWORD", "approver-demo"), "approver")]
        with self.session() as s:
            for username, password, role in demo:
                if not s.exec(select(User).where(User.username == username)).first():
                    s.add(User(username=username, password_hash=hash_password(password), role=role))
            s.commit()

    def authenticate(self, username: str, password: str) -> User | None:
        with self.session() as s:
            user = s.exec(select(User).where(User.username == username)).first()
            return user if user and check_password(password, user.password_hash) else None

    # -- visitors -------------------------------------------------------------
    def get_visitor(self, visitor_id: str) -> Visitor | None:
        with self.session() as s:
            v = s.get(Visitor, visitor_id)
            return None if v is None or v.forgotten_at else v

    def give_consent(self, visitor_id: str) -> Visitor:
        with self.session() as s:
            v = s.get(Visitor, visitor_id) or Visitor(id=visitor_id)
            v.consent_given_at, v.forgotten_at = now(), None
            s.add(v)
            s.commit()
            return v

    def remember(self, visitor_id: str, known_slots: dict[str, Any], last_quote_id: int | None = None) -> None:
        """Store what Mira knows, ONLY if the visitor consented."""
        with self.session() as s:
            v = s.get(Visitor, visitor_id)
            if v is None or v.consent_given_at is None or v.forgotten_at:
                return
            v.known_slots_json = json.dumps(known_slots, default=str)
            if last_quote_id is not None:
                v.last_quote_id = last_quote_id
            s.add(v)
            s.commit()

    def forget(self, visitor_id: str) -> None:
        """'Forget me': wipe stored knowledge and detach quotes/enquiries from the visitor."""
        with self.session() as s:
            v = s.get(Visitor, visitor_id)
            if v is not None:
                v.known_slots_json, v.last_quote_id, v.consent_given_at, v.forgotten_at = "{}", None, None, now()
                s.add(v)
            for model in (QuoteRecord, Enquiry):
                for row in s.exec(select(model).where(model.visitor_id == visitor_id)).all():
                    row.visitor_id = None
                    if isinstance(row, Enquiry):
                        row.contact_json = "{}"
                    s.add(row)
            s.commit()

    # -- quotes, enquiries, flags --------------------------------------------
    def save_quote(self, quote, visitor_id: str | None, thread_id: str | None,
                   trace_id: str | None, trace_url: str | None) -> QuoteRecord:
        internal, traveller = quote.internal, quote.traveller
        row = QuoteRecord(
            ref=new_ref("Q"), visitor_id=visitor_id, thread_id=thread_id, tour_id=internal.tour_id,
            start_date=internal.request.start_date.isoformat(), adults=internal.request.adults,
            child_ages_json=json.dumps(list(internal.request.child_ages)), price_usd=str(traveller.price_usd),
            deposit_usd=str(traveller.deposit_usd), internal_json=_dumps(internal), traveller_json=_dumps(traveller),
            trace_id=trace_id, trace_url=trace_url)
        with self.session() as s:
            s.add(row)
            s.commit()
            s.refresh(row)
        return row

    def create_enquiry(self, kind: str, summary: str, visitor_id: str | None = None, thread_id: str | None = None,
                       tour_id: str | None = None, quote_id: int | None = None, contact: dict | None = None,
                       trace_id: str | None = None, trace_url: str | None = None) -> Enquiry:
        row = Enquiry(ref=new_ref("E"), kind=kind, summary=summary, visitor_id=visitor_id, thread_id=thread_id,
                      tour_id=tour_id, quote_id=quote_id, contact_json=json.dumps(contact or {}),
                      trace_id=trace_id, trace_url=trace_url)
        with self.session() as s:
            s.add(row)
            s.commit()
            s.refresh(row)
        return row

    def raise_flag(self, source: str, reason: str, detail: str, tour_id: str | None = None,
                   enquiry_id: int | None = None, thread_id: str | None = None, severity: str = "warning",
                   trace_id: str | None = None, trace_url: str | None = None) -> Flag:
        row = Flag(ref=new_ref("F"), source=source, reason=reason, detail=detail, tour_id=tour_id,
                   enquiry_id=enquiry_id, thread_id=thread_id, severity=severity, trace_id=trace_id,
                   trace_url=trace_url)
        with self.session() as s:
            s.add(row)
            s.commit()
            s.refresh(row)
        return row

    def list_flags(self, thread_id: str | None = None) -> list[Flag]:
        with self.session() as s:
            q = select(Flag).order_by(Flag.id.desc())
            if thread_id:
                q = q.where(Flag.thread_id == thread_id)
            return list(s.exec(q).all())

    def list_enquiries(self) -> list[Enquiry]:
        with self.session() as s:
            return list(s.exec(select(Enquiry).order_by(Enquiry.id.desc())).all())

    def get_enquiry(self, enquiry_id: int) -> Enquiry | None:
        with self.session() as s:
            return s.get(Enquiry, enquiry_id)

    def get_quote(self, quote_id: int) -> QuoteRecord | None:
        with self.session() as s:
            return s.get(QuoteRecord, quote_id)

    def update_enquiry(self, enquiry_id: int, status: str | None = None, contact: dict | None = None) -> Enquiry | None:
        with self.session() as s:
            row = s.get(Enquiry, enquiry_id)
            if row is None:
                return None
            if status is not None:
                row.status = status
            if contact is not None:
                row.contact_json = json.dumps(contact)
            row.updated_at = now()
            s.add(row)
            s.commit()
            s.refresh(row)
            return row

    def add_note(self, enquiry_id: int, author: str, text: str) -> EnquiryNote:
        note = EnquiryNote(enquiry_id=enquiry_id, author=author, text=text)
        with self.session() as s:
            s.add(note)
            s.commit()
            s.refresh(note)
        return note

    def notes_for(self, enquiry_id: int) -> list[EnquiryNote]:
        with self.session() as s:
            return list(s.exec(select(EnquiryNote).where(EnquiryNote.enquiry_id == enquiry_id)
                               .order_by(EnquiryNote.id)).all())

    def flags_for_enquiry(self, enquiry_id: int) -> list[Flag]:
        with self.session() as s:
            return list(s.exec(select(Flag).where(Flag.enquiry_id == enquiry_id)).all())

    # -- content drafts -------------------------------------------------------
    def save_draft(self, draft: ContentDraft) -> ContentDraft:
        with self.session() as s:
            s.add(draft)
            s.commit()
            s.refresh(draft)
        return draft

    def get_draft(self, draft_id: int) -> ContentDraft | None:
        with self.session() as s:
            return s.get(ContentDraft, draft_id)

    def list_drafts(self, status: str | None = None) -> list[ContentDraft]:
        with self.session() as s:
            q = select(ContentDraft).order_by(ContentDraft.id.desc())
            if status:
                q = q.where(ContentDraft.status == status)
            return list(s.exec(q).all())

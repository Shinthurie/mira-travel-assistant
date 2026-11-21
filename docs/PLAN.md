# Mira: build plan

Source of truth for rules: `CLAUDE.md`. Data findings: `docs/DATA_AUDIT.md`. Final technology choices are justified in `docs/DECISIONS.md` as they are made.

## 1. Data issues
See `docs/DATA_AUDIT.md`. It confirms all 22 items from CLAUDE.md section 6 and adds 20 new ones (B1–B20). The ones that most affect design:
- **B1**: rates and FX end 31 Oct 2027 → `beyond_rate_validity`.
- **B4 / A12**: T14 has valid rates but is a stale promo → explicit decision file.
- **B6**: two "Cultural Triangle" tours.
- **B8**: whale-season contradiction between pages.

## 2. Architecture

```
Browser (Next.js + CopilotKit A2UI renderer, our catalog, zod validation)
   │  AG-UI event stream (HTTP/SSE) via the CopilotKit runtime route
FastAPI ── ag_ui_langgraph.add_langgraph_fastapi_endpoint(LangGraphAGUIAgent(graph))
   │
LangGraph StateGraph (typed MiraState)
   intake ─► discovery ─┐
          ├► retrieval ─┼─► compose_ui ─► guard ─► persist ─► END
          └► pricing ───┘
   (pricing tool → mira.pricing engine; retrieval → BM25 over published content)
SQLite (SQLModel) · Langfuse (no-op without keys)
```

Layers, for the demo: **LangGraph** = what the agent does. **AG-UI** = how agent and UI talk (event stream). **A2UI** = what gets drawn (declarative JSON from our fixed catalog).

### 2.1 Graph nodes
| Node | LLM? | Job |
|---|---|---|
| `intake` | yes (structured output, temperature 0) | Intent (`quote`, `info`, `plan_custom`, `enquiry`, `book`, `off_topic`, `smalltalk`, `injection`) and slot extraction (tour, start date, adults, child ages). Merges slots into state and never overwrites known slots with nulls. |
| `discovery` | yes (wording only) | Decides the **one** next question from the missing slots in a fixed priority order (trip type → travellers → date). Counts questions; after 3 it must show something (closest tours). Never asks for a known slot (code check). |
| `retrieval` | no | BM25 over **published, comment-stripped, supersession-annotated** passages. Returns passages with `doc_id`, `title` and `section`. |
| `answer` | yes | Grounded answer from the passages only, wrapped as `<untrusted_content>`. If nothing supports the answer, says so and offers an enquiry. Citations are attached by code from the passage ids, never by the model. |
| `pricing` | no | Calls `mira.pricing.quote()` → `QuoteInternal` + `QuoteForTraveller`, or `NoQuote(reason)` → staff flag. |
| `compose_ui` | partly | Fixed-schema surfaces are built by code from engine output. Dynamic surfaces (TourCard, ItineraryDay, TravellerPicker, SourceCitation) are chosen by the agent but filled from content data. |
| `guard` | no | Money scan (USD, US$, $, LKR, Rs, EUR, €, £, "per person", "pp") of text **and** UI payloads. Every amount must be in the conversation's allowed set (traveller-facing quote values only). Otherwise: redact → "a specialist will confirm" → staff flag → trace event. Also checks for PII in outgoing traces and validates A2UI payloads against the catalog (Pydantic). |
| `persist` | no | Saves quote, enquiry, flag and trace link. |
| `content_agent` (separate graph) | yes | Requirement 8: creates a draft from existing content only. Publishing is an API endpoint with a role check. |

### 2.2 Typed shared state (Pydantic)
```python
class Travellers(BaseModel):
    adults: int | None = None
    child_ages: list[int] = []          # ages <2 = infants, 2–11 children, ≥12 → adults (engine decides)

class MiraState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages]
    visitor_id: str | None = None
    stage: Literal["greeting","discovery","informing","quoted","handoff","booking","done"] = "greeting"
    intent: Intent | None = None
    trip_type: Literal["day_tour","multi_day","custom"] | None = None
    traveller_type: Literal["solo","couple","family","group"] | None = None
    travellers: Travellers = Travellers()
    start_date: date | None = None
    tour_id: str | None = None
    questions_asked: int = 0
    retrieved: list[Passage] = []
    quotes: list[QuoteForTraveller] = []      # traveller-safe only; internal quotes live in the DB
    allowed_amounts: set[Decimal] = set()     # filled by the pricing node; used by the guard
    flags: list[FlagRef] = []
    ui: list[A2UIMessage] = []
    trace_id: str | None = None
```

### 2.3 UI catalog (A2UI)
Every component has exactly one `accent` prop from `teal | leaf | sun | sky | coral` (brand rule: one accent colour per card).

| Component | Surface | Props (Pydantic and zod) | Data source |
|---|---|---|---|
| **PriceBreakdown** | fixed | `tour_id, tour_title, start_date, travellers_summary, price_usd, deposit_usd, balance_usd, balance_due_date?, pay_in_full: bool, inclusions[], quote_ref, accent` | `QuoteForTraveller` only. It has no cost, margin or GP fields. |
| **BookingForm** | fixed | `quote_ref, price_usd, deposit_usd, fields: [name, email, phone, notes], consent_text, accent` | engine and quote |
| **SpecialistHandoff** | fixed | `reason_text, tour_title?, flag_ref, enquiry_cta, accent` | `NoQuote` + flag |
| **EnquiryConfirmation** | fixed | `enquiry_ref, summary, next_steps[], accent` | DB |
| **TourCard** | dynamic | `tour_id, title, category, duration, destinations[], summary, priceable: bool, image: "placeholder", accent` (**no price field**) | content |
| **ItineraryDay** | dynamic | `tour_id, day_number, title, description, meals[], accommodation?, entrance[], source_ref, accent` | content |
| **TravellerPicker** | dynamic | `adults_default, child_ages_default[], max_group: 20, prompt, accent` | state |
| **SourceCitation** | dynamic | `sources: [{doc_id, title, section}], accent` | retrieval |

Validation: Pydantic models on the server (before AG-UI emits) and zod schemas on the client, generated from one JSON Schema per component (`mira/ui/catalog/*.json`), so the two can't drift. An invalid payload falls back to text, and the event is logged to the trace.

### 2.4 A2UI wiring (from the current CopilotKit docs, checked 21 Nov 2026)
- Python: `ag-ui-langgraph` (`add_langgraph_fastapi_endpoint`) + `copilotkit` (`LangGraphAGUIAgent`, `CopilotKitMiddleware`, the `a2ui` helpers `create_surface / update_components / update_data_model / render`). The graph is compiled with `MemorySaver`.
- **Fixed schema**: a pricing tool returns `a2ui.render(operations=[...])` with our JSON component tree and a data model built from `QuoteForTraveller`. The runtime runs with `injectA2UITool: false`.
- **Dynamic schema**: `get_a2ui_tools(...)` gives a `generate_a2ui` tool that composes from our catalog id.
- Next.js: `@copilotkit/react-core` (v2 `CopilotKit` provider with `a2ui={{ catalog }}`), `@copilotkit/runtime` (`CopilotRuntime` + `HttpAgent` from `@ag-ui/client` → FastAPI), `@copilotkit/a2ui-renderer` (`createCatalog(definitions, renderers, {catalogId})`), `zod`.
- **Open question for Phase 2.5**: the A2UI spec is now v1.0 (`createSurface`, `updateComponents`, `updateDataModel`; `@path` bindings), but CopilotKit's page says its `a2ui` prop uses **v0.9**. We pin one renderer version and test against the wire format it actually emits. If this is still blocked after about 3 hours → fall back to AG-UI + CopilotKit generative UI (recorded in DECISIONS.md).

### 2.5 Database (SQLite + SQLModel)
| Table | Key columns |
|---|---|
| `visitor` | id (uuid cookie), consent_given_at, last_quote_id, known_slots_json, forgotten_at |
| `quote` | id, ref, visitor_id, tour_id, start_date, adults, child_ages_json, **internal_json** (cost, price, GP%, breakdown), **traveller_json**, settings_snapshot_json, trace_id, trace_url, created_at |
| `enquiry` | id, ref, visitor_id, quote_id?, kind (`quote / no_quote / custom / booking`), summary, contact_json (local DB only, never traced), status (`new / contacted / won / lost`), created_at |
| `enquiry_note` | id, enquiry_id, author_user_id, text, created_at |
| `flag` | id, enquiry_id?, reason (enum), detail, tour_id?, severity, source (`pricing / guard / data_decision`), trace_id, resolved |
| `user` | id, email, password_hash, role (`staff / approver`) |
| `content_draft` | id, slug, front_matter_json, body, created_by, status (`draft / published / rejected`), approved_by, approved_at |

Drafts are stored in the DB plus `generated_content/`, **never** in the dataset folder.

## 3. Folder structure and startup
```
mira/                 Python package (backend)
  config.py           env: TODAY, paths, override file
  data/               workbook.py, content.py, decisions.py, models.py   ← Phase 1
  pricing/            engine.py, schemas.py, __main__.py (CLI)          ← Phase 2
  retrieval/          index.py                                          ← Phase 3
  agent/              state.py, nodes/, graph.py, guard.py              ← Phase 4
  ui/                 catalog/ (JSON Schemas), a2ui.py                  ← 2.5 / 5
  db/                 models.py, session.py                             ← 4 / 8
  tracing.py          Langfuse wrapper with no-op + PII redaction       ← 2.5 / 6
  api.py              FastAPI app                                       ← 2.5
  chat.py             CLI chat                                          ← 4
frontend/             Next.js app                                       ← 2.5 / 5
evals/                cases/, run.py, judge.py, human_labels_template.jsonl
config/               data_decisions.yaml, pricing_overrides.example.json
scripts/dev.py        one command: backend + frontend
tests/                pytest (no LLM calls)
reports/              eval_report.md/.json, history/
docs/                 brief/, PLAN, DATA_AUDIT, DECISIONS, PROGRESS, AI_USAGE, FIXED_PROBLEM
```
**One command:** `python scripts/dev.py`. It checks Python and Node, installs frontend deps on first run, starts uvicorn (port 8123) and `next dev` (port 3000) as subprocesses, forwards Ctrl+C, and works on Windows (no `make`, no Docker).

### Pinned versions (latest on PyPI/npm, 21 Nov 2026; each is added when its phase installs and tests it)
Python 3.11: `pydantic 2.14.4`, `openpyxl 3.1.5`, `PyYAML 6.0.4`, `python-dotenv 1.2.4`, `pytest 9.2.0` *(Phase 1)*; `fastapi 0.165.0`, `uvicorn 0.54.0`, `langgraph 1.2.24`, `langchain-core 1.8.4`, `ag-ui-langgraph 0.0.47`, `ag-ui-protocol 1.0.0`, `copilotkit 0.1.97`, `langfuse 5.2.0`, `sqlmodel 0.0.50`, `httpx 0.28.1`, `rank-bm25 0.2.2`, plus the LLM provider SDK (e.g. `langchain-google-genai 4.5.2`).
Node: `next 16.4.6`, `react 19.3.1`, `@copilotkit/react-core 1.90.0`, `@copilotkit/runtime 1.90.0`, `@copilotkit/a2ui-renderer 1.90.0`, `@ag-ui/client 1.0.2`, `zod 4.6.7`.

## 4. Evaluation plan (target 48 cases, 7 multi-turn)
| Group | Cases | Requirements | Checks |
|---|---|---|---|
| Seeds S01–S17 (unchanged) | 17 | 1, 4, 5, 6, safety | code (quote and flag types) + judge (behaviour) |
| Pricing extras: infant, 12-year-old = adult, 3 vs 4 travellers (car/van), 8 vs 9, 21 → Sales, mid-tour season change, H10 USD tour (T13), T07 in Dec vs Jan (H03 conflict), within-30-days deposit, past date, after 31 Oct 2027 | 11 | 5, 6 | code: consistency + golden |
| No-price: T14 stale, T15 Jaffna draft quote, T16 old Cultural Triangle, T11 Feb 2028, custom 10-day planner | 5 | 6, 1 | code: no money + flag exists |
| Guard red team: per person, convert to EUR/LKR, discount, teaser "from USD 85?", other tour in passing, "what if we add a child" (multi-turn re-run), Mirissa-page injection, testimonial "20% off" | 8 | 5, safety | code: every amount ∈ engine set |
| Grounding: whale season contradiction, shared boat, T16 massage, Little Adam's Peak, cost/margin leak ("what's your margin?") | 5 | 4, 5 | judge + code (no cost or GP terms) |
| Discovery and multi-turn: planner family of 4 (Kandy, Ella, south coast), ≤3 questions, no re-asking, change travellers mid-flow | 4 | 1 | code (question count, slots) + judge |
| UI payloads: every turn's A2UI validated; PriceBreakdown has no cost fields | all turns | 3 | code |
| PII: name/email/phone in message → not in trace payloads | 2 | tracing | code |
| Extended (later): returning visitor, staff page access, draft never cited, published draft answerable without price | 4+ | 2, 7, 8 | code + judge |

- **Code checks**: money amounts vs the engine (consistency), the engine vs expected (golden), flag rows exist, no draft doc ids in citations, no `cost / margin / GP` keys or words in traveller output, A2UI validity, question count.
- **LLM judge**: a different, stronger model than Mira, temperature 0, a rubric per case, calibrated on 10 cases you label (`evals/human_labels_template.jsonl`; the labels are left empty for you).
- **Repeats**: price and flag cases run 3 times; report the worst case. Latency per turn and time to first quote.

## 5. Build order vs schedule
| When | Phase | Est. |
|---|---|---|
| Sat 21 | 0 plan · **1 skeleton + loaders** | 3 h |
| Sun 22 | 2 pricing engine (perfect) · 2.5 thin A2UI slice · 3 retrieval | 3 h + 4 h + 2 h |
| Mon 23 | 4 agent + guard + flags · 5 full UI · 6 tracing | 5 h + 4 h + 2 h |
| Tue 24 | 7 evals · *you label 10 cases* · 7b fix · 8 enquiries/staff/returning | 4 h + 1 h + 4 h |
| Wed 25 | MCP bonus (1 h, only if green) · 9 content workflow · 10 README/report/video | ~6 h |

## 6. Risks
| Risk | Mitigation |
|---|---|
| A2UI v0.9 vs v1.0 mismatch; young SDK (`copilotkit 0.1.x`, `ag-ui-langgraph 0.0.x`) | Thin slice first (2.5), exact pins, 3-hour cut-off → AG-UI + CopilotKit generative UI fallback |
| An LLM writes a number | Guard on all output plus red-team evals; numbers only from the engine |
| LLM rate limits or free-tier quotas during evals | Run cache, retry with backoff, `--max-cases` |
| Windows-specific issues (encoding, line endings, processes) | `.gitattributes` keeps the dataset bytes exact; UTF-8 everywhere; `dev.py` uses subprocess, not shell scripts |
| Ambiguous decisions (H03, T06) | In `config/data_decisions.yaml` and the audit; easy to change live |
| Time | Cut order from the playbook; never cut evals or the guard |

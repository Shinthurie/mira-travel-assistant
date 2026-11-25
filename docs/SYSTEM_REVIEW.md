# System review: Mira against the brief

Reviewed on 25 Nov 2026 (submission day). Every "met" below points to code or a test that proves it; every gap says why it exists and what it would take. Numbers are from the latest runs: `pytest` **246 passed**, `python -m evals.run` **54/54** (offline mode), `python scripts/adversarial.py` **20 attacks, 0 invented amounts**.

## 1. Verdict in one paragraph

The parts that decide the score are strong and proven: prices only ever come from a deterministic, golden-tested engine; every reply and every UI payload passes a price guard; anything without a valid rate goes to a specialist with a staff flag; content is published-only and injection-resistant; and the evaluation suite measures all of this with code checks rather than opinions. The honest weak spot is that **all eval numbers so far are from offline (rule-based) mode**, because no Gemini key has been added yet. That means the LLM judge, the judge-human agreement and the "real model" behaviour numbers do not exist yet. This is the single most important thing to fix today, and it takes about 15 minutes once the key is in `.env`.

## 2. Core requirements (1, 3, 4, 5, 6)

| # | Requirement | Status | Evidence | Gaps and why |
|---|---|---|---|---|
| 1 | Discover trip type and traveller type in at most 3 questions, then show something useful | **Met** | `discovery` node: one question per turn, never repeats a question, shows tours with the first question (`test_discovery_*`, evals S01, S13, M28, M33) | Wording of questions is fixed text, not LLM-written. Chosen on purpose: deterministic, on-brand and testable. |
| 3 | Agent chooses UI from a fixed catalog (≥5), brand-styled, mobile + desktop | **Met** | 9 components (PriceBreakdown, BookingForm, SpecialistHandoff, EnquiryConfirmation, TourCard, TourShelf, ItineraryDay, TravellerPicker, SourceCitation); A2UI v0.9 over AG-UI with CopilotKit's renderer; screenshots at 375px and desktop in `docs/screenshots/` | Components are chosen by graph logic, not composed freely by the LLM. Deliberate: a model that writes UI JSON can write a price into it. The brief asks the *agent* to choose, and the graph is the agent. |
| 4 | Facts from content only, source shown; if not there, say so and offer an enquiry | **Met** | BM25 over published content only; citations attached by code; `NOT_IN_CONTENT` path; evals S07–S10, S16, S17, M23–M27 | Offline answers are extractive quotes (less conversational). With the key, Gemini writes them in Mira's voice from the same passages. Search has no synonyms (BM25); fine for 95 passages, would need embeddings at scale. |
| 5 | Correct prices from a pricing function; never LLM arithmetic; staff see cost/price/GP%, travellers only price + deposit | **Met** | `mira/pricing/engine.py` (Decimal); golden tests S02, S03, S13, S15, Q-1041/42/44; `QuoteForTraveller` has no cost fields and forbids extras; price guard; staff page shows cost and GP% | None known. Q-1043 "as sent" is wrong in the dataset and a test documents why. |
| 6 | Missing or expired rates: never guess, specialist confirms, staff flag | **Met** | 12 `NoQuote` reasons; flag + enquiry saved for each; evals S04–S06, S11, M04, M06, M09–M11, M37 (10/10) | H03's overlapping rows are treated as a conflict until Sales confirms (judgement call, documented). |

## 3. Extended requirements (2, 7, 8)

| # | Requirement | Status | Evidence | Gaps and why |
|---|---|---|---|---|
| 2 | Returning visitor greeted with last quote, not asked again | **Met** | Consent cookie, `remember`/`forget`, re-prices the last quote fresh; `test_returning_visitor_with_consent`, eval M35 | Only one eval case. Visitor id is a browser cookie (no accounts), which is enough for the brief. |
| 7 | Every quote saved as a private enquiry; staff page with notes and follow-up status | **Met** | `Enquiry`, `EnquiryNote` tables; `/staff` with notes, status, flags, internal cost/GP%, trace link; role checks in the API (`test_api.py`) | Staff auth is a demo (two seeded users, HMAC tokens), not production identity. |
| 8 | Staff command makes an AI draft; only an Approver can publish; then Mira can answer about it | **Met** | `content_agent.py`: draft in DB only, approver-only publish (checked in API and function), written to `generated_content/`, retrieval reloads, no rates → no price; `test_only_approver_can_publish_and_drafts_are_never_used`, evals M36, M37 | Without a key the draft is assembled from destination pages (honest but plain); with the key Gemini writes it from the same sources. |

## 4. Technical requirements

| Requirement | Status | Evidence / gap |
|---|---|---|
| LangGraph with ≥3 nodes and typed shared state | Met | 14 nodes; `MiraSession` / `TurnState` Pydantic models inside the graph state |
| Pricing, permissions, publishing as deterministic code | Met | Engine, FastAPI role dependencies, `publish_draft` role check |
| A2UI over AG-UI, payloads validated before the browser | Met | Pydantic catalog on the server (`compose`), zod on the client; invalid → text fallback + trace event |
| Tracing: one trace per turn with model calls, tools, retrieval, prices; quotes link to trace; no PII | **Partly met** | All implemented and tested (`test_turn_trace_contains_no_pii`). **Langfuse keys not added yet**, so traces are local JSON files that the staff page opens. Langfuse needs only the two keys. |
| Dataset loaded with code, unchanged; configurable today | Met | SHA-256 test of all 37 files; `TODAY` env |
| One command starts everything | Met | `python scripts/dev.py` (creates `.venv` on first run) |
| Unit tests for pricing | Met | `tests/test_pricing.py` (golden + every NoQuote reason + boundaries) |

## 5. Evaluation requirements

| Requirement | Status | Evidence / gap |
|---|---|---|
| ≥40 cases incl. 17 seeds, ≥5 multi-turn, every requirement, off-topic, injection | Met | 54 cases, 8 multi-turn, tagged by requirement |
| Code checks where there is an exact answer | Met | Golden, consistency, invented amounts, flags, UI validity, drafts never used, leaks, PII in traces |
| LLM judge checked against 10 hand-labelled cases, agreement reported | **Not yet** | Judge and `evals/labels.py` are built; **needs the key and your 10 labels**. By design the labels can only come from you. |
| One command, report with pass rates per requirement and trace links | Met | `python -m evals.run` → `reports/eval_report.md` + JSON + history |
| Targets: 100% price accuracy, 0 invented, 100% missing/expired handling | Met (offline) | 18/18 golden, 0 invented, 10/10. **Must be re-run with the LLM** |
| A real problem found and fixed with before/after | Met | `docs/FIXED_PROBLEM.md` (tour mentioned in passing was priced) |

## 6. Bonus

| Bonus | Status | Why |
|---|---|---|
| MCP server (search_tours, get_quote, create_enquiry) on the same rules | Done | `mira/mcp_server.py`, `tests/test_mcp.py` |
| Model routing (small vs large model per turn) | Not done | Cut first in the agreed cut order; with one free-tier provider and no key there was nothing real to evaluate. About 2 hours: route plan_custom/answer turns to the Pro model, everything else to Flash, add an eval column per route. |
| Personalization with consent | Not done | Same cut order. The consent and memory plumbing exists (requirement 2), so it would mostly be a "recommended for you" shelf ranked by stored interests and past quotes. |

## 7. Best practices we did not use, and why

| Practice | Why not (yet) | What it would take |
|---|---|---|
| Embeddings / hybrid search | 95 passages; BM25 is deterministic, needs no key and is explainable live | Add Gemini embeddings and blend scores; re-run grounding evals |
| Free-form LLM tool-calling agent (ReAct) | Rules must live in code; a deterministic router makes every decision testable and traceable | Not recommended for pricing; could be used for small talk only |
| Token streaming of replies | Replies are composed and price-guarded in code *before* sending; streaming would show unguarded text | Stream only after the guard (sentence by sentence) |
| Prompt management/versioning in Langfuse | No Langfuse keys during the build | Move the 3 system prompts to Langfuse prompts |
| Langfuse datasets/experiments for evals | Same | Push the 54 cases as a dataset and log runs as experiments |
| Property-based tests for pricing (Hypothesis) | Time; golden + boundary tests cover the rules | ~1 hour: random travellers/dates, check invariants (multiple of 5, deposit ≤ price) |
| Browser tests in CI (Playwright) | Playwright is used locally for screenshots; CI runs Python only to stay fast and keyless | Add a CI job that starts offline mode and runs 3 browser flows |
| Production auth (OAuth/SSO), rate limiting, CSP headers | Out of scope for a take-home demo | An identity provider, a rate limiter on `/agent`, security headers in Next.js |
| Postgres, migrations, Docker | SQLite and one command meet the brief on Windows without Docker | SQLModel works on Postgres; add Alembic and a Dockerfile |
| Accessibility audit | Labels, focus styles, reduced-motion and contrast were done by hand; no automated audit | Run axe in the Playwright job |
| A2UI v1.0 | The pinned CopilotKit renderer speaks v0.9 | Upgrade when the renderer supports v1.0 |

## 8. How strong is it? (against the marking scheme)

| Area | Points | Assessment |
|---|---|---|
| Working system (core 25, extended 10) | 35 | Strong. Every requirement works end to end in the browser and is tested. Risk: a live question in LLM mode that the rules never met; mitigated by the guard, which cannot be bypassed. |
| Agent design and generative UI | 25 | Strong. Clear node responsibilities, typed state, A2UI fixed and dynamic surfaces, validation on both sides. Found and worked around a real CopilotKit SDK bug (`mira/agui.py`). |
| Evaluation and tracing | 25 | Good, **not yet complete**: the judge, agreement and Langfuse traces need the keys and your labels. The code-check side is unusually thorough (consistency vs golden, worst of 3 runs, history). |
| Code quality and demo | 15 | Good. Small modules with docstrings, 246 tests, CI green, demo script and video plan written. |
| Bonus | +10 | MCP done; routing and personalization not done. |

The hard cap ("an invented or wrong price caps the score at 50") is the main risk in any demo. Here it is defended three times: the model never sees prices, the engine is golden-tested, and the guard removes any amount that isn't an engine value from the same conversation (red-teamed with 20 attacks).

## 9. UI redesign done today (requirement 3 polish)

- Inter is loaded (the brand typeface); all colours, sizes, radii and spacing come from `brand_pack.json`.
- Desktop: a quiet side panel with three plain promises and the consent control; mobile: a compact header.
- Our own welcome screen with four starter questions, instead of the library's generic one.
- Mira's text now appears **before** its cards (needed a fix for a CopilotKit 0.1.97 bug that dropped manually emitted text).
- Cards rebuilt at the brand's 320px maximum with one accent each: a price card with a clear total and a payment timeline; tour cards with an honest "route line" placeholder instead of fake photos; tour suggestions grouped into a swipeable shelf; itinerary days for multi-day tours (this component existed but was never shown before); sources as a compact list.
- Staff page: summary tiles, tabs, readable quote rows with cost and GP%, coloured flag pills, cards on mobile.
- Checked in Chromium at 1366px and 375px: no horizontal scroll, no console errors.

## 10. Checklist for today (in order)

1. Add `GEMINI_API_KEY` to `.env` (https://aistudio.google.com/apikey). Restart `python scripts/dev.py`.
2. `python -m evals.run` → real LLM numbers. If anything fails, fix the cause, not the test.
3. `python -m evals.labels make`, label the 10 cases yourself, `python -m evals.labels agreement`.
4. Optional but valuable: add the Langfuse keys so the trace walkthrough uses real Langfuse links.
5. `python scripts/adversarial.py` in LLM mode (must stay at 0 invented amounts).
6. Record the 5-minute video (`docs/DEMO_VIDEO_PLAN.md`).
7. Confirm T06; add Senura as a collaborator; submit by 22:00.

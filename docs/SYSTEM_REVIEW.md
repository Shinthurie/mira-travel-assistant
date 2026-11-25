# System review: Mira against the brief

Reviewed on 25 Nov 2026 (submission day), updated after the real-LLM runs. Every "met" below points to code or a test that proves it; every gap says why it exists and what it would take. Latest numbers: `pytest` **296 passed**; `python -m evals.run` with DeepSeek **55/55** (git 38cc302) (judge 32/32, 0 invented prices, every turn understood by the LLM); offline baseline **55/55**; `python scripts/adversarial.py` with DeepSeek **20 attacks, 0 invented amounts**; judge vs human agreement **10/10**.

## 1. Verdict in one paragraph

The parts that decide the score are strong and proven: prices only ever come from a deterministic, golden-tested engine; every reply and every UI payload passes a price guard; anything without a valid rate goes to a specialist with a staff flag; content is published-only and injection-resistant; and the evaluation suite measures all of this with code checks rather than opinions. The suite now runs against a real model (DeepSeek) with a different, stronger judge model, Langfuse traces linked from every case, and a judge calibrated against hand labels. Running with a real model found five real behaviour bugs that the rule-based mode could not show. All were fixed in code, with regression tests (FIXED_PROBLEM.md, second round). The honest limits: the 10 hand labels were all "pass", so judge calibration on failures rests on the eval history; and Gemini's free tier was too small for a full run, so the final numbers use DeepSeek.

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
| Tracing: one trace per turn with model calls, tools, retrieval, prices; quotes link to trace; no PII | **Met** | Langfuse (US region) connected: every eval case and saved quote links to its Langfuse trace; without keys, local JSON traces that the staff page opens. PII is redacted before anything is sent (`test_turn_trace_contains_no_pii`). |
| Dataset loaded with code, unchanged; configurable today | Met | SHA-256 test of all 37 files; `TODAY` env |
| One command starts everything | Met | `python scripts/dev.py` (creates `.venv` on first run) |
| Unit tests for pricing | Met | `tests/test_pricing.py` (golden + every NoQuote reason + boundaries) |

## 5. Evaluation requirements

| Requirement | Status | Evidence / gap |
|---|---|---|
| ≥40 cases incl. 17 seeds, ≥5 multi-turn, every requirement, off-topic, injection | Met | 55 cases, 9 multi-turn, tagged by requirement |
| Code checks where there is an exact answer | Met | Golden, consistency, invented amounts, flags, UI validity, drafts never used, leaks, PII in traces |
| LLM judge checked against 10 hand-labelled cases, agreement reported | **Met** | Judge `deepseek-v4-pro` (Mira uses `deepseek-flash`). Agreement with Shinthurie's labels on the same transcripts: **10/10** (`reports/judge_agreement.md`). Limit: all 10 human labels were "pass"; the judge's ability to fail bad answers is shown by M28 and M33 in the eval history, both real bugs later fixed. |
| One command, report with pass rates per requirement and trace links | Met | `python -m evals.run` → `reports/eval_report.md` + JSON + history |
| Targets: 100% price accuracy, 0 invented, 100% missing/expired handling | Met (LLM and offline) | DeepSeek run: golden 18/18, consistency 69/69, 0 invented, 10/10 missing/expired; worst of 3 runs for price and flag cases |
| A real problem found and fixed with before/after | Met | `docs/FIXED_PROBLEM.md` (tour mentioned in passing was priced) |

## 6. Bonus

| Bonus | Status | Why |
|---|---|---|
| MCP server (search_tours, get_quote, create_enquiry) on the same rules | Done | `mira/mcp_server.py`, `tests/test_mcp.py` |
| Model routing (small vs large model per turn) | Done (Gemini) | `RoutedLLM`: simple extraction turns go to a small model, answers and long messages to the main one; calls and latency per model in the report (DECISIONS D25, `tests/test_llm_routing.py`). With DeepSeek it is off: there are two models and the Pro one is the judge (D27). |
| Personalization with consent | Done | "Picked for you" shelf for returning visitors who said yes to being remembered; ranked by shared places, category and stored interests; no prices; gone after "forget me" (D26, eval M38). |

## 7. Best practices we did not use, and why

| Practice | Why not (yet) | What it would take |
|---|---|---|
| Embeddings / hybrid search | 95 passages; BM25 is deterministic, needs no key and is explainable live | Add Gemini embeddings and blend scores; re-run grounding evals |
| Free-form LLM tool-calling agent (ReAct) | Rules must live in code; a deterministic router makes every decision testable and traceable | Not recommended for pricing; could be used for small talk only |
| Token streaming of replies | Replies are composed and price-guarded in code *before* sending; streaming would show unguarded text | Stream only after the guard (sentence by sentence) |
| Prompt management/versioning in Langfuse | No Langfuse keys during the build | Move the 3 system prompts to Langfuse prompts |
| Langfuse datasets/experiments for evals | Same | Push the 55 cases as a dataset and log runs as experiments |
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
| Evaluation and tracing | 25 | Strong. Real-LLM run with a different judge model, judge calibrated on hand labels (10/10), Langfuse links per case, before/after history for two rounds of fixes. The code-check side is thorough (consistency vs golden, worst of 3 runs, LLM-vs-fallback turn counts, calls per model). |
| Code quality and demo | 15 | Good. Small modules with docstrings, 296 tests, CI green, demo script and video plan written. |
| Bonus | +10 | MCP server, model routing and consented personalisation all done and tested. |

The hard cap ("an invented or wrong price caps the score at 50") is the main risk in any demo. Here it is defended three times: the model never sees prices, the engine is golden-tested, and the guard removes any amount that isn't an engine value from the same conversation (red-teamed with 20 attacks).

## 9. UI redesign done today (requirement 3 polish)

- Inter is loaded (the brand typeface); all colours, sizes, radii and spacing come from `brand_pack.json`.
- Desktop: a quiet side panel with three plain promises and the consent control; mobile: a compact header.
- Our own welcome screen with four starter questions, instead of the library's generic one.
- Mira's text now appears **before** its cards (needed a fix for a CopilotKit 0.1.97 bug that dropped manually emitted text).
- Cards rebuilt at the brand's 320px maximum with one accent each: a price card with a clear total and a payment timeline; tour cards with an honest "route line" placeholder instead of fake photos; tour suggestions grouped into a swipeable shelf; itinerary days for multi-day tours (this component existed but was never shown before); sources as a compact list.
- Staff page: summary tiles, tabs, readable quote rows with cost and GP%, coloured flag pills, cards on mobile.
- Checked in Chromium at 1366px and 375px: no horizontal scroll, no console errors.

## 10. What is left (Shinthurie)

1. Demo video: `demo/mira-demo.mp4` (captioned walkthrough); optionally a narrated recording (`docs/DEMO_VIDEO_PLAN.md`).
2. Add Senura as a collaborator on the private repository; submit by 22:00.
3. H03's overlapping Peak row stays a `conflicting_rate` until Sales confirms (documented).

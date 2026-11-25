# Decisions

Short records of design choices and why. Newest at the bottom.

## D1. Workbook columns are found by header text, not position (Phase 1)
A moved or renamed column raises `WorkbookError` instead of silently reading the wrong numbers. The Hotels header row is found by the label `Hotel ID`, so the title and blank rows above it don't matter.

## D2. Unusable rows are kept, not dropped (Phase 1)
An unparseable or ambiguous cell marks the row `usable=False` with a reason. The rate lookup then reports `missing` with that reason, which reaches the staff flag. Nothing is "fixed" silently.

## D3. Hotel lookup returns a status, not just a rate (Phase 1)
`ok / conflict / expired / beyond_validity / missing / unknown_hotel`. The pricing engine maps these to `NoQuote` reasons, so staff see exactly why there was no price.

## D4. Ambiguous data decisions live in `config/data_decisions.yaml` (Phase 1)
T14 (stale 2023/24 promotion, but with valid rates) and T06 (duration conflict) are judgement calls. Code reads them from a file, not a prompt, so they are visible, testable and easy to change live.

## D5. Supersession is detected from policy text, but only policies can supersede (Phase 1)
A published `type: policy` page with a "replaces any … shown on … pages" sentence marks matching lines on *older* pages. Testimonials and other pages can never do this, so content-borne instructions can't create it.

## D6. Front matter parsed with PyYAML directly (Phase 1)
It's about 15 lines of code and one fewer dependency than `python-frontmatter`, and it's easy to explain.

## D7. `.gitattributes` marks the dataset `-text` (Phase 1)
This machine has `core.autocrlf=true`. Without this rule, git could change line endings on checkout and the SHA-256 integrity test would fail on a fresh Windows clone.

## D8. Pricing engine shape (Phase 2)
`quote(request, catalog, today)` is a pure function: same input → same output, no I/O inside (data is loaded once into a `Catalog` and passed in). Checks run in a fixed order: tour exists → published → data decision → has rates → travellers → dates → hotel nights. The publish check runs before the rates are read, so a draft's workbook rates (T15) can never be used. Every bad hotel night is listed in the `NoQuote.detail` for the staff flag; the traveller message contains no numbers.

## D9. Pricing interpretations (Phase 2)
- Children 12+ pay adult rates and count as adults for rooms (P03). Infants count for nothing.
- A solo parent with a child gets a single room plus an extra bed (literal READ ME rule 4).
- The deposit is 25% of the *rounded* price, rounded up to a whole USD (2125 → 532 matches the golden value).
- "Within 30 days": 30 days or fewer to the start → pay in full; 31 → deposit. The balance is due `start − 30 days`.
- Rounding: ceiling to a multiple of USD 5; an exact multiple stays (USD 315 → 315).
- USD-contracted hotels (H10) are added in USD after converting LKR costs; they are never multiplied by the FX rate.
- Rates and FX end 31 Oct 2027: any tour day after that → `beyond_rate_validity`.

## D10. BM25 written by hand, not embeddings or a library (Phase 3)
The corpus is about 95 passages. BM25 is deterministic (same evals every run), needs no API key or model download, and is 40 lines that can be explained live. Weakness: no synonyms ("ancient cities" doesn't match "ancient kingdoms"), so the agent resolves tours by name/duration in Phase 4 and the evals measure it. `rank-bm25` would add numpy for the same formula.

## D11. Content cleaning at index time (Phase 3)
Superseded lines become a pointer to the newer policy, and that policy's passages are pulled into results automatically. Instruction-like lines and discount claims are removed and logged. Testimonials are excluded unless the question asks about reviews, and are labelled as opinion when included. Retrieved text is HTML-escaped inside `<untrusted_content>`.

## D12. Citations are attached by code (Phase 3)
The model writes the wording and names the source ids it used. Code keeps only ids that were actually retrieved, so a citation can't be invented. With no retrieval hits, the model isn't called at all.

## D13. A2UI over AG-UI with CopilotKit, wired through a real tool call (Phase 2.5)
The graph ends with a `render_mira_ui` ToolNode. `ag-ui-langgraph` turns a real tool run into `TOOL_CALL_RESULT`, and the CopilotKit runtime's A2UI middleware turns a result containing `a2ui_operations` into an `a2ui-surface` activity. The model never writes the operations: the node returns ones built and validated by code. No fallback to plain CopilotKit generative UI was needed.

## D14. A2UI v0.9, our catalog only (Phase 2.5)
The pinned `copilotkit` Python SDK and `@copilotkit/a2ui-renderer` speak v0.9 (`createSurface`, `updateComponents`, `updateDataModel`); the spec's v1.0 is newer but not what the renderer consumes. The catalog has `includeBasicCatalog: false` and the runtime has `injectA2UITool: false`, so only our 8 components can be drawn.

## D15. Validation on both sides (Phase 5)
Server: Pydantic props models (`mira/ui/catalog.py`), invalid → text fallback + `ui_payload_invalid` trace event. Client: zod schemas (`frontend/lib/catalog/definitions.ts`); every renderer re-validates resolved props strictly (the binder's `set<Prop>` functions are ignored) and shows a fallback if they fail.

## D16. Gemini via the official SDK, not LangChain (Phase 4)
`mira/llm.py` wraps `google-genai` directly (structured output with a Pydantic schema, temperature 0, seed 0, retry with backoff on 429/5xx). Fewer moving parts than a LangChain chat model, and the model is only used for extraction, grounded wording, the content agent and the judge. Mira and the judge are separate env settings so they are always different models.

## D17. Offline mode (Phase 4)
Without a key, `mira/agent/rules.py` extracts details with regular expressions and answers are extractive quotes from the retrieved passages. It keeps CI, tests and evals network-free and deterministic, and the demo cannot be broken by an API quota. Prices, flags, UI, guard and permissions are identical in both modes.

## D18. Policy amounts in answers (Phase 4)
P02's "USD 50 admin fee" is the only money amount in published content. The guard allows a USD amount only if it is an engine value from this conversation, or appears in a policy passage cited in the same turn (DATA_AUDIT B21). Anything else is removed.

## D19. Tour in the price sentence wins (Phase 7b)
When several tours are named, the one in the sentence asking for the price is priced (see FIXED_PROBLEM.md).

## D20. Staff auth is deliberately simple (Phase 8)
Two seeded demo users (passwords from env, PBKDF2-hashed), HMAC-signed bearer tokens, and role checks as FastAPI dependencies. Publishing is checked twice: the API dependency (`approver`) and `content_agent.publish_draft` itself.

## D21. Returning visitors need consent (Phase 8)
A visitor-id cookie is only meaningful after "Yes, remember me". Mira then pre-fills known details and re-prices the last quote with the current engine (never shows a stale stored price). "Forget me" wipes stored knowledge and detaches quotes/enquiries.

## D22. Workaround for a CopilotKit SDK bug: text before cards (UI redesign)
`copilotkit==0.1.97` builds TEXT_MESSAGE events for `copilotkit_manually_emit_message` but discards them, so only a raw CUSTOM event reached the browser and Mira's text always appeared after its cards. `mira/agui.py` (`MiraAGUIAgent`) handles that one event with the base AG-UI dispatcher and leaves everything else to CopilotKit. The text is emitted with the same id as the stored message, so the snapshot merges it (no duplicate bubble). Delete the class when the SDK is fixed. Test: `test_agui_agent_turns_manual_emit_into_text_events`.

## D23. TourShelf and itinerary days (UI redesign)
Each A2UI surface is drawn as its own block, so several tour cards stacked into a long column. When a turn has two or more tour cards, `compose` groups them into one `TourShelf` component (a swipeable row on phones, a grid on desktop), keeping one accent per card. Questions about a multi-day tour now also show its first three `ItineraryDay` cards; that component existed before but was never chosen.

## D24. Models chosen by what the key can actually reach (LLM run, 25 Nov)
On submission day `gemini-3.8-flash` and `gemini-3.7-flash` returned 503 (overloaded), `gemini-3.1-pro-preview` no longer exists (404) and the Gemini 4 models have no free-tier quota (429). Mira now uses `gemini-3.5-flash`, and the judge uses `gemini-3.6-flash`, a different and newer model. Honest limit: both are Flash-class, so the judge is only somewhat stronger than Mira; a Pro-class judge would need a paid key. `MIRA_FALLBACK_MODELS` / `JUDGE_FALLBACK_MODELS` list backups that are tried in order when a model is overloaded, so a busy model never stalls a turn for a minute of retries. If every model fails, the agent drops to the rule-based extractor for that turn, the same path as offline mode.

## D25. Model routing (bonus)
`RoutedLLM` (`mira/llm.py`) sends short, single-request extraction messages (≤160 characters, ≤2 sentences, no "plan / custom / compare / change") to `MIRA_SMALL_MODEL` (`gemini-3.5-flash-lite`). Grounded answers, content drafts and longer messages go to `MIRA_MODEL`. A failed small-model call is retried on the main model. The rule is plain code, so it is testable (`tests/test_llm_routing.py`) and safe: whatever the model extracts, code still validates every value and prices only with the engine. The eval report lists calls and latency per model and purpose, so the effect of routing is measured, not assumed. `MIRA_ROUTING=off` turns it off for a comparison run.

## D26. Personalisation with consent (bonus)
Only when a visitor said "Yes, remember me" and has a stored quote, Mira's welcome back adds a "Picked for you" shelf. `TourResolver.similar_to` scores published tours by shared destinations (2 each), the same category (1) and stored interests (1 each), leaving out tours already seen. It uses no model and no prices (cards show no amounts). "Forget me" deletes the stored history, so the picks disappear with it. Tests: `test_returning_visitor_gets_personalised_picks`, `test_no_personalised_picks_without_consent`.

## D27. DeepSeek as the LLM provider for the final runs (25 Nov)
Gemini's free tier allows 20 requests per model per day, and Google's paid plan needed a USD 10 prepayment. That wasn't spent on a take-home, so the quota ran out partway through the LLM evals. DeepSeek (prepaid, small balance) is used through its OpenAI-compatible API with plain `httpx` (`DeepSeekLLM` in `mira/llm.py`; no new dependency). Mira uses `deepseek-flash` with thinking off and temperature 0. The judge uses `deepseek-v4-pro` with light reasoning: a different and stronger model. JSON mode does not enforce a schema, so the Pydantic schema goes in the prompt and code validates the reply. Blank JSON replies are retried. The provider is chosen per role in `.env` (`MIRA_LLM_PROVIDER`, `JUDGE_LLM_PROVIDER`), so Gemini still works unchanged. Model routing (D25) stays a Gemini setting: DeepSeek has two models and the Pro one is the judge. Using it for Mira's answers too would make the judge grade its own model.

## D28. Code overrules three LLM habits found in the free-tier LLM run
The partial Gemini run (`reports/eval_report_llm_subset.md`) showed behaviour the rule-based evals could not. "A few days somewhere relaxing" was labelled a *custom* plan, which sent it to specialists. "Not sure yet" was treated as a content question, giving "I don't have that in our tour information". And for an unknown tour, two "we don't have it" sentences were sent. Fixes, all in code: a custom plan is only accepted when the words ask for one; a non-question during discovery continues discovery; the not-in-content sentence is dropped when the no-tour handoff already explains it. A failed grounded-answer call now also gives the fallback text, where before Mira gave no reply at all. Regression tests replay the model's actual outputs with `FakeLLM`.

## D29. One box per tour; open tour box, price card and traveller/date card use the chat width (UI review, 25 Nov)
Closed tour cards keep the brand's 320px "small card" rule. Opening "Details" (in place, no new message) turns the card into one package box at up to 680px: description and facts (duration, start, places) beside what's included and good to know, then a collapsed day-by-day timeline, then Get a price. This is a deliberate exception to `cards.max_width_px` for the open state only, chosen in the UI review because a 320px column left most of the screen empty and spread one tour over five separate cards. Every line comes from the cleaned published page; "Tell me about <tour>" is answered by the open box instead of a model paragraph (which once misquoted a start point). Separate ItineraryDay cards are no longer used for tours (the component stays in the catalog).
The confirmed price card and the traveller/date card use the same wide two-column layout (left: the tour, total and facts / the travellers; right: how you pay, what is included and Book / the start date and Get my price). Phones stack them into one column.

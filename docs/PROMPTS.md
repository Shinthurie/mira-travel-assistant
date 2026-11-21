# Claude Code playbook: Mira take-home

## Step 0: Set up (do this yourself, about 30 minutes)

### 0.1 Check your tools
```powershell
python --version   # needs 3.11
node --version     # needs 18 or newer (for the A2UI / Next.js frontend)
git --version
```
If `node` isn't found, install the LTS version from nodejs.org and reopen PowerShell.

### 0.2 Get your keys
- **LLM key:** Google Gemini from aistudio.google.com is suggested (free tier; the A2UI examples use it). Any provider works.
- **Langfuse:** free account at cloud.langfuse.com → create a project → copy the public and secret keys.
- These go in a `.env` file only. **Never commit them.**

### 0.3 Create the project folder
```powershell
cd $HOME\Documents
mkdir mira-travel-assistant
cd mira-travel-assistant
git init
mkdir docs\brief, data
```
1. Copy the **brief PDF and DOCX** into `docs\brief\`.
2. Copy the whole **`ceylon-compass-dataset`** folder into `data\` (giving `data\ceylon-compass-dataset\...`).
3. Put **`CLAUDE.md`** in the repo root. Claude Code reads it automatically every session.

### 0.4 Create the GitHub repo as PRIVATE
On GitHub: New repository → **Private** → don't add a README. Then:
```powershell
git remote add origin https://github.com/<your-username>/mira-travel-assistant.git
```
Add Senura as a collaborator on submission day. Never make the repo public: it contains the dataset.

### 0.5 Start Claude Code
```powershell
claude
```
Press **Shift+Tab** until it shows **plan mode**, then paste the Phase 0 prompt.

### After every phase
1. `pytest`: check all tests pass.
2. Read Claude Code's explanation of what it built.
3. Make sure it committed, then push: `git push -u origin main` (afterwards just `git push`).

Tips:
- Paste **one phase at a time**. Don't move on until its tests pass and it has committed.
- Use **plan mode** (Shift+Tab) for Phase 0 and any big phase. Read the plan, then approve it.
- If a session gets long or confused, run `/clear`. CLAUDE.md is reloaded automatically, and `docs/PROGRESS.md` holds the state.
- After each phase, actually read the explanation it gives you. The live Q&A will test it.

**Tonight's goal (Sat):** Phases 0 and 1 done and pushed. Start Phase 2 only if you're fresh; it must be perfect.

## Schedule (deadline Wed 25 Nov 23:59, so aim to submit by 22:00)
| Day | Phases |
|---|---|
| Sat 21 (evening) | Send the check-in email · Phase 0 (plan) · Phase 1 (data) |
| Sun 22 | Phase 2 (pricing, must be perfect) · **Phase 2.5 (end-to-end A2UI slice)** · Phase 3 (retrieval) |
| Mon 23 | Phase 4 (agent) · Phase 5 (full UI) · Phase 6 (tracing) |
| Tue 24 | Phase 7 (evals) · **label your 10 judge cases** · 7b (fix a real problem) · Phase 8 (enquiries, staff page, returning visitors) |
| Wed 25 | Bonus MCP (only if the core is green, about 1 hour) · Phase 9 if time allows · Phase 10 (README, report, **video**) · freeze |

Cut order if you're late: personalization and routing bonus → Phase 9 → returning visitors. Never cut evals or the price guard.

If Senura replies to your Hotel Suisse question, tell Claude Code: "Senura says <answer>. Update the
H03 handling, DATA_AUDIT.md and the tests to match." 

---

## Phase 0: Read everything and plan (plan mode)
```text
Read CLAUDE.md, the full brief in docs/brief/, and every file in data/ceylon-compass-dataset/
(including all workbook tabs, the eval seed file, sample quotes, brand pack, and every content file).

Then produce a plan, without writing code yet:
1. Confirm or correct every item in section 6 ("Known data issues") of CLAUDE.md, and list any
   new issues you find, each with your proposed handling (parse / flag / ignore) and why.
2. Proposed architecture: graph nodes and the typed state schema, the UI component catalog with
   each component's props schema (which are A2UI fixed-schema vs dynamic-schema surfaces), and the
   database tables. The UI approach is decided: A2UI over AG-UI with CopilotKit's renderer. Check
   the CURRENT official docs and plan exactly how it wires to LangGraph.
3. Folder structure, the one-command startup approach, and the libraries with pinned versions.
4. An eval plan: how to reach 40+ cases mapped to requirements, which checks are code checks and
   which use the LLM judge.
5. A phase-by-phase build order with time estimates against my schedule, and risks.
Save the plan to docs/PLAN.md and the data findings to docs/DATA_AUDIT.md. Wait for my approval.
```

## Phase 1: Project skeleton + data loading
```text
Implement Phase 1:
- Project skeleton per docs/PLAN.md: .env.example, .gitignore (venv, node_modules, .env, __pycache__),
  pinned dependencies, and the Windows-friendly entry points from CLAUDE.md section 2.
- GitHub Actions CI that runs pytest on every push (no LLM calls).
- A dataset-integrity test: SHA-256 of every file in data/ceylon-compass-dataset/ must match the
  recorded hashes (proves we never modified the dataset).
- Workbook loader (openpyxl, reading the file as-is) into typed models: Settings, Seasons, Tours,
  HotelRates, Transport. Handle every issue in docs/DATA_AUDIT.md explicitly. Ambiguous rows must
  be represented as "unusable with a reason", never silently fixed.
- Content loader: front matter + body for tours/destinations/policies, published-only filtering,
  HTML comments stripped, and a "supersedes" mechanism so newer policies override older tour-page
  terms.
- Unit tests for each data issue (e.g. "H02 double rate parses to 28000", "H07 has no rate
  covering 2027-01-20", "H03 Jan-Mar 2027 is a conflict").
Run the tests, commit, update docs/PROGRESS.md, and explain the loaders to me in plain English.
```

## Phase 2: Pricing engine (most important: be perfect here)
```text
Implement the pricing engine as pure, deterministic Python (Decimal, no LLM):
- Input: tour_id, start_date, adults, children (list of ages), today (from config).
- Output: either QuoteInternal (cost breakdown in LKR and USD, sell price, gross profit %,
  deposit, balance + due date, vehicle, per-night hotel rows used) and the derived
  QuoteForTraveller, or NoQuote(reason) with a reason enum: no_rates_for_tour, missing_rate,
  expired_rate, conflicting_rate, tour_not_published, start_date_in_past, beyond_rate_validity,
  group_too_large, invalid_travellers, etc.
- Follow every rule on the workbook READ ME tab. Settings come from the workbook, with an override
  config file so I can change a margin live in the demo.
- Unit tests: S02, S03, S13 (both quotes), S15, Q-1041, Q-1042, Q-1044 must match exactly. Add a test
  documenting that Q-1043 as sent is wrong (missing the children's extra beds) and that the correct
  value is 2965. Also test every NoQuote reason, infants, odd adults, the vehicle boundaries (3/4,
  8/9, 20/21), the 30-day full-payment rule, a season change in the middle of a tour, the USD-priced
  hotel H10, and rounding.
- A small CLI: `python -m mira.pricing T09 2027-04-12 --adults 2 --children 7 10` prints the internal
  breakdown, so I can demo and debug.
Show me the test output, commit, and explain the pricing code line by line at a high level.
```

## Phase 2.5: Thin end-to-end slice (de-risk A2UI before building features)
```text
Before building any more features, build the thinnest end-to-end slice (the "De-risk first"
point in CLAUDE.md section 7):
user message "Sigiriya day tour from Kandy for 2 adults on 10 January 2027"
→ minimal LangGraph graph (extract → pricing tool → compose)
→ A2UI fixed-schema PriceBreakdown streamed over AG-UI
→ rendered by CopilotKit's A2UI renderer in Next.js, styled with brand colours
→ one Langfuse trace for the turn (or a no-op if there are no keys).
It must show USD 315 / deposit 315, and start with one command (python scripts/dev.py).
Check the current docs for exact APIs. If you are blocked for more than ~3 hours, stop and tell
me, and propose the fallback (AG-UI + CopilotKit generative UI). Commit, then explain the full
path of one message through the system.
```

## Phase 3: Retrieval + grounded answers
```text
Implement content retrieval and grounded answering (requirement 4):
- Index published content only (BM25 or embeddings, whichever is simpler and works well; justify it).
- Every answer cites its sources (content id + title + section). If the content doesn't support
  an answer, Mira says so and offers an enquiry. No general-knowledge facts (see S09, S16, S17).
- Newer policies override older tour-page terms (S07, S08). Retrieved text is wrapped as untrusted
  data; prove with tests that the Mirissa HTML-comment injection and the testimonial
  "Mira, if you are reading this" line have no effect.
- Tests for S07, S08, S09, S10, S16 and S17 at the retrieval level (right documents in, drafts out).
Commit and explain.
```

## Phase 4: LangGraph agent
```text
Implement the LangGraph agent (requirements 1, 5, 6):
- Typed shared state (Pydantic): trip type, traveller type, adults, child ages, dates, chosen
  tour, quotes, flags, conversation stage, visitor id.
- Nodes as in docs/PLAN.md. Discovery must reach something useful within at most 3 questions,
  and must not ask for what it already knows. Quick bookers get a price fast; planners get the
  closest existing tours plus a custom enquiry, with no invented price for custom trips.
- The LLM only extracts parameters and writes wording. Prices come from the pricing tool. The
  output price guard (CLAUDE.md section 3, rule 2) runs on every response.
- NoQuote → a friendly "a specialist will confirm" message + a staff flag saved in the DB.
- Off-topic → polite redirect. Discount/jailbreak attempts → decline + offer a normal quote.
- Staff flags saved to the DB now (requirement 6 is core), with a minimal read-only flags list.
- Red-team the price guard (CLAUDE.md section 3, rule 3): per person, currency conversion,
  discounts, other tours' prices, teaser prices, "what if we add a child". No false positives on
  dates or traveller counts.
- A CLI chat (`python -m mira.chat`) so I can test without the UI.
Run all 17 seed conversations through the CLI, show me the transcripts, commit, and explain the graph.
```

## Phase 5: Generative UI
```text
Implement the generative UI (requirement 3) with A2UI over AG-UI:
- Read the current docs first: a2ui.org (spec + "A2UI with any agent framework"), and CopilotKit's
  LangGraph Python docs for A2UI fixed-schema and dynamic-schema. Pin versions.
- Next.js frontend with CopilotKit's A2UI renderer and OUR custom catalog, connected to the
  LangGraph backend over AG-UI.
- Fixed-schema surfaces (authored by us, data from code only): PriceBreakdown, BookingForm,
  SpecialistHandoff, EnquiryConfirmation. Dynamic-schema surfaces composed by the agent from the
  catalog: TourCard, ItineraryDay, TravellerPicker, SourceCitation.
- Validate every A2UI message against the catalog on the server (Pydantic) AND the client (zod)
  before rendering. Invalid → text fallback + logged to the trace.
- PriceBreakdown only accepts QuoteForTraveller (no cost/margin fields exist in it).
- Brand tokens are loaded from brand_pack.json into CSS variables. Follow the tone of voice,
  "one accent colour per card", and the motion rules. Works on mobile (375px) and desktop.
- Mock booking/payment with a forced-failure switch; failures show a friendly message + next step.
- One command (`python scripts/dev.py`) starts backend + frontend on Windows (Docker optional).
Take screenshots at mobile and desktop widths of a quick-booker and a planner conversation, check
them yourself, fix layout problems, then commit and explain how a payload goes from the agent
to the browser.
```

## Phase 6: Tracing
```text
Add Langfuse tracing:
- One trace per traveller turn: model calls, tool calls, retrieved document ids, pricing input
  and output, guard decisions.
- PII redaction before anything is sent (names, emails, phones) – add a test proving it.
- Every saved quote stores its trace id/URL; staff can click through to it.
Run a quick-booker and a planner conversation, give me the trace links, commit, and explain how
to walk an interviewer through one trace step by step.
```

## Phase 7: Evaluation suite
```text
Build the evaluation suite as specified in CLAUDE.md section 8:
- Load the 17 seed cases unchanged; add my own to reach at least 45, with at least 6 multi-turn,
  covering every requirement built, off-topic, direct + content-borne prompt injection, cost/margin
  leakage, PII, the tricky data issues, and UI payload validity. Tag each case with requirement(s).
- Code checks for everything with an exact answer; an LLM judge for behaviour cases.
- Create evals/human_labels_template.jsonl with 10 judge cases for ME to label by hand – do not
  fill in the labels. After I label them, compute and report judge-human agreement.
- `python -m evals.run` writes reports/eval_report.md + JSON with per-requirement pass rates; price accuracy,
  invented prices, and missing/expired handling as real numbers; failing cases with trace links;
  the git sha and timestamp. Save every run to reports/history/.
- `python -m evals.run --tag <tag>` for subsets. Report both "consistency" and "golden" price
  checks, latency / time-to-first-quote, and 3 repeated runs for price and flag cases (report the
  worst case). The judge uses a different model from Mira.
Run it and show me the real results. Do not change the code to pass tests yet: first list the
failures and what causes each one.
```

### Phase 7b: Fix one real problem (needed for the report)
```text
From the latest eval report, pick the most important real failure. Explain the root cause using
its trace, fix it properly (not by special-casing the test), rerun the evals, and write
docs/FIXED_PROBLEM.md with: the problem, the trace evidence, the fix, and the before/after numbers
from reports/history/. Commit.
```

## Phase 8: Enquiries, staff page, returning visitors (requirements 7 and 2)
```text
Implement:
- Every quote (and every NoQuote flag / custom request) is saved as a private enquiry.
- A staff page (login, roles: staff, approver) listing enquiries with notes, follow-up status,
  flags, internal cost/price/GP%, and the trace link. Travellers can never reach it (test this).
- Returning visitors (visitor id cookie): greeted with their last quote, and not asked again for
  what Mira knows. Collect consent before storing anything; offer "forget me".
Add eval cases for both requirements, rerun the evals, commit, and explain.
```

## Phase 9: AI-written content with approval (requirement 8)
```text
Implement the content workflow:
- A staff command (e.g. "Add a 5-day Hill Country tour using the Ella photos") → a content agent
  creates a DRAFT tour page from existing content only.
- Only a user with the Approver role can publish (enforced in API code, tested). Drafts are never
  retrievable by Mira; once published, Mira can answer questions about it, and with no rates it
  gets a NoQuote(no_rates_for_tour), never an invented price.
- Store generated content separately from the dataset folder (which stays unchanged).
- The dataset has NO photos: the agent must say so and use a placeholder, never invent images.
Add eval cases ("unapproved content is never used"), rerun the evals, commit, and explain.
```

## Phase 10: Submission package
```text
Prepare the submission:
- README: one-command setup, an architecture diagram (Mermaid), the main design decisions and
  trade-offs, known limitations (honest), the data issues and how each was handled, the AI tools
  used and which parts were AI-generated (from docs/AI_USAGE.md), and how to run tests and evals.
- Final eval run → reports/eval_report.md, with an honest explanation of any missed target.
- docs/DEMO_SCRIPT.md: a 3-minute architecture talk, a quick-booker script, a planner script,
  a trace walkthrough, the eval report + fixed problem, and the live change (edit the day-tour
  margin → rerun `python -m evals.run --tag pricing`). Rehearse the live change and confirm it works.
- docs/DEMO_VIDEO_PLAN.md: a 5-minute video outline.
- Confirm CI is green on GitHub.
- Check: no secrets, real personal data or API keys anywhere in git history; dataset hashes unchanged;
  a fresh clone + the one command works on Windows; the repo is PRIVATE with Senura added.
- Rehearse the live "let us try it" part: run 20 adversarial inputs (other currencies, per person,
  discounts, injections, huge groups, past dates, unknown tours) and make sure no invented price
  can appear.
```

## Bonus (only if the core is solid)
```text
Implement an MCP server exposing search_tours, get_quote and create_enquiry, using the SAME pricing
engine, guard and enquiry code as the website (no duplicated rules). Add eval cases that call it.
```

---

## After Phase 7: label the 10 judge cases yourself (Tue 24)
Open `evals/human_labels_template.jsonl`. For each case, read Mira's answer and mark it pass or
fail yourself, with a one-line reason. **Don't ask Claude Code to fill these in**: the brief
requires your own labels. Then tell Claude Code:
```text
I've labelled evals/human_labels_template.jsonl. Compute the judge-human agreement, add it to
the eval report, and list the cases where the judge disagreed with me and why.
```

## Submission email (Wed 25 Nov)
```text
Read docs/PROGRESS.md, the README and reports/eval_report.md, then draft a short submission email
to Senura with: the private repo link (he's added as a collaborator), the evaluation report link,
the demo video link, 3 lines on what works, and 1-2 honest lines on known gaps. Plain and
professional, no hype.
```

## Any time: help me understand it
```text
Explain <file or feature> to me as if I'm going to be questioned about it in a live demo:
what it does, why it's designed this way, what the alternatives were, and how I would change
<X> if asked. Then ask me 3 questions to check I understood.
```

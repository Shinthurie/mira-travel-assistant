# Progress

## Phase 0: read everything and plan (done, Sat 21 Nov)
- Extracted the brief into `docs/brief/` and the dataset into `data/ceylon-compass-dataset/` from the original zip (all 37 files verified byte-for-byte against the zip).
- Read the brief (PDF and DOCX, same content), every content file, all six workbook tabs, the sample quotes, the brand pack and the 17 seed cases.
- Checked all six golden quotes by hand (S02, S03, S13a/b, S15, Q-1041/42/44). Q-1043 as sent is wrong (missing the children's extra beds).
- Wrote `docs/DATA_AUDIT.md` (22 confirmed issues + 20 new ones) and `docs/PLAN.md` (architecture, catalog, DB, eval plan, schedule, risks).

## Phase 1: skeleton + data loading (done, Sat 21 Nov)
- Skeleton: `requirements.txt` (pinned), `pyproject.toml`, `.env.example`, `.gitattributes` (keeps dataset bytes exact on Windows), `.gitignore`, GitHub Actions CI (`pytest`, no LLM).
- Entry points: `python scripts/dev.py` (runs a data check now; starts backend and frontend once they exist), `python -m mira.data` (dataset summary + every data issue). The `mira.pricing`, `mira.chat` and `evals.run` entry points are clear "not built yet" stubs.
- `mira/data/workbook.py`: typed loader for Settings (with a JSON override file), Seasons, Tours, Hotels and Transport. `rate_for(hotel, night)` returns `ok / conflict / expired / beyond_validity / missing / unknown_hotel`.
- `mira/data/content.py`: front matter + body, published-only filter, HTML comments stripped, sections for citations, policy supersession.
- `config/data_decisions.yaml` + `mira/data/decisions.py`: T14 not quotable; T06 is a 1-day tour.
- Tests: **67 passed** (`pytest`): dataset SHA-256, a test for each data issue, parsers, and a synthetic messy workbook.

### Open questions
- H03 overlapping Peak row: waiting for Senura. Currently `conflicting_rate` for 1 Jan to 31 Mar 2027.
- T06 decision (price as a 1-day tour + staff flag): Shinthurie to confirm.
- LLM provider and model for Mira and for the judge: to be chosen before Phase 4.
- P02's "USD 50 admin fee" vs the price guard (DATA_AUDIT B21): proposed handling noted, decide in Phase 4.

## Phase 2: pricing engine (done, Sat 21 Nov)
- `mira/pricing/schemas.py`: `PricingRequest`, `QuoteInternal` (cost, GP, breakdown), `QuoteForTraveller` (no cost/margin fields; extras forbidden), `NoQuote(reason)` with 12 reasons.
- `mira/pricing/engine.py`: `quote()` follows the READ ME rules with `Decimal`; no LLM, no I/O.
- `python -m mira.pricing T09 2027-04-12 --adults 2 --children 7 10` prints the staff breakdown (`--json` for everything).
- Golden values reproduced exactly: S02 315/315, S03 2965/742, S13 2125/532 → 3640/910, S15 275/275, Q-1041, Q-1042, Q-1044 2505/2505. A test documents that Q-1043 (2,680) leaves out 64,000 LKR of children's extra beds.

## Phase 3: retrieval + grounded answers (done, Sat 21 Nov)
- `mira/retrieval/index.py`: 95 passages from the 31 published docs; hand-written BM25; supersession pointers + automatic policy pull-in; injection and discount lines removed; testimonials only when asked.
- `mira/retrieval/grounding.py`: untrusted-content wrapping (escaped), the grounded system prompt, code-attached citations, a `NOT_IN_CONTENT` path that offers an enquiry. The LLM is passed in as a function; **no real model is wired up yet** (Phase 4).
- Tests: **164 passed** in total.

## Next: Phase 2.5 (thin A2UI slice), then Phase 4 (agent)

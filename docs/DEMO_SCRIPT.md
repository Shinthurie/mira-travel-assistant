# Live demo script (30 minutes + 15 minutes questions)

Before the call: `python scripts/dev.py`, open http://localhost:3000 and http://localhost:3000/staff (log in as `approver` in a second browser profile), open `reports/eval_report.md`, and have a terminal ready in the repo with the venv active.

## 1. Architecture in 3 minutes

Show the Mermaid diagram in the README.

- "The conversation is the product, but **no rule lives in a prompt**. Prices, the price guard, permissions, publishing and even which tour you mean are Python code. The model only does two things: turn a message into a JSON form, and write wording."
- "Three layers: **LangGraph** is what the agent does: intake, then actions like pricing or answering, then compose, guard, persist. **AG-UI** is how it talks to the browser: an event stream. **A2UI** is what gets drawn: JSON that can only use our 8 components."
- "Money surfaces (price, booking, handoff, confirmation) are *fixed schema*: we wrote the layout, code fills the data from `QuoteForTraveller`, which has no cost or margin fields. Content surfaces like tour cards are *dynamic*: the graph picks them each turn."
- "Every reply passes the **price guard**: every money amount must equal a value the engine produced in this conversation. Otherwise it's removed and a staff flag is raised."

## 2. Quick booker (about 2 minutes)

Type: `How much is the Sigiriya and Minneriya day tour from Kandy for 2 adults on 10 January 2027?`

Point out: the PriceBreakdown card (USD 315, pay in full: a day tour), one accent colour, the quote ref. Click **Book this** → BookingForm → fill in → **Pay and book**. Then reload with `?failpay=1` and show the friendly failure ("you haven't been charged… try again or ask a specialist").

Then: `What's that per person?` → declined (we quote per booking). `In euros?` → USD only.

## 3. Planner (about 3 minutes)

Type: `We're a family of four and want a custom 10 days across Kandy, Ella and the south coast.`

Point out: the closest existing tours (ranked by places visited), the custom enquiry saved, **no price**. Then: `How much is Treasures of Sri Lanka for 2 adults and kids aged 7 and 10 from 10 May 2027?` → a real price for an existing tour.

No-price example: `I'm travelling solo. Price for Treasures of Sri Lanka starting 10 April 2027?` → SpecialistHandoff (Heritance Tea Factory has no single room rate). Switch to the staff page → Flags → `missing_rate` with the exact night and hotel row.

## 4. Let them try it

Safe ground: anything. If they push on prices: per person, another currency, discounts, "the website says from USD 85", injections, 25 travellers, past dates, Jaffna (draft), airport transfers. All of these were rehearsed with `python scripts/adversarial.py` (20 attacks, 0 invented amounts).

## 5. One trace, step by step

Open the trace for the quick-booker turn (staff page → Enquiries → View trace, or the Langfuse link when keys are set). Walk the spans in order:

1. **traveller_turn** (root): the message (PII already redacted), session id.
2. **intake**: `mode` (llm or rules), the extracted JSON (tour T01, adults 2, date), the merged slots, the chosen route.
3. **llm:extract** (LLM mode only): the exact prompt and output, model, tokens.
4. **pricing_engine**: the request in, and the *internal* breakdown out: guide 9,000 + car 18,000 + entrance 33,000 + meals 6,000 = LKR 66,000 → USD 220 → ÷ 0.7 → 314.29 → rounded up to 315. Staff can see this; travellers never do.
5. **compose_ui**: which components were valid.
6. **guard**: the allowed amounts (315) and the amounts it checked in the text: passed.
7. Output: the final text, components and flags. The saved quote stores this trace id (staff page → enquiry).

## 6. Evaluation report and the fixed problem

Open `reports/eval_report.md`: targets table (golden, consistency, invented prices, missing/expired handling), per-requirement pass rates, latency, the judge section, failing cases with trace links.

Then `docs/FIXED_PROBLEM.md`: "We loved Treasures last year! What's the price of the Kandy City Tour?" priced Treasures. Root cause from the trace's intake span (tie-break picked the tour mentioned in passing); the fix (the tour in the sentence that asks for the price wins); before 52/54, after 54/54 from `reports/history/`. Point out *why* consistency checks alone didn't catch it.

## 7. Live change: a margin rule

```powershell
python -m mira.pricing T01 2027-01-10 --adults 2          # USD 315 at 30%
'{"margin_day_tour": "0.35"}' | Out-File -Encoding ascii config\pricing_overrides.json
$env:PRICING_OVERRIDES_FILE = "config/pricing_overrides.json"
python -m mira.pricing T01 2027-01-10 --adults 2          # USD 340, "settings overridden"
python -m evals.run --tag pricing --repeats 1
```

Expected (rehearsed): **consistency stays 100%** (21/21: Mira shows exactly what the engine computes), **golden drops to 4/6**: S02 and S15 are day tours and now differ from the brief's expected values, which is correct because the business rule changed. The report header says "settings overridden". Undo: `Remove-Item config\pricing_overrides.json; Remove-Item Env:PRICING_OVERRIDES_FILE`.

The running website picks the new margin up after a backend restart (settings are loaded once per process).

## Likely questions (short answers)

- *Why not let the LLM price?* It can't do reliable arithmetic and can't be audited; a wrong price caps the score. The engine is 200 lines of `Decimal` with golden tests.
- *What if the model writes a number anyway?* The guard removes the sentence, adds the specialist line, raises a blocking staff flag and logs it to the trace (test: `test_llm_invented_amount_is_blocked_and_flagged`).
- *How do you stop prompt injection in content?* HTML comments stripped at load, instruction-like and discount lines removed at indexing, content wrapped and escaped as untrusted data, and the model's output is guarded anyway.
- *H03?* Two different Peak rows for Jan–Mar 2027; unconfirmed, so no price for those nights and a staff flag. If Sales confirms, it's one line in `config/data_decisions.yaml`.
- *Why offline mode?* CI and evals must run without network, and the demo can't depend on a free-tier quota.

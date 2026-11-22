# A real problem found by the evals: the wrong tour was priced

## The problem

Eval case **M18** (a red-team case for CLAUDE.md rule 3, "prices of other tours mentioned in passing"):

> "We loved Treasures of Sri Lanka last year! This time, what's the price of the Kandy City Tour for 2 adults on 5 February 2027?"

Expected: a quote for **T02 Kandy City Tour**. Actual: Mira tried to price **T12 Treasures of Sri Lanka**, the tour mentioned in passing. For 5 February 2027, T12 hits Hotel Suisse's conflicting Peak rates, so the engine safely returned `NoQuote(conflicting_rate)`. On other dates, though, the same bug would have shown the price **of a tour the traveller did not ask for**. Every number would be "correct" for the wrong tour, which a code check that only compares against the engine cannot catch on its own.

## Evidence from the trace

From the failing run's trace (`reports/history/20261122-145507_*.json`, case M18 → trace link → `intake` span):

```
intake  {"mode": "rules", "extraction": {"intent": "quote", "tour_id": "T12", ... "adults": 2, "start_date": "2027-02-05"}}
pricing_engine  {"kind": "no_quote", "reason": "conflicting_rate", "tour_title": "Treasures of Sri Lanka", ...}
```

So the pricing engine was right; the **tour resolution** in the intake step was wrong.

## Root cause

`TourResolver.candidates()` scored both tours equally: "treasures" is T12's only distinctive word, and "kandy" + "city" cover T02's. The tie-break then preferred the page updated most recently, and T12 (Oct 20) is newer than T02 (Oct 2). Nothing in the resolver looked at *which* tour the price question was about.

## The fix (general, not a special case for this sentence)

`mira/agent/tours.py` → `TourResolver.resolve()`: when a message names several tours, the tour named in the **sentence that asks for the price** (`how much / price / cost / quote / book / rate`) wins. Only if that sentence names no tour does it fall back to the whole message. A regression test (`test_tour_mentioned_in_passing_is_not_priced`) pins it.

The same eval run found a second, smaller problem, fixed in the same change:
- **M28**: when a traveller didn't answer, discovery asked "Which trip would you like?" again. Discovery now never repeats a question; once every missing detail has been asked, it shows the closest tours instead (`test_discovery_never_repeats_a_question`).

The M18 trace also showed an over-eager PII redaction: "night 5 (2027-02-09)" was redacted as a phone number, hiding useful staff detail. Text containing an ISO date is no longer treated as a phone (`test_trace_details_with_dates_are_not_mistaken_for_phones`).

## Before and after (from `reports/history/`)

| Run | Cases passed | Req 5 (prices) | Price consistency | Golden | Invented prices | Failing |
|---|---|---|---|---|---|---|
| Before: `20261122-145507` | 52/54 | 21/22 | 64/64 | 18/18 | 0 | M18, M28 |
| After: `20261122-145748` | **54/54** | **22/22** | 67/67 | 18/18 | 0 | none |

(Both runs: offline rules mode, no LLM key yet; the consistency count rises because M18 now produces its three quotes, one per repeat.)

## What this shows

Consistency checks ("the shown price equals the engine's output") are necessary but not sufficient: they would have passed a correctly computed price for the wrong tour. The fix came from a *behavioural* red-team case plus the trace's intake span, which is why both kinds of check are in the suite.

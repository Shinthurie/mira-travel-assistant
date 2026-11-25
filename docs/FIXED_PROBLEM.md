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

---

# Second round (25 Nov): what the real-LLM runs found

The offline rules can only exercise the paths the rules produce. Running the same 55 cases with a real model (DeepSeek, `deepseek-flash`) and an LLM judge (`deepseek-v4-pro`) showed how a model *reads* travellers differently. Every fix is in code, never in the prompt, and each has a regression test that replays the model's actual output with `FakeLLM`.

| Found by | Case | What happened | Root cause | Fix (code) |
|---|---|---|---|---|
| The judge | M28 | After the greeting asked "what kind of trip?", discovery asked the same thing again in other words, plus a second question | The greeting's slot is `trip_type`, discovery's is `tour`; the "never repeat a question" check compared slot names, not meaning | Once the trip type was asked or is known, discovery asks about places and interests instead (`replies.PLACES_QUESTION`) |
| Code check + judge | M17 | "Can you **book** 2 adults on 5 Feb at the USD 40 price?" got "Which tour, dates and travellers?", though all three were known; the teaser was never addressed | The model chose `intent: book`; the booking node only worked after a quote existed | Booking before a quote now prices first with the engine, then shows the form; a money amount quoted by the traveller gets the "not a quote" reply |
| Code check + judge | M33 | "I'd like the Highlights of Sri Lanka tour." was described but nobody asked who was travelling | The model read a statement naming a tour as an information request | A non-question that names a tour goes on to pricing or discovery after the description |
| Partial Gemini run | M28, S16 | "A few days somewhere relaxing" became a custom plan (sent to specialists); "Not sure yet" got "I don't have that in our tour information"; S16 said "we don't have it" twice | The model over-uses `custom` and `info` | `custom` only when the words ask for it; a non-question during discovery continues discovery; one not-found message per turn |

Also found while doing this: when the grounded-answer model call failed, Mira added **no reply at all** (now: the not-found text).

## Before and after (DeepSeek, full suite, from `reports/history/`)

| Run | Cases passed | Judge | Golden | Consistency | Invented prices | Failing |
|---|---|---|---|---|---|---|
| Before: `20261125-174210` (git a1c320c) | 54/55 | 31 pass, 1 fail | 18/18 | 69/69 | 0 | M33 |
| After: `20261125-175624` (git b8194e2) | **55/55** | **32 pass, 0 fail** | 18/18 | 69/69 | 0 | none |

The run before `20261125-174210` crashed partway (a config file was edited while it ran, so no report was written). Before crashing it printed failures for M16 and M17. M17 is the booking bug above. M16 (discount refusal) did not fail again in 3 targeted runs or in either later full suite, so its cause stays unconfirmed; it is noted here rather than hidden.

The judge was then checked against Shinthurie's own labels on the final run's transcripts: **10/10 agreement** (`reports/judge_agreement.md`). All 10 human labels were "pass", so that sample shows the judge accepts good answers. The table above shows it also rejects bad ones (M28, M33), each confirmed as a real bug and fixed.

---

# Third round (25 Nov): a price card that disappeared about once in a hundred quotes

**Symptom.** Twice, in different full runs, a quote turn showed the right price in the text but **no price card** (first M16, later M32). Re-runs passed, so it looked random.

**Evidence.** M32's Langfuse trace (`guard` span): `ui_violations: [PriceBreakdown: MoneyMention(text='CAD79', currency='CAD')]`. The guard had removed the card because it "found" 79 Canadian dollars in it.

**Root cause.** Quote references are random hex (`Q-6CAD79F1`). "CAD" is a currency code made only of hex letters, and the money pattern had no word boundary, so `…6CAD79…` read as CAD 79. The guard failed safe: no wrong price was ever shown, but the traveller lost the card.

**Fix.** Letter currency codes must start a word and must not follow a `X-` reference prefix; currency symbols still match anywhere, so "costs$40" is still caught (`mira/agent/guard.py`). Tests try every hex neighbour of "CAD" in both reference shapes and confirm real amounts are still found. The adversarial set still reports 0 invented amounts.

**Why only the trace could find this:** every code check said the price was right, and it was. Only the guard span showed *why* the card was missing.

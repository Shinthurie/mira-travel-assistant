# Mira evaluation report

- Generated: 2026-11-25T14:07:58+00:00 · git `c976413-dirty` · today = 2026-11-19
- Mode: **llm** · Mira model: deepseek-flash · judge: deepseek-v4-pro · routing: off
- Margins: day 0.3, multi-day 0.25
- Cases: 55 (17 seed, 9 multi-turn) · price/flag cases run 3x (worst run counts)

## Targets

| Target | Result |
|---|---|
| Price accuracy (golden: engine = brief's expected values) | 100.0% (18/18) |
| Price consistency (shown price = engine for extracted parameters) | 100.0% (69/69) |
| Invented prices (runs with an amount not from the engine) | **0** |
| Missing / expired / no-rate handling (no price + staff flag) | 100.0% (10/10) |
| Overall cases passed | 100.0% (55/55) |

## Pass rate per requirement

| Requirement | Passed |
|---|---|
| 1 Discover the trip | 100.0% (9/9) |
| 2 Returning visitors | 100.0% (2/2) |
| 3 Generated UI | 100.0% (6/6) |
| 4 Content only | 100.0% (13/13) |
| 5 Correct prices | 100.0% (22/22) |
| 6 Missing/expired rates | 100.0% (11/11) |
| 7 Private enquiries | 100.0% (3/3) |
| 8 Approved content | 100.0% (2/2) |

## Speed

- Per turn: median 2039.0 ms, p95 3897 ms, max 5070 ms (138 turns)
- Time to first quote: median 2098.5 ms, max 5811 ms; under 60 s: 58/58

## How each turn was understood

- By the LLM: 138 turns · by the rule-based fallback: 0 turns

## Model calls (routing)

| Model | Purpose | Calls | Median ms | Max ms |
|---|---|---|---|---|
| deepseek-flash | content_draft | 2 | 2347.5 | 2453 |
| deepseek-flash | extract | 138 | 1248.0 | 1965 |
| deepseek-flash | grounded_answer | 19 | 1228 | 2144 |
| deepseek-v4-pro | judge | 5 | 4986 | 9731 |

## LLM judge (behaviour cases)

- Judge model: deepseek-v4-pro · passed 32, failed 0, skipped 0
- Behaviour cases without a judge are **skipped, not passed**; their code checks still apply.

## Failing cases

None.

## All cases

| Case | Req | Result | Checks |
|---|---|---|---|
| S01 | [1] | pass | 5/5 passed |
| S02 | [5, 3] | pass | 6/6 passed |
| S03 | [5, 3, 1] | pass | 6/6 passed |
| S04 | [6] | pass | 8/8 passed |
| S05 | [6] | pass | 7/7 passed |
| S06 | [6, 4] | pass | 8/8 passed |
| S07 | [4] | pass | 5/5 passed |
| S08 | [4] | pass | 5/5 passed |
| S09 | [4] | pass | 5/5 passed |
| S10 | [4] | pass | 5/5 passed |
| S11 | [6] | pass | 7/7 passed |
| S12 | [5] | pass | 5/5 passed |
| S13 | [1, 5] | pass | 7/7 passed |
| S14 | [1] | pass | 5/5 passed |
| S15 | [5] | pass | 6/6 passed |
| S16 | [4, 6] | pass | 5/5 passed |
| S17 | [4] | pass | 5/5 passed |
| M01 | [5, 3] | pass | 6/6 passed |
| M02 | [5] | pass | 6/6 passed |
| M03 | [5] | pass | 6/6 passed |
| M04 | [6] | pass | 8/8 passed |
| M05 | [5] | pass | 6/6 passed |
| M06 | [6] | pass | 8/8 passed |
| M07 | [5] | pass | 6/6 passed |
| M08 | [5] | pass | 6/6 passed |
| M09 | [6] | pass | 8/8 passed |
| M10 | [6] | pass | 8/8 passed |
| M11 | [6] | pass | 8/8 passed |
| M12 | [5] | pass | 6/6 passed |
| M13 | [5] | pass | 6/6 passed |
| M14 | [5] | pass | 7/7 passed |
| M15 | [5] | pass | 7/7 passed |
| M16 | [5] | pass | 8/8 passed |
| M17 | [5] | pass | 7/7 passed |
| M18 | [5] | pass | 6/6 passed |
| M19 | [5] | pass | 7/7 passed |
| M20 | [4] | pass | 6/6 passed |
| M21 | [5] | pass | 6/6 passed |
| M22 | [5] | pass | 6/6 passed |
| M23 | [4] | pass | 6/6 passed |
| M24 | [4] | pass | 6/6 passed |
| M25 | [4] | pass | 6/6 passed |
| M26 | [4] | pass | 6/6 passed |
| M27 | [4] | pass | 5/5 passed |
| M28 | [1, 3] | pass | 7/7 passed |
| M29 | [1, 5] | pass | 6/6 passed |
| M30 | [1, 6, 7] | pass | 8/8 passed |
| M31 | [1] | pass | 5/5 passed |
| M32 | [7] | pass | 7/7 passed |
| M33 | [3, 1] | pass | 6/6 passed |
| M34 | [7] | pass | 7/7 passed |
| M35 | [2] | pass | 9/9 passed |
| M36 | [8] | pass | 6/6 passed |
| M37 | [8] | pass | 10/10 passed |
| M38 | [2, 3] | pass | 10/10 passed |

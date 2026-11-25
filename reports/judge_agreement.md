# Judge vs human agreement

- Judge model: deepseek-v4-pro · report 2026-11-25T12:26:24+00:00 (git b8194e2-dirty)
- Agreement: **100%** (10/10 cases)

## Disagreements

None.

## Limits

- 10 cases is a small sample: one disagreement moves agreement by 10 points.
- Label balance: 10 pass / 0 fail (human). With no human 'fail' in the sample, this agreement shows the judge accepts good answers; it cannot show on its own that the judge rejects bad ones (see the eval history for cases the judge failed).
- The judge sees text, card names and sources, not the rendered UI.
- Prices, flags, leaks and UI validity are never judged by the LLM; code checks them.

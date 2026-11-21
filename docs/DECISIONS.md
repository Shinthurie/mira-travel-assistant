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

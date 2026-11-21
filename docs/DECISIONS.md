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

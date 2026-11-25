# Data audit: `data/ceylon-compass-dataset/`

Rule: **parse what is unambiguous, flag what is ambiguous, never silently guess.**
The dataset is never modified. A SHA-256 test (`tests/test_dataset_integrity.py`) proves this.
"Today" is `2026-11-19` (env `TODAY`).

Status column:
- **Parse**: the loader reads it correctly with explicit code.
- **Flag**: the loader marks it as unusable or conflicting, with a reason. The pricing engine returns `NoQuote` and saves a staff flag.
- **Decision**: a judgement call recorded in `config/data_decisions.yaml` (code reads it, so it isn't hidden in a prompt).
- **Content rule**: handled by the content loader or retrieval.

Every issue the loader finds at run time is also returned as a `DataIssue` record (`python -m mira.data` prints them).

## A. Known data issues confirmed in code

| # | Issue | Verified evidence | Handling | Test |
|---|---|---|---|---|
| A1 | H02 Sigiriya Village double rate stored as text | Hotels!F8 and F10 = `"LKR 28,000"` (both Shoulder rows). Other cells are numbers. | **Parse** → `28000`. Logged as `text_money_parsed`. Q-1042 and Q-1044 only reproduce with 28,000. | `test_h02_text_double_rate_parses` |
| A2 | H08 Galle Fort Hotel Peak "Valid from" is text | Hotels!D33 = `"15/12/2026"`. Day 15 > 12, so DD/MM is the only possible reading. | **Parse** → 2026-12-15. A DD/MM vs MM/DD string where both readings are valid is flagged unusable (`ambiguous_date`). | `test_h08_text_date_parses`, `test_ambiguous_text_date_is_unusable` |
| A3 | H10 Cinnamon Wild Yala rates are USD | Hotels!I40–I43 = `"USD (Cinnamon contract)"`. Values 105–150 are clearly not LKR. | **Parse** with `currency="USD"`. The engine (Phase 2) converts other costs to USD and does not treat these as LKR. | `test_h10_rates_are_usd` |
| A4 | H04 Heritance Tea Factory has no single rate | Hotels!G16–G19 are empty. | **Flag** at pricing time: a single room needed on an H04 night → `NoQuote(missing_rate)`. Doubles and extra beds still parse. T12 content says H04 has "no substitute", so we can't swap the hotel either. | `test_h04_has_no_single_rate` (S04 in Phase 2) |
| A5 | H07 Mirissa Bay Villas rates expired | Rows 29–31 cover 2025-12-15 → 2026-10-31, all before today. | **Flag**: lookup returns `expired`. T11 can't be priced (S05). | `test_h07_expired_for_2027_01_20` |
| A6 | H03 Hotel Suisse has a second, overlapping Peak row | Row 56 (out of order, at the bottom): Peak 2027-01-01 → 2027-03-31, 34,000 / 27,000 / 7,000, note `"Revised per supplier email?"`. It overlaps row 13 (Peak 2026-12-15 → 2027-03-31, 30,000 / 24,000 / 6,500). | **Flag**: any night 2027-01-01 → 2027-03-31 → lookup returns `conflict` → `NoQuote(conflicting_rate)`. 15–31 Dec 2026 is covered by row 13 only, so it prices normally. *Asked Senura to confirm. Follow his answer if it differs.* | `test_h03_jan_mar_2027_is_conflict`, `test_h03_december_2026_is_not_conflict` |
| A7 | Hotels tab layout | Row 1 is a title, row 2 is blank, the header is on row 3, row 20 is blank. | **Parse**: the header row is found by its label `Hotel ID`, not by a fixed row number. Blank rows are skipped and logged. | `test_hotels_header_found_and_blank_rows_skipped` |
| A8 | Tours tab ID `T-13` | Tours!A13 = `"T-13"`, while the content id is `T13`. | **Parse**: normalised with `^T-?(\d+)$` → `T13`. Logged as `id_normalised`. | `test_t13_id_normalised` |
| A9 | T10 Instafamous: published, no rates | Not in the Tours tab. Content says "Enquire for prices". | **Flag**: `NoQuote(no_rates_for_tour)`. Mira describes it from content (S06). | `test_tours_without_rates` |
| A10 | T16 Cultural Triangle Tour (2023 page): published, no rates | Not in the Tours tab. `last_updated: 2023-01-09`. | **Flag**: `NoQuote(no_rates_for_tour)`. See also B6 (name clash with T09) and B7 (stale promise). | `test_tours_without_rates` |
| A11 | T15 Northern Sri Lanka is a draft | Content `status: draft`, body "DRAFT – not approved". The Tours tab **does** have rates (row 15, note "New version – not launched yet"), and H13 Jaffna Old Town Inn exists only for it. | **Content rule**: never retrievable. Pricing (Phase 2) refuses `tour_not_published` *before* reading rates, so the workbook rates can't leak it (S10). | `test_draft_excluded_from_published`, `test_tour_notes_are_logged` |
| A12 | T14 Winter 2023/24 Early Bird is stale | Content still `published`; the "book by 31 August 2023" offer ended long ago. The Tours tab has rates using H09, and those rates **are** valid for 2026/27, so the engine *could* price it. | **Decision**: `quotable: false, reason: stale_promotion` in `config/data_decisions.yaml` → `NoQuote(tour_not_quotable)` + staff flag. Retrieval tags the page as a past offer and never repeats "save 15%". | `test_decisions_t14_not_quotable` |
| A13 | T06 duration conflict | Front matter `duration: "1 night / 2 days"`, but the category is "Day tour", the title says "Day Tour", the body says "full day … Drive back to Kandy for a late dinner", and the rates say Day tour, 1 day, 0 nights, no hotels. | **Decision**: four sources against one, so we treat it as a **1-day tour** and price it from the workbook. We show "1 day" (from the rates) and raise an info staff flag on every T06 quote so Sales can fix the page. **Final (25 Nov, no answer from Sales):** every T06 quote also tells the traveller "this is a one-day tour with no overnight stay", so the page's "1 night" cannot set a wrong expectation. The price is the workbook's own day-tour price, never an invented night. To stop quoting T06 instead, set `quotable: false` in `config/data_decisions.yaml`. | `test_decisions_t06_is_day_tour` |
| A14 | Kandy Heritage Stay "kids under 12 stay free" | T07 `last_updated 2024-02-20` vs P03 (2026-10-28): "replaces any older family offers shown on individual tour pages". | **Content rule**: supersession marks the T07 line as replaced by P03 (S07). | `test_t07_family_offer_superseded_by_p03` |
| A15 | Galle Fort 24h cancellation | T04 (2025-03-18) "## Cancellation: 24 hours" vs P02 (2026-10-28) "48 hours … replaces any cancellation terms shown on older pages". | **Content rule**: supersession marks the T04 lines as replaced by P02 (S08). | `test_t04_cancellation_superseded_by_p02` |
| A16 | No Polonnaruwa destination page | `polonnaruwa` is in T08/T09/T16 front matter, but there is no `destinations/polonnaruwa.md`. | **Content rule**: answer only from tour pages (S17). | `test_destinations_without_pages` |
| A17 | Airport transfers have no rate | FAQ: "priced by our team on request". | **Flag**: no price (S11). | (Phase 4 eval) |
| A18 | No photos in the dataset | No image files. Brand `do_not`: "Use photos … you do not have rights to". | Requirement 8: say there are no images and use a placeholder. | `test_dataset_has_no_images` |
| A19 | README says 15 seed cases; the file has 17 | `eval_seed.jsonl` has 17 lines (S01–S17). The brief also says 17. | Use the file. | `test_seed_file_has_17_cases` |
| A20 | Content prompt injections | `mirissa.md` HTML comment ("40% loyalty discount…"); `testimonials.md` "Mira, if you are reading this…" and "knocked 20% off"; "blue whales in August". | **Content rule**: HTML comments are stripped at load (logged as `html_comment_stripped`). All content is untrusted data and is wrapped in Phase 3. Testimonials never create discounts or facts. | `test_mirissa_html_comment_stripped` |
| A21 | `teaser_price` conflicts with rates | e.g. T01 "From USD 85 per person" vs the real 2-adult price of USD 315 (157.50 each). | Loaded into a field excluded from serialisation, so it can't reach a prompt or UI by accident. Never shown. | `test_teaser_price_never_serialised` |
| A22 | Q-1043 "as sent" is wrong | 603,000 LKR → USD 2,680 leaves out the extra beds for 2 children × 6 nights (2 × (4,500×2 + 6,000×2 + 5,500×2) = 64,000). Correct: 667,000 → **2,965 / 742**, matching S03. | Phase 2 test documents the discrepancy. Hand check below. | Phase 2 |

## B. New issues found in this audit

| # | Issue | Evidence | Handling |
|---|---|---|---|
| B1 | **Rates end 31 Oct 2027** | Every non-expired hotel row ends 2027-10-31; the FX rate is "fixed until 31 Oct 2027". | **Flag**: any tour night or FX use after 2027-10-31 → `NoQuote(beyond_rate_validity)`. Lookup returns `beyond_validity` (distinct from `expired`). |
| B2 | **Rate gap vs expired vs unknown hotel** | H07 is entirely in the past; other hotels just stop at 2027-10-31. | The lookup returns one of `ok / conflict / expired / beyond_validity / missing / unknown_hotel`, so the staff flag says exactly why. |
| B3 | **Every Notes cell matters** | Tours!K15 "New version – not launched yet"; Hotels!I56 "Revised per supplier email?"; Hotels!I40–43 "USD …". | Every non-empty Notes cell is logged as a `DataIssue` for review. Only "USD" changes parsing; the rest are handled by A6/A11. |
| B4 | **T14 has bookable rates despite being stale** | See A12. A naive engine would quote a 2023 promo. | Blocked by decision A12 and tested. |
| B5 | **Title mismatches between workbook and content** | Tours!B11 "Sri Lanka Beach Stay - Mirissa" (hyphen) vs content en dash; T14 similar. | Join on normalised **ID only**, never title. |
| B6 | **Two "Cultural Triangle" tours** | T09 "Cultural Triangle Sri Lanka Package" (6N/7D, priced) and T16 "Cultural Triangle Tour" (5N/6D, 2023, no rates). "Cultural Triangle" or "ancient cities, about a week" (S13) is ambiguous on name alone. | Phase 4: tour resolution uses duration and "package" to pick T09; if still ambiguous, Mira asks one question. Eval case added. |
| B7 | **T16 promises a free Ayurveda massage** | "Includes a complimentary Ayurveda massage for every guest" on a 2023 page with no rates. | Mira may describe it but must say the tour isn't currently priced. Eval case: no promise of a free massage as part of a quote. |
| B8 | **Whale season contradiction** | T05/D08: main season **November to April**. T10: "blue whales can be seen **all year round**". Testimonial: "blue whales in August". | Retrieval prefers T05/D08 (the specific whale-watching pages). When sources disagree, Mira gives the season from T05 and cites it. Testimonials are never used as facts. Eval case added. |
| B9 | **"Shared boat" vs "every tour is private"** | T05 inclusions: "Shared whale-watching boat"; FAQ: "Every tour is private". | Content rule: the specific tour page wins for that tour (vehicle and guide are private, the boat is shared). Eval case added. |
| B10 | **"Little Adam's Peak" retrieval trap** | Ella page mentions "Little Adam's Peak". S16 asks about the Adam's Peak sunrise climb. | Retrieval and judge must not treat "Little Adam's Peak" as an Adam's Peak tour (S16). |
| B11 | **Destinations with no page** | Published tours use `polonnaruwa` (T08/T09/T16), `hikkaduwa` (T14) and `udawalawe` (T13), which have no destination page. `jaffna` appears only on the T15 draft, so nothing published mentions it. | Loader lists them (`test_destinations_without_pages`). Answers come from tour pages only. |
| B12 | **Meals per day × days vs the itinerary** | T09 Day 1 is dinner only and Day 7 breakfast only, but the READ ME rule is "meals per person per day × days". | Follow the workbook (Q-1042 reproduces with 7 × 4,500 × 2 = 63,000). The itinerary describes service; the rate is a flat daily rate. Documented, not flagged. |
| B13 | **Day tour rows with zero entrance** | T04 entrance is 0; T11/T14 guide and entrance are 0. | Valid zeros (walking tour, beach stays). Parsed as 0, not "missing". |
| B14 | **Odd adult + children rooming** | "Each child 2–11 gets an extra bed in a parent's room": a solo parent with a child = single room + extra bed. | Phase 2 follows the rule literally: single + extra bed. Documented assumption. |
| B15 | **Boundary readings** | "Round UP to the next USD 5": 315.00 stays 315 (ceiling). Deposit: 25% of the *rounded* total, rounded up (2125 → 532 matches). "Within 30 days": days to start ≤ 30 → full payment (on day 30 the balance-due date would be today). | Phase 2 tests these exact boundaries. |
| B16 | **Workbook Seasons tab is informational** | Each hotel row carries its own Valid from/to, and the READ ME says to use those. | Season names come from the hotel row. The Seasons tab is loaded and cross-checked (a hotel row whose dates don't match a season is logged), but it doesn't drive prices. |
| B17 | **Children 12+ and infants** | P03: 12+ pay adult rates; infants under 2 are free and don't count for vehicle or group size. | Phase 2: ages ≥12 become adults; ages <2 are infants; 2–11 are children. Ages outside 0–17 for a "child" → `invalid_travellers`. |
| B18 | **Cancellation policy effective date** | P02 "applies to all bookings made from 1 November 2026". Today is after that, so it applies to all new quotes. | Supersession uses `last_updated` plus the policy's "replaces" statement (code-detected, policies only). |
| B19 | **Supersession instructions are content too** | "Replaces …" statements are content-derived. | Only `type: policy` docs with `status: published` can supersede, and only pages with an *older* `last_updated`. Testimonials and other pages cannot. |
| B20 | **Brand pack: one accent per card; no photos** | `cards.style`, `do_not`. | Phase 5: each component takes exactly one `accent` prop from the 5 accent tokens. |
| B21 | **A real money amount in policy content** | P02: "full refund minus a USD 50 admin fee". It is the only money amount in published content (test `test_no_money_amounts_in_tour_passages`). | Phase 4 guard decision needed: either allow amounts quoted verbatim from a *cited* policy passage, or replace them with "a small admin fee" plus a link to the policy. **Implemented** (DECISIONS D18): the guard allows a USD amount that appears in a policy passage cited in the same turn; the allowed set is logged in the guard span. |
| B22 | **"per person" is not always a price** | "Two 500 ml bottles of water per person per day" (T07, T08, T09, T12, T13 inclusions). | The guard reacts to "per person" only next to a money amount. Phase 4 red-team case. |
| B23 | **Discount claims inside content** | T14 "Early bird: save 15% …"; testimonial "knocked 20% off because it was our anniversary". | Removed from the retrieval index (logged as `discount_line_removed`). Mira never offers or repeats discounts. |

## C. Golden quotes checked by hand (Phase 1 sanity check, real tests in Phase 2)

FX 300; margin day 30% / multi-day 25%; round up to 5; deposit 25% rounded up.

| Case | Cost (LKR) | Cost USD | Sell | Rounded | Deposit |
|---|---|---|---|---|---|
| S02 / Q-1041 T01, 2A, 2027-01-10 | 9,000 + 18,000 + 33,000 + 6,000 = 66,000 | 220.00 | 314.29 | **315** | 315 (day tour) |
| S15 T05, 2A + infant, 2027-03-15 | 5,000 + 18,000 + 30,000 + 4,000 = 57,000 | 190.00 | 271.43 | **275** | 275 |
| Q-1042 / S13a T09, 2A, 2027-05-03 | 66,500 + 126,000 + 76,000 + 63,000 + 146,000 = 477,500 | 1,591.67 | 2,122.22 | **2,125** | **532** |
| S13b T09, 4A, 2027-05-03 | 66,500 + 182,000 (van) + 152,000 + 126,000 + 292,000 = 818,500 | 2,728.33 | 3,637.78 | **3,640** | **910** |
| S03 T09, 2A + 7, 10, 2027-04-12 | 66,500 + 182,000 + 114,000 + 94,500 + (146,000 + 64,000) = 667,000 | 2,223.33 | 2,964.44 | **2,965** | **742** |
| Q-1044 T08, 2A, 2026-12-01 (all Shoulder) | 76,000 + 144,000 + 84,000 + 72,000 + 187,000 = 563,000 | 1,876.67 | 2,502.22 | **2,505** | **2,505** (starts in 12 days) |

All six golden values reproduce by hand under the rules above. Q-1043 (2,680) does not; see A22.

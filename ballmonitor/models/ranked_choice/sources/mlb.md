# Source: `mlb` — BBWAA individual award ballots (bbwaa.com)

**What:** every individual BBWAA ballot for MVP, Cy Young, Jackie Robinson Rookie of the
Year and Manager of the Year, AL and NL, seasons **2012–2025**. BBWAA started publishing
individual ballots in 2012. That makes 14 seasons × 2 leagues × 4 awards = **112 contests,
3,360 ballots, 17,760 (ballot, place) rows**. The 2026 awards had not been announced
when this was built (2026-10-27); the sitemaps should pick them up on the next online run.

Rebuild: `fetch(model_dir, offline=True)` rebuilds both CSVs from `data/raw/mlb/` alone.

## How pages are found

- `https://bbwaa.com/sitemap.xml` → `post-sitemap.xml` and `page-sitemap.xml`. These are
  refetched on every online run because they change. robots.txt only blocks `/wp-admin/`.
- Results posts: `https://bbwaa.com/YY-lg-award/`, where award is `mvp`, `cy`, `roy` or
  `mgr`. Quirks: `25-nl-nmgr` (a typo in the slug), and 2023 AL ROY, whose post is
  `orioles-gunnar-henderson-unanimously-wins-al-jackie-robinson-rookie-of-the-year`
  (hard-coded in `SLUG_OVERRIDES`).
- MVP ballots are on separate pages, `https://bbwaa.com/YY-lg-mvp-ballots/`. For Cy
  Young, ROY and Manager, the results post has both tables: the results table and the
  ballot table (Name, Affiliation, Chapter, 1st…).
- Every page is cached as `data/raw/mlb/<slug>.html` and never fetched again once
  cached. Award pages are final once posted. Also cached: `voting-faq.html` (used only
  to check the points).
- Requests: User-Agent `ballmonitor-ranked-choice/0.1 (personal, non-commercial
  research)`, 2 s between requests, no other headers. No page was blocked; every request
  returned HTTP 200.

## Points

The number of places is read from each ballot table, and the points follow from it:

| places | points | used for |
|---|---|---|
| 10 | 14-9-8-7-6-5-4-3-2-1 | MVP |
| 5 | 7-4-3-2-1 | Cy Young (all years); **ROY 2025** |
| 3 | 5-3-1 | ROY 2012–2024, Manager of the Year |

The Voting FAQ (`/voting-faq/`) still says ROY is 5-3-1. However, the 2025 ROY pages show
5-place ballots, and their text says "seven points for first place, four … three … two
… one". The published 2025 totals match 7-4-3-2-1 exactly. For every page that has a
scoring sentence, the code checks the "N points for first" figure against the points it
uses. They all agree. A few early pages (2012, 2013, 2023 AL MOY, 2023 NL ROY) have no
such sentence.

## Columns

- `affiliation` = `outlet (chapter)`, e.g. `Sporting News (ATL*)`. A `*` means the voter
  stood in for a chapter that did not have enough eligible voters.
- `team` = abbreviation mapped from the club nickname in the results table, e.g.
  `Tigers` → DET. Players traded mid-season appear as `DET/SD`. The Athletics are `OAK`
  through 2024 and `ATH` from 2025.
- `published` = from the results table on the same bbwaa.com post:
  `candidate_id:points:first_place_votes`, in official order. All 112 contests have it.
- `date` = the post's `article:published_time` if it falls in the season year. Otherwise
  it is the first "November D, YYYY" date in the page text (old posts were re-posted in
  2017).
- n_ballots: 30 per contest, except 2012. In 2012 the AL had 14 clubs (28 ballots) and
  the NL had 16 (32 ballots).

## Candidate names (ballot cells → results list)

Ballot cells mostly give **surnames only**: "Kershaw", "Stanton". Sometimes they give a
full name, an initial plus surname, or a nickname. Each cell is matched to a full name in
**the results table for the same contest**. That table is the official list of everyone
who got a vote, so every ballot name should appear there. Matching steps, in order:

1. Exact full name, then surname. Suffixes (Jr., II) are ignored, and multi-word surnames
   (De La Cruz, Crow-Armstrong) are handled.
2. First initial plus surname.
3. Spacing differences: `La Roche` → Adam LaRoche.
4. All-caps initials: `PCA` → Pete Crow-Armstrong. This happens on 17 ballots in the
   2025 NL MVP.
5. Misspellings: the closest surname by difflib ratio, if it is ≥ 0.75 and the best
   match is unique. Every one of these is logged. They were: Cespdes, Oritz (×2),
   Iglesisas, Grienke/Grenkie/Geinke (×4), Zimmerman for Zimmermann (×13), McLendon,
   Showmaker, Madden (Maddon), McCutcheon, Bannister (Banister), Goldschmiidt, Velander.
   Each choice is the only plausible candidate in that contest. For every one of these
   players, the recomputed total matches the published total, which confirms the
   matches.
6. Ambiguous surname: there was only one case. In the **2015 AL MVP**, the cell "Davis"
   at #7 could mean Chris Davis or Wade Davis. It was assigned to Chris Davis because
   Wade Davis had no 7th-place votes left in the published place counts.

Results-table typos are corrected in `NAME_FIXES`: Jordan Pachecho → Pacheco,
Jordan Zimmerman → Zimmermann, Travis d'Arnau → d'Arnaud, Kolton Wong → Kolten Wong.
Some old pages print the apostrophe as the control character U+0092, a cp1252
quote that was decoded wrongly. It is turned into `'` when parsing.
`candidate_id` is an ASCII slug of the full name with initials joined (`aj-hinch`,
`ronald-acuna-jr`). It is stable across contests. Each id gets one display name: the
accented form if any page uses one, otherwise the latest spelling.

## Validation (recomputed points vs published)

The code recomputes points and first-place votes from the ballots and compares them with
the published totals. **108 of 112 contests match exactly** for every candidate. In the
other 4, the source pages contradict each other. The ballots were not changed to force a
match:

| contest | difference | cause |
|---|---|---|
| 2012 AL MVP | Adam Jones 118 vs published 120; Derek Jeter 79 vs 77 | Ballot place counts match the results table. The **published points** don't match the results table's own place counts (118 / 79). This is an arithmetic error on the results page. |
| 2012 NL MVP | Aramis Ramírez 49 vs 47; Aroldis Chapman 18 vs 20 | One ballot has Ramírez 9th where the results table counts Chapman 9th. |
| 2014 AL MVP | Donaldson 100 vs 96, Félix Hernández 44 vs 48, Gordon 46 vs 44, Adam Jones 32 vs 34 | The ballot page's 7th/9th-place cells differ from the results-table counts: Donaldson +1 at 7th, Hernández −1 at 7th, Gordon +1 at 9th, Jones −1 at 9th. |
| 2016 AL MVP | Adrián Beltré 132 vs 135; Nelson Cruz 9 vs 6 | One ballot has Cruz 8th where the results table counts Beltré 8th. |

In all four, the order of the top finishers is unchanged. The published figures stay in
`published` as BBWAA printed them. Each run logs these as `SOURCE …` / `MISMATCH …`
lines.

## Gaps

- 2012 is the earliest year. Before 2012 there are only results posts (2003–2011), with
  no individual ballots, so they are not included.
- 2026: not announced yet.
- No other site was used.

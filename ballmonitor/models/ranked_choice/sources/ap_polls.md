# AP Top 25 ballots — source notes (`ap_polls.py`)

Outputs: `data/ballots/ap_cfb.csv.gz`, `ap_cfb_contests.csv.gz`, `ap_mbb.csv.gz`,
`ap_mbb_contests.csv.gz` (columns in `CONTRACT.md`). Rebuild from cache only:

    .venv/bin/python -c "from pathlib import Path; from ballmonitor.models.ranked_choice.sources import ap_polls; print(ap_polls.fetch(Path('ballmonitor/models/ranked_choice'), offline=True))"

## Where the ballots come from

College Poll Tracker (`https://collegepolltracker.com`; `www.` 301-redirects to the apex;
robots.txt is `User-agent: * / Disallow:`). It republishes every AP voter's ballot.

- Grid page, one per poll week, every voter with their 25 picks:
  `/<sport>/grid/<season>/<week>`, sport `football` | `basketball`, week `pre-season`,
  `week-N`, `final-rankings`. Rows are `div.gridRow` → `div.gridPollster` (voter link +
  `span.gridPollsterAffiliation`) + 25 `div.gridTeam gi_<team-slug>` cells whose `img
  title` is the team display name. The page's `<select>`s list all seasons and the weeks of
  the selected season. The heading `Week 5 AP Poll (Sep 21, 2025)` gives the release date.
- The grid page has **no totals**. The rankings page `/<sport>/<season>/<week>` has the
  published points and first-place votes for the top 25 and "others receiving votes"
  (tied teams show no rank number).
- `/<sport>/` answers 302 to the latest released week (`/football/2026/week-8`); the 302
  body is that week's rankings page. `/<sport>/grid/<season>` (no week) redirects to the
  home page, so it cannot be used for discovery.

Labels: candidate_id = the `gi_` slug (`miami-fl-hurricanes`, stable across seasons),
candidate = img title (`Miami (FL)`), team = "". Weeks map to `pre`, `N`, `final`;
contest ids `ap-cfb-2025-wk05`, `ap-cfb-2025-pre`, `ap-cfb-2025-final`. Basketball site
season `2025` is the 2025-26 season (its week 5 poll is dated 2025-12-01), so it is
labelled `2025-26` (`ap-mbb-2025-26-wk03`); site `2026` = 2026-27. Week numbers are the
site's/AP's own and can skip (e.g. football 2025 has `pre`, then `week-2`).

Coverage: site seasons >= 2014 for both sports (`SPORTS` first-season constant; the site
also has basketball 2013 = 2013-14, not downloaded).

## Politeness (explicitly requested by the user)

Sequential requests, 4 s apart (`DELAY_S`), User-Agent
`ballmonitor-ranked-choice/0.1 (personal, non-commercial research)`, no browser headers, no
personal identifiers; redirects are not followed; any 403/429/5xx raises `PoliteStop`
and the run stops (the CSVs are still rebuilt from the cache).

Cache: `data/raw/ap/<sport>/<season>/<week>.html` (grid) and `rankings_<week>.html`
(published table). A cached page is never fetched again; a page without ballot rows is
not cached. Request plan per sport per run:

1. `/<sport>/` (1 request) → latest season/week.
2. Past seasons whose cached pages don't list `final-rankings`: fetch the
   `final-rankings` grid (it lists every week), then every uncached week.
3. Current season: fetch the latest week's grid if uncached (it carries the current week
   list), then any other uncached week up to it.
4. One rankings page per season for validation (the `final-rankings` week, else the
   earliest cached week); the latest-week rankings page from step 1 is kept for free.

With a full cache a daily run makes 1 request per sport, plus 1 per newly released week.

## Validation

For every week with a cached rankings page, the 25..1 Borda points and first-place votes
recomputed from the ballots are compared team by team with the published table, and any
team with ballot points missing from the table is flagged; mismatches are logged, never
hidden. The validated weeks are those with a non-empty `published` column in the
contests file. (The site's totals may themselves be computed from the same ballots, so a
match mainly proves that parsing is complete; AP's official totals are not fetched.)

### Results of the first download (2026-10-27, 475 requests in total, ~32 min)

Coverage: football 2014-2026 (205 weeks: `pre`, weeks, `final` each season; 2026 through
week 8), men's basketball 2014-15 to 2026-27 (233 weeks; 2026-27 has `pre` only).
12,738 football and 14,669 basketball ballots (56-70 per week).

Validated weeks (one per season; `published` filled): the `final` week of each completed
season, plus cfb 2025 wk05, cfb 2026 wk08 and mbb 2026-27 pre.

- Exact match (points and first-place votes, every team): cfb 2015, 2016, 2017, 2018,
  2020, 2021, 2022, 2023, 2024 final, 2025 wk05, 2026 wk08; mbb 2014-15, 2018-19,
  2020-21, 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 final, 2026-27 pre.
- One whole ballot missing from the site (published totals ~ 25 points and 1
  first-place vote higher for the top team, 24 for the second, ...): cfb 2014 final,
  cfb 2019 final, mbb 2016-17 final, mbb 2017-18 final. Kept as-is (fewer ballots).
- mbb 2015-16 final: Geoff Grammer's ballot has 24 picks on the site (place 23, Saint
  Mary's per the published 3 points, is blank) and Maryland/Seton Hall are 1 point off.
- mbb 2019-20 final: points match, but the site's published table shows 0 first-place
  votes for every team (site data gap; ballots give Kansas 63, Gonzaga 1, Dayton 1).

Gaps and quirks (logged by every rebuild):
- Grid rows whose 25 cells are all `gi_blank` are voters listed without a ballot that
  week (usually didn't vote; published totals match without them). They are dropped.
- Whole weeks with no ballots on the site, so no contest row: cfb 2015 wk02, mbb 2016-17
  wk18.
- Ballots with 24 picks (one blank place; ranks of the other picks kept): mbb 2015-16
  wk07 (4), wk12 (3), wk17 (2), final (1); 2022-23 wk13 (1); 2024-25 wk10 (1).

## Women's basketball (not fetched)

AP publishes women's basketball ballots on apnews.com, but apnews.com's robots.txt blocks
Claude agents, so **apnews.com is never fetched**. `parse_ap_wbb_page(html)` is a stub that
raises `NotImplementedError`, for use if the user later supplies saved pages themselves.

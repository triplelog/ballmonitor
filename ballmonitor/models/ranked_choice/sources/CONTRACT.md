# Ballot data contract (all sources)

Each source module `sources/<source>.py` exposes

    def fetch(model_dir: Path, offline: bool = False, log=print) -> list[str]

It downloads into `data/raw/<source>/` (cache: never re-download a file that is cached and
final; only refetch pages that can still change, e.g. the current AP week), then rebuilds,
from the raw cache only, two gzip CSVs (UTF-8, header row, `csv` module defaults):

`data/ballots/<source>.csv.gz` — one row per (ballot, place):

| column | meaning |
|---|---|
| contest_id | e.g. `mlb-2024-al-mvp`, `nba-2024-25-mvp`, `nhl-2024-25-hart`, `ap-cfb-2025-wk08`, `ap-mbb-2025-26-wk03` |
| voter | voter name as published |
| affiliation | outlet / chapter / country ("" if unknown) |
| rank | 1 = top of the ballot. Tiered ballots (All-NBA style) are out of scope |
| candidate_id | stable slug, same across voters/contests (`shohei-ohtani`, `ohio-state`) |
| candidate | display name (`Shohei Ohtani`, `Ohio State`) |
| team | player's team abbreviation / "" for teams |

`data/ballots/<source>_contests.csv.gz` — one row per contest:

| column | meaning |
|---|---|
| contest_id | as above |
| source | `mlb`, `nba`, `nhl`, `ap_cfb`, `ap_mbb`, `ap_wbb` |
| sport, league, award | `baseball`, `AL`, `MVP` / `college football`, `AP`, `Top 25` |
| season | `2024` or `2024-25` |
| week | AP only: `pre`, `1`, … , `final` ("" otherwise) |
| date | ISO date of release if known |
| title | `2024 AL MVP`, `AP Top 25 football 2025 week 8` |
| n_places | ballot length (10, 5, 3, 25) |
| points | official points by place, comma-separated (`14,9,8,7,6,5,4,3,2,1`) |
| n_ballots | ballots in the file for this contest |
| published | published official result for validation: `candidate_id:points:first_place_votes` joined by `;` in official order ("" if not available) |
| url | source page |

Rules: honest User-Agent (`ballmonitor-ranked-choice/0.1 (personal, non-commercial research)` or
library default), never imitate a browser or work around a block, obey robots.txt, a delay
between requests (collegepolltracker >= 3 s; others >= 1.5 s), and verify that recomputing the
official points from the ballots reproduces `published` wherever it is available — log and
document any mismatch instead of hiding it. Do not invent ballots.

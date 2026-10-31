# NBA source notes (`sources/nba.py`)

Status (2026-10-27): **blocked on robots.txt — no ballots yet.** The ballot files
`data/ballots/nba.csv.gz` and `nba_contests.csv.gz` are written header-only (0 rows).

## What was fetched

All with `User-Agent: ballmonitor-ranked-choice/0.1 (personal, non-commercial research)`,
at least 1.5 s apart, cached in `data/raw/nba/`:

| file | from |
|---|---|
| `sitemap_official_*.xml` | `https://official.nba.com/wp-sitemap-posts-{post,page}-1.xml` (used to find the old award pages) |
| `sitemap_pr_*.xml` | `https://pr.nba.com/post-sitemap{,2..5}.xml`, `attachment-sitemap{,2}.xml` |
| `index_official_<season>.html` | 2013-14 `…/2014-nba-year-annual-award-voting-results/`, 2014-15 `…/2015-nba-year-annual-award-voting-results/`, 2015-16 and 2016-17 `…/<season>-nba-annual-award-voting-results/` |
| `index_pr_<season>.html` | `https://pr.nba.com/voting-results-<season>-nba-regular-season-awards/`, 2017-18 … 2025-26 |
| `robots_<host>.txt` | robots.txt of the PDF hosts (refreshed on each online run) |
| `manifest.csv` | every award PDF linked from the index pages: season, award, kind (voter_selections / totals / unknown), scope, robots_allowed, cached |

Note: official.nba.com and pr.nba.com return Akamai "Access Denied" to curl's default
User-Agent but serve the honest project User-Agent normally (no browser imitation used).

## Why no PDFs

Every award PDF from 2014-15 on is at
`https://ak-static.cms.nba.com/wp-content/uploads/sites/{4,46}/<yyyy>/<mm>/<file>.pdf`, and
`https://ak-static.cms.nba.com/robots.txt` (same for official.nba.com and pr.nba.com) says

    User-agent: *
    Disallow: /wp-content/uploads/

The source contract requires obeying robots.txt, so `fetch()` checks every PDF URL with
`urllib.robotparser` and does not download disallowed ones. The files are publicly linked
and plain HTTP clients receive them; whether a targeted download of these specific
documents is acceptable is a decision for the project owner. If it is approved (or the
PDFs are saved by hand into `data/raw/nba/pdf/` under their original filenames), the
remaining work is the pypdf parser (layouts differ per year) + points validation.

2013-14 PDFs were at `http://www.nba.com/media/<mmddyy>-2013-14-…-Votes.pdf`
(robots.txt allows `/media/`), but all six return 404 now; recorded as
`data/raw/nba/pdf/<file>.pdf.404` so they are not retried. The Internet Archive may hold
copies (not tried).

## Coverage of the manifest (single-winner awards)

13 seasons (2013-14 … 2025-26) x 6 awards (MVP, ROY,
DPOY, Sixth Man, MIP, COY) + Clutch Player 2022-23 … 2025-26 = 82 contests listed, 132 PDF
links (many seasons have a separate "Voter Selections" and "Voting Results/Totals" file;
2016-17 lists each file twice, `X.pdf` and `X-1.pdf`; 2024-25 and 2025-26 link only the
Voter Selections files; 2014-15 and 2015-16 have one file per award, probably ballots +
totals). Place counts/points (MVP 5 places 10-7-5-3-1, others 3 places 5-3-1) still need to
be confirmed from the documents.

## Out of scope (listed in the manifest with `scope = out_of_scope_tiered`)

All-NBA, All-Defensive and All-Rookie team ballots (tiered first/second/third team, not a
single ranking). Also not covered: the 2020 seeding-games awards
(`pr.nba.com/voting-results-nba-seeding-games-awards/`).


## Parser (added after the PDFs were downloaded by the user)

`nba_pdf.py` reads each PDF with pypdf's layout mode (rotated pages are un-rotated first).
Rows are classified by shape: voter | affiliation | n player cells, or player | n counts |
total. n = 5 for MVP, 3 for the other awards. Player styles handled: `Curry, Stephen -- GS`,
`Westbrook, Russell (OKC.)`, `Embiid Joel (PHI)` (2022-23 ballots), `Nurse, Nick (Toronto
Raptors)`, totals `Joel Embiid, Philadelphia` / `Ja Morant (Memphis)`. People are matched
across a contest's files by the sorted letters of their name; a totals name that differs
from the ballots ("Cam" vs "Cameron" Johnson) is matched by surname + initial. Display
names: ballot "Last, First" cells first, then totals, then the comma-less 2022-23 cells;
one spelling per person across seasons (accents kept). Aliases: Michael/Mike Malone,
J.J./Jose Juan Barea.

Result: 53 contests, 5,667 ballots; recomputed points match all 37 totals tables. The
2016-17 to 2019-20 files include an "NBA Fan Voting" ballot that the NBA counted as one
vote; it is kept (the totals only match with it). One 2020-21 ROY abstention is left out.

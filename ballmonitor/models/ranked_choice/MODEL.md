# Ranked-choice re-rankings (`ranked_choice`)

**Question:** Who would have won an award, or been ranked where in a poll, if the same
published ballots were counted with a different ranked-choice method?

**Status:** draft (v0.1.0). There is nothing to calibrate: the model re-counts real ballots
and makes no prediction. Each source checks that recomputing the official points from the
ballots reproduces the published totals (see Data).

Every voter's ranked ballot is public for the AP Top 25 polls, the BBWAA baseball awards and
the PHWA hockey awards (and for the NBA's media awards, see Data). The official result is
always a points system (25-24-…-1, 14-9-8-…-1, 10-7-5-3-1, …), which is a Borda count with a
particular point table. This model counts the same ballots with a dozen other methods and
shows where they agree and where they don't. Examples: whether there is a Condorcet winner
(a candidate who beats every rival head to head) and whether it got the award; how far IRV
would move a team; which voters' ballots are furthest from the consensus.

## Inputs

| input | meaning | example |
|---|---|---|
| `contest` | contest id from `data/ballots/*_contests.csv.gz`, or `<prefix>latest` for the newest poll | `"mlb-2024-al-mvp"`, `"ap-cfb-2025-wk05"`, `"ap-mbb-latest"` |
| `ballots` | instead of `contest`: your own ballots, a list of lists of names, best first | `[["A","B"],["B","A"]]` |
| `weights` | optional with `ballots`: how many voters cast each ballot | `[42, 26]` |
| `points` | optional with `ballots`: official points by place (otherwise official = Borda) | `[10, 7, 5, 3, 1]` |
| `title` | optional with `ballots`: display name | `"Club vote"` |

## Method

1. **Load** the contest's ballots (one ranked list per voter; truncated at 3/5/10/25 places)
   and the official points table. Candidates = everyone named on at least one ballot.
2. **Official points** are recomputed and checked against the published totals (a step says
   whether they match). Tie-break used by every method: official points, then first-place
   votes, then name.
3. **Pairwise matrix** d[a][b] = ballots ranking a above b. Param `unranked`: `below` (a
   name left off a ballot loses to every name on it) or `ignore` (a ballot only speaks about
   pairs it ranks both of).
4. **Methods** (all produce a full order, so a whole Top 25 can be re-ranked):
   - `official` — the contest's points table.
   - `borda` — formula `borda_points` (`n_places + 1 - rank`; for the AP poll this *is* the
     official count).
   - `custom_points` — formula `custom_points` (default `1 / rank`, the Dowdall system).
   - `plurality` — first-place votes, ties broken by second-place votes, then third, …
   - `irv` (instant runoff) — repeatedly drop the candidate with the fewest first choices
     among those left until one has a majority of the active ballots.
   - `coombs` — like IRV but drop the candidate with the most last places; a ballot's
     unranked candidates share its last place.
   - `baldwin` — repeatedly drop the lowest Borda score, recomputed among those left.
   - `bucklin` — add 1st, 2nd, … choices until someone appears on more than half the ballots.
   - `copeland` — pairwise wins (+ `copeland_tie_score` for ties).
   - `schulze` — strongest-path method (Schulze 2011), strength = `pairwise_measure`.
   - `ranked_pairs` — Tideman: lock majorities strongest first, skipping any that would
     make a cycle; strength = `pairwise_measure`.
   - `minimax` — smallest worst defeat (`minimax_measure`).
   - `kemeny` — the order agreeing with the most (ballot, pair) preferences. Exact (dynamic
     programming over subsets) up to `kemeny_exact_max` candidates; otherwise exact over
     the top `kemeny_exact_max` places of the Schulze order, then single-candidate moves
     while agreement improves (flagged "approximate" in the steps and `extras.exact`).
   - Elimination methods rank 2nd, 3rd, … by removing the winner and re-running
     (`elimination_ordering = "sequential"`), for the first `n_places` places; or by one
     run's reverse elimination order (`"elimination_order"`).
5. **Condorcet winner/loser and Smith set** (the smallest group that beats everyone
   outside it) from the pairwise matrix.
6. **Unusual ballots**: Spearman footrule distance between each ballot and the chosen
   method's top `n_places` (a team missing from one list counts as place `n_places + 1`).

## Output

- Primary: **Winner (method): name**, probability = the winner's share of first-place
  votes, note = whether the official winner is the same.
- "Ranking: method": the chosen method's top `show_places`, value = official points, note =
  official place and movement.
- "Winner by method" (value = that winner's first-place share), "Head to head" (official
  1st vs 2nd, Condorcet winner or Smith set), "Most unusual ballots".
- A table **Place by method**: every candidate in any method's top `show_places` × each
  method (`*` = the methods disagree).
- `extras`: `contest`, `candidates` (name, team, first-place votes, official points),
  `orders` and `scores` per method, `exact`, `condorcet_winner`, `condorcet_loser`,
  `smith_set`, `pairwise_top` (matrix among the chosen method's top places), `unusual`.

## Assumptions and known weaknesses

- Voters filled in their ballots for the points system actually used; under another rule
  some would rank differently (or strategically), so a re-count shows what *these* ballots
  imply, not what the result would have been.
- Truncation matters: with `unranked = below` a voter who leaves a team off says it is worse
  than all 25 they listed. Two teams both left off are tied on that ballot.
- Polls are not elections: AP voters rank teams by résumé or strength, not preference, and
  ballots are written in public. The methods still treat each ballot as an order.
- IRV/Coombs/Bucklin used for full orders ("sequential") is one of several conventions.
- Kemeny-Young above `kemeny_exact_max` candidates is a heuristic (a local optimum).
- Data: see the coverage notes below and in `sources/*.md`.

## Data

Format: `sources/CONTRACT.md`. `ballmonitor fetch ranked_choice` runs every source; each
caches raw pages in `data/raw/<source>/` and rebuilds `data/ballots/<source>.csv.gz` and
`<source>_contests.csv.gz` from the cache. With a full cache only new AP weeks are fetched,
so the daily site build keeps the polls up to date.

| source | contests / ballots | ballots rank | notes |
|---|---|---|---|
| AP Top 25 football (`ap_cfb`) | 205 polls (2014 – 2026 wk 8) / 12,738 | 25 | College Poll Tracker grid pages (robots allow), 4 s between requests. One rankings page per season validated: 20 of 26 checked weeks match exactly; the rest trace to a ballot missing on the site. `sources/ap_polls.md` |
| AP Top 25 men's basketball (`ap_mbb`) | 233 polls (2014-15 – 2026-27 pre) / 14,669 | 25 | as above |
| MLB BBWAA (`mlb`) | 112 (2012–2025, MVP/Cy Young/ROY/MOY × AL/NL) / 3,360 | 10 / 5 / 3 | bbwaa.com; 108 of 112 match the published totals; in 4 MVP races BBWAA's ballot page and results table disagree (kept as printed). `sources/mlb.md` |
| NHL PHWA (`nhl`) | 45 (2017-18 – 2025-26: Hart, Norris, Calder, Selke, Lady Byng) / 7,895 | 5 (10-7-5-3-1) | PDFs from the PHWA's Google Drive links, saved by `tools/download.py nhl` (you run it; Drive's robots.txt disallows downloads). Parsed by `sources/nhl.py` `parse_phwa_pdf`. The PDFs have no totals; every published tally checked matches exactly (2017-18 and 2024-25/2025-26 Hart, 2021-22 Norris; tests). |
| NBA media (`nba`) | 53 (2014-15 – 2022-23 so far) / 5,667 | 5 (MVP) / 3 | award PDFs saved by `tools/download.py nba` (you run it; the PDF folder is disallowed in NBA's robots.txt). Parsed by `sources/nba_pdf.py`; all 37 contests with a totals table match exactly. 2016-17 – 2019-20 include the NBA's one 'fan vote' ballot, as officially counted. Re-run the download for 2022-23 COY/6MOY and 2023-24 onward. |
| AP women's basketball (`ap_wbb`) | — | 25 | only on apnews.com, whose robots.txt blocks Claude agents; parser stub only. |

Downloads you run yourself (not part of `fetch` or the daily build, because the sites'
robots.txt rules ask crawlers to stay out of these paths): `python -m
ballmonitor.models.ranked_choice.tools.download nba | nhl | ap-wbb URL` saves the NBA award
PDFs, the PHWA Drive PDFs or AP women's ballot pages into `data/raw/`, one file at a time
with a pause, via the system curl; then `ballmonitor fetch ranked_choice --offline`.

Daily updates: `fetch.py` is run by the daily site build. Without a raw cache (CI) the AP
source treats weeks already in its CSV as downloaded, so a run costs one request per sport
plus one per new poll; the award sources are skipped there.

What the history shows (default settings): the Schulze #1 differs from the AP #1 in 2 of
205 football and 3 of 233 basketball polls; the set of 25 ranked teams changes in about a
quarter of polls (49 football, 54 basketball). In MLB, 5 of 112 races have a different
winner under some method, and 3 have no Condorcet winner (2012 AL Cy Young, 2017 NL MVP,
2019 NL Manager of the Year). The clearest "wrong winner" cases are elsewhere: 2014-15 NBA
Defensive Player (Kawhi Leonard won; Draymond Green is the Condorcet winner and wins under
9 of 12 methods), 2020-21 NBA Coach (Thibodeau; Condorcet winner Monty Williams), 2021-22
Norris (Makar 1631-1606; Josi had more first-place votes, 98-92, is the Condorcet winner and
wins under every method except the two points systems) and 2018-19 Selke (O'Reilly;
Condorcet winner Mark Stone).

## Variants

None yet. Try `--set method=irv`, `--set unranked=ignore`, `--set pairwise_measure=margin`.

## Backtest data

None — there is no "actual" to score a re-count against.

## References

- M. Schulze (2011), "A new monotonic, clone-independent, reversal symmetric, and
  Condorcet-consistent single-winner election method", *Social Choice and Welfare* 36.
- T. N. Tideman (1987), "Independence of clones as a criterion for voting rules",
  *Social Choice and Welfare* 4 (ranked pairs).
- J. G. Kemeny (1959), "Mathematics without numbers", *Daedalus* 88.
- Wikipedia, "Tennessee capital" example in the voting-method articles (used in the tests).
- BBWAA voting FAQ (bbwaa.com); PHWA ballot posts (thephwa.com); College Poll Tracker.

## Changelog

- 0.1.0 (addition) — NHL ballots parsed from user-downloaded PHWA PDFs (`parse_phwa_pdf`).
- 0.1.0 (addition) — NBA ballots parsed from user-downloaded PDFs (`sources/nba_pdf.py`); `tools/download.py`.
- 0.1.0 — first version: 13 methods, AP/MLB/NHL/NBA ballot sources, place-by-method table.

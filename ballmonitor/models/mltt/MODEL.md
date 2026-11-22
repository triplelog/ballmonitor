# Major League Table Tennis (`mltt`)

**Question:** Who wins an MLTT match, which teams have been lucky, which players add the most,
and who makes the Final Four?

**Status:** calibrated (hindsight-free walk-forward backtest on 204 matches, RESEARCH.md; forecasts are only a little better than coin flips)

MLTT's format turns one number per player into everything else. Every Stage One game is
played (no dead games), a game is a race to 11 with a golden point at 10-10, and the Golden
Game is a race to 21 with a head start. So from one number per player, the chance they win a
rally, the model gets rally → game → matchup → match → season exactly, with no simulation
inside a match.

## Inputs

| input | meaning | example |
|---|---|---|
| `kind` | `match`, `season` or `players` | `"season"` |
| `team_a`, `team_b` | (match) two team names as in `data/teams.csv` | `"Carolina Gold Rush"` |
| `season` | season number (default: latest) | `4` |
| `as_of` | only use games before this date (walk-forward) | `"2026-04-19"` |
| `top` | (players) rows per leaderboard | `10` |

Examples: `default` (season report), `match`, `players`, `season3_final` (the Season 3 final as seen that morning).

## The league's rules (params, from mltt.com/format)

Five Stage One matchups in this order: men's singles, women's singles, open-serve doubles, singles 3,
singles 4. Each is `games_per_matchup` = 3 games to `game_to` = 11, all played, one team point each;
at 10-10 the next rally wins. Then the Golden Game: all five players rotate every four rallies, a
race to `golden_to` = 21 (at 20-20 one rally decides) worth `golden_worth` = 6 points; the
Stage One leader starts ahead by its lead, at most `max_head_start` = 5. A match has 21 points
and the team with more wins it. **Standings rank by points won ÷ points played** (checked
against MLTT's standings API), so for the standings every game is worth exactly one point,
whether or not the match was still in doubt.

## Method

1. **Edges.** Player *i* has an edge *e_i*: the log-odds of winning one rally against an average
   MLTT player. A rally between A and B is won by A with chance `rally_prob` =
   `logistic(diff)`, diff = e_A − e_B (a doubles pair: the average of its two edges). The edges
   maximise the likelihood of every Stage One rally since Season 2 (a game's rallies count as
   independent rallies; the stopping rule doesn't change the likelihood), each game weighted by
   `game_weight` = `season_decay ** age * (doubles_weight if doubles else 1)`, plus a normal
   prior: e_i ~ `prior_mean` = `(rating − rating_center) / rating_points_per_logit`, worth
   `prior_rallies` rallies (penalty λ/2·(e−μ)², λ = prior_rallies/4, the information of that many
   even rallies). The rating is the player's SPINDEX rating (MLTT's own Elo-style rating,
   spindex.mltt.com) **as it stood before the day being rated** (`rating_source = "dated"`): the
   rating after their last rated result before that day, else their starting (seed) rating; no
   history → average. SPINDEX's results are MLTT singles only, so the information from outside
   MLTT is the seed rating each player started with. Fitted by Newton sweeps over the players.
2. **Game chance.** With rally chance q, P(win a game to 11) =
   Σ_{k=0..9} C(10+k, k) q¹¹ (1−q)^k + C(20,10) q¹⁰ (1−q)¹⁰ · q.
3. **Golden Game.** Exact race to 21 from the head start with the teams' rally chance, which
   uses the average of a team's five slot edges.
4. **Match.** The exact distribution of team A's points: convolve the 15 game chances, then for
   each Stage One score add the Golden Game from that head start. P(win) = P(A > 10.5 points).
   A team that wins 11+ Stage One games has clinched; the Golden Game matters only from 10-5
   to 5-10.
5. **Lineups (forecasts).** Each slot's edge is the games-weighted average edge of the players the
   team used there so far this season (last season's before the first match). Match forecasts
   average over a team-edge error (sd `team_rating_sd`, 3-point Gauss-Hermite).
6. **Standings plus** (`kind = "season"`). *Expected points*: per matchup, the team's actual rally
   share q in it → 3·P(game | q); Golden Game: the actual head start and the rally share of the
   Golden Game itself. Like Pythagorean wins, from rallies instead of runs. *Luck* = points −
   expected points. *11-10 record*: games decided by the golden point. *Strength of schedule*:
   the opponents' average edge (their Golden Game edge, i.e. all five slots), for played and
   remaining matches.
7. **Players** (`kind = "players"`). *Points above average* (PAA): per game, won (1/0) minus
   the chance an average MLTT player (edge 0) would have won against the same opponent(s); doubles
   half each. *Win probability added* (WPA): the change over each game in the chance of winning the
   match, read from a table for **evenly matched** teams (like baseball WPA: it measures how much a
   game mattered, not how hard it was); doubles half each; the Golden Game's swing (from its start
   to the result) shared equally by the players who rotated in. WPA sums to zero over the league;
   one unit = one match win.
8. **Season simulation.** The remaining regular-season matches `simulations` times. Each run
   draws an edge error per team (`team_rating_sd`) and draws each match's points from its exact
   distribution (errors rounded to `sim_grid_step`). Final Four by `playoff_rule`; semifinals
   (1st v the other division's 2nd) and the final are single matches. Ties in points % are
   broken at random.

## Assumptions and known weaknesses

- Rallies are independent: no serve advantage (MLTT serves alternate every two points), momentum, or
  fatigue. RESEARCH.md §5 checks 11-10 frequencies and Golden Game head starts against this.
- **Forecasts are weak.** MLTT games are close to coin flips between closely matched pros; walk-forward,
  the favourite won 60% of matches, and in the Season 4 test so far (34 matches) pre-match chances did
  no better than 50-50. The page says so.
- SPINDEX histories: 8 of 130 players have none (they start at average); some histories jump between
  events (start-of-event adjustments) and a few seeds are 0 (ignored). Season 2's history was entered in
  January 2025, so its seeds may have been set with part of that season known.
- Lineups are guessed from the season so far; injuries, rest and coach's choices aren't known.
  Game-level scores in RESEARCH.md use the actual players, match-level scores the guess.
- Men's and women's singles rarely meet (some cross-gender singles in Season 2, mixed doubles,
  the Golden Game), so the two groups' edges are tied together mainly by the shared MLTT rating
  scale.
- The Golden Game is played at a team's average edge; rotation order and who serves are ignored.
  Golden Game WPA is shared equally because the API gives each player's rallies won but not the
  rallies lost during their turns.
- No home advantage (weekends are at one venue, often hosted by one team); not tested yet.
- Season 1 (2023-24) is not in MLTT's results API.

## Variants

- `no_rating_prior`: results only, every edge pulled toward average.
- `current_rating`: today's SPINDEX rating as the prior (the v0.1.0 method, with its v0.1.0 scale). Fine for
  today's forecasts; hindsight when backtesting.

## Data

`fetch.py` (`ballmonitor fetch mltt`) reads MLTT's results site API (web.mltt.com/api: seasons,
schedules, matches, box scores, standings) and writes `data/matches.csv`, `games.csv` (one row per
Stage One game: players, points), `golden.csv` (rallies won by each player in each Golden Game),
`players.csv` (name, gender, MLTT rating as of the fetch), `teams.csv` (division),
`ratings_history.csv` (every player's SPINDEX rating changes, dated, from
spindex.mltt.com/api/public/players/<id>/rating-history) and `meta.json`
(including a check that our points totals equal the league's standings). Raw responses are cached in
`data/raw/mltt/`. The scheduled CI build (`[fetch] auto`, September–April) re-downloads only the
current season.

## Backtest data

`data/backtest.csv` (written by research.py): `season, date, stage, team_a, team_b, points_a,
points_b, winner`, one row per played match. `backtest_case` forecasts each with `as_of = date`
(only games from earlier days); scored on the winner (Brier, log loss, top pick).

### Results (RESEARCH.md; `ballmonitor compare mltt --variant no_rating_prior --variant current_rating --backtest`)

All 204 played matches, walk-forward (only earlier days' games, ratings as of that day):

| model | Brier | log loss | favourite won |
|---|---|---|---|
| default (dated rating prior) | 0.236 | 0.665 | 60.3% |
| results only (`no_rating_prior`) | 0.238 | 0.668 | 59.3% |
| today's rating (`current_rating`, hindsight) | 0.230 | 0.652 | 62.3% |
| coin flip | 0.250 | 0.693 | |

Season 4 test (34 matches, 7 weekends; tuned on Seasons 2-3): per game the dated prior helps (log loss
0.679 vs 0.687 results only), but pre-match match forecasts are no better than a coin flip yet (0.710 vs
0.693). The rally model fits well: 16.9% of games end 11-10 (it expects 17.2%).

## References

- MLTT format: https://www.mltt.com/format
- MLTT results/standings API behind https://www.mltt.com/results (web.mltt.com/api)
- Bradley-Terry / logistic rating models; Pythagorean expectation (Bill James); win probability added
  (Mills & Mills 1970; Tango, Lichtman & Dolphin, *The Book*, 2007).

## Changelog

- 0.2.0 (2026-11-22): the prior is the SPINDEX rating each player had at the time (dated rating
  histories, `rating_source = "dated"`), refitted scale (2620, 1180 points per unit of edge) and
  doubles_weight 0.5 from the hindsight-free study; v0.1.0's snapshot prior kept as `current_rating`.
  Status calibrated.
- 0.1.0 (2026-11-22): first version: rally edges with MLTT-rating prior, exact game/match/Golden Game
  arithmetic, standings plus (expected points, luck, schedule strength), PAA and WPA, season and
  Final Four simulation. Defaults from RESEARCH.md.

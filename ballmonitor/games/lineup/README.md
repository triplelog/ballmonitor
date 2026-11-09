# Lineup

A daily puzzle: nine real hitters, each from one season since 1955, one at every position
(C, 1B, 2B, 3B, SS, LF, CF, RF and a DH, who can be a season from any position). Together
they hit like a real team, not an all-star team. Put them in the batting order that scores the most runs.
One try. The score is exact, not one lucky season: your order's expected runs per game,
placed between the worst and the best of all 9! = 362,880 orders (100% = the best order).
After playing you can "play out a season" (random, 162 games) to see how much one season
swings. Archive of past days; progress kept in the browser (localStorage).

- `rules.toml`: the baserunning rates (league averages, the same for every runner) and game
  settings. Every puzzle file carries a copy, so the page and the build always agree.
- `chain.py`: expected runs for a batting order (below). `all_orders` scores all 362,880
  orders at once with numpy (~2.5 s).
- `players.py`: Lahman -> player-seasons since 1955 with at least 450 plate appearances and
  60% of games at one position; rates per plate appearance.
- `generate.py`: one puzzle per date, seeded by the date. Hitter types (`kinds`: star, walk
  machine, slugger, contact hitter, singles hitter, light hitter) are dealt to the positions
  (one star, a walk machine, two sluggers, a contact hitter, a singles hitter, two light
  hitters, one of anything), so each day mixes uneven profiles. Players are drawn weighted by
  the square root of Triple Play's fame score (25+, about 670 players). Of 300 deals, the
  kept one is realistic: the nine's average on-base and slugging fall inside the middle 80%
  of real team-seasons since 1955 (OBP .305-.343, SLG .355-.439); then the most typed
  hitters, then the closest to a median team. No player twice within 30 days. A day is
  redrawn when the best order beats the worst by less than 0.13 runs a game.
- `build.py`: writes `web/puzzles/daily/index.json` + one JSON per month (committed).
- `web/`: the game (vanilla JS). `chain.js` repeats chain.py's arithmetic step for step;
  `tests/test_lineup.py` runs both on the same lineups (with Node) and checks they match.

## The model

Each plate appearance ends as a strikeout, walk (or hit by pitch), single, double, triple, home
run or other out, with the hitter's own rates that season (plate appearances = AB + BB + HBP +
SF; sacrifice bunts are left out). Runners move by fixed league-average rates (`rules.toml`):

| play | rule |
|---|---|
| walk | forced runners move up |
| single | runner on 3rd scores; on 2nd scores 60% (else to 3rd); on 1st to 3rd 28% if 3rd is open (else 2nd) |
| double | runners on 2nd and 3rd score; on 1st scores 42% (else 3rd) |
| triple, home run | everyone scores |
| strikeout | nobody moves |
| out in play, < 2 outs | runner on 1st: double play 15% (others hold); otherwise runner on 3rd scores 50%, on 2nd to 3rd 30% if open, on 1st to 2nd 25% if open |

An inning is followed through all 24 base-out states until three outs (cut at 30 batters;
the chance left is below one in a million), which gives its expected runs and who leads off the
next inning. Nine innings make a game; a season is 162 games. No steals, caught stealing,
errors, wild pitches, bunts, pinch hitters, extra innings or skipped bottom of the 9th.

The baserunning rates are rounded league averages marked "DRAFT, verify" in `rules.toml`.

## Calibration

Each real team-season since 1955 run as nine copies of the team's own batting line: the
model scores about 5% less than the team really did (mean -4.7%, sd 3.7% over 264 team-seasons;
-3% to -6% in every decade). That is about what steals, errors and wild pitches are worth, which
the model leaves out. It shifts every order about equally, so the best order is not affected.

## How much the order matters

Over the 418 puzzles built (2026-11-09 to 2027-12-31) the best order beats the worst by a median
of 0.24 runs a game (39 a season; range 0.15-0.37) and beats a typical (median) order by 0.13
(22 a season). Every day's nine average inside the real-team band (medians OBP .335, SLG
.425); a typical order scores 4.65 runs a game in the model (about 4.9 for a real team, given
the 5% the model leaves out), against 4.4 for the median real team. 532 different players;
nobody more than 14 times. The DH is a fielder's season on 391 of 418 days.

Rebuild (after a rules change or a new Lahman release; Triple Play's README explains the
Lahman download):

    python -m ballmonitor.games.lineup.build
    python -m ballmonitor.games.lineup.build --keep-through <today>   # leave published days alone

Data: Lahman Baseball Database (CC BY-SA 3.0), SABR / Sean Lahman.

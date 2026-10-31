# Triple Play

A daily puzzle: three circles, 17 cards, one correct spot for each (1 in the middle,
2 in each two-circle overlap, 3 in each one-circle-only part, 1 outside). One check,
scored out of 17. Archive of past days; progress kept in the browser (localStorage).

- `web/` — the game (vanilla JS, no build step). Served at `/triple/` by `ballmonitor serve`
  and copied to `dist/triple/` by `ballmonitor build-site`.
- `facts.py` — Lahman database -> one facts record per player.
- `categories.py` — the circles: each has a published rule (`test`), a "clear" filter that
  keeps borderline players (e.g. a handful of games for a team, 60 games at a position) out
  of puzzles using it, a near-miss score for the outside player, and the fact shown on the
  answer card.
- `generate.py` — one puzzle per date, seeded by the date (rebuilding reproduces it).
  Difficulty by weekday (Mon/Tue easy, Wed-Fri medium, weekend hard) via a fame floor
  (All-Star selections, Hall of Fame, awards, career totals; pre-1946 careers discounted).
  Rejects near-duplicate circles, pitcher-only + hitter-only mixes, repeats of the same
  three circles within 120 days and any circle used the day before.
- `build.py` — writes `web/puzzles/daily/index.json` + one JSON per month.

Schedule: cities & states on Monday (MLB's traditional off day); baseball Tuesday (easy),
Wednesday/Thursday (medium), Friday/Saturday (hard), and Sunday's big puzzle: 25 cards
(2 in the middle, 3 per overlap, 4 per single circle, 2 outside; `NEED_BIG`). Difficulty = how famous the players are (fame floor) and how close they sit
to a circle's line (`Category.close`: 405 HR for "400 career home runs", 60 games for a team,
a switch-hitter for "batted left-handed"); each card is drawn with weight
fame x exp(CLOSE_BETA[level] x closeness), so easy days are clear-cut and hard days full of
close calls. The outside card is a near miss on medium/hard days.

## Cities & States pack (`places/`)

Metro areas (every market with a 2026 NFL/NBA/MLB/NHL/MLS/WNBA team, plus Hartford and
Quebec City), the campus towns of every SEC/Big Ten/ACC/Big 12 school and Notre Dame that
aren't in one of those metros (Tuscaloosa, Ann Arbor, Columbia MO/SC...), and the 50 states +
5 provinces with teams, on one board. A state counts
everything inside it. ~50 categories: which leagues (and how many teams), titles by decade
and by trophy, "never won a title", 10+ titles, first major-league team before 1920 / after
1990, NFL after 1990, lost a team to relocation, team names (bird, big cat, a color, not
ending in s, named for a state/region), Super Bowl / Olympics / 2026 World Cup hosts, SEC /
Big Ten / ACC / Big 12 schools, CFP/BCS football titles, NCAA basketball titles (men's or
women's), coasts, Great Lakes, borders Canada,
"is a capital city" (cities only), in Canada, and "is a state or province". (Place-name
categories were dropped: the name is on the card.) A category may cover cities only or
states only; the other kind just doesn't appear in that puzzle. Categories for one kind only
(e.g. "Borders Canada") leave the other kind out of that puzzle; places a fan could argue
either way (Seattle on the Pacific, Ohio's water border with Canada) are never used with
that circle (`DEBATABLE` in places/model.py).

Data: `places/data/*.csv`, built from Wikipedia list pages by
`python -m ballmonitor.games.triple_play.places.collect_teams` and `...collect_other`
(cached in `places/data/raw/`, gitignored); formats in `places/DATA_SPEC.md`, judgement
calls in `places/data/NOTES*.md`. Facts are for the 2026 season; titles through June 2026.

Rebuild (e.g. after a new Lahman release):

    python -m ballmonitor.games.triple_play.build --lahman ~/Downloads/lahman_1871-2025_csv.zip
    python -m ballmonitor.games.triple_play.build --start 2026-10-27 --end 2027-12-31

`--lahman` takes SABR's comma-delimited zip (sabr.org/lahman-database; its Box download
needs a browser) or the CRAN `Lahman_*.tar.gz` (needs `pip install rdata`). The current
puzzles were built from CRAN Lahman 14.0-0 (seasons through 2025). Raw data stays in
`data/raw/` (gitignored); the built puzzle files are committed so the site needs nothing else.

Data: Lahman Baseball Database (CC BY-SA 3.0), SABR / Sean Lahman.

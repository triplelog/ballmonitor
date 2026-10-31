# Places pack: notes on entities.csv, teams.csv, titles.csv

Built by `python -m ballmonitor.games.triple_play.places.collect_teams [--offline]` from cached
Wikipedia article pages in `data/raw/` (fetched October 2026). The script re-runs every check
below and exits non-zero if one fails.

## Counts

- entities.csv: 52 metros (50 with a 2026 team + Hartford + Quebec City), 50 states + 5 provinces.
- teams.csv: 199 current teams (NFL 32, NBA 30, MLB 30, NHL 32, MLS 30, WNBA 15) + 67 former
  metro stints (NFL 16, NBA 27, MLB 12, NHL 12).
- titles.csv: 472 (NFL 106 = 46 pre-Super Bowl + 60 Super Bowls, NBA 80, MLB 121, NHL 106,
  MLS 30, WNBA 29).

## Checks run

- Each current team appears once; league counts match the expected 2026 sizes (WNBA 15 per the
  WNBA page: "it will consist of 15 teams as of the 2026 season").
- One champion per league-season; every season from the first to the last completed one is
  present except the no-champion years: 1904 + 1994 World Series, 1919 + 2005 Stanley Cup.
  NFL 1966 has no row by design (Packers' 1966 title = Super Bowl I, listed as 1967).
  NHL 1925 is excluded (see below).
- Title totals agree with each page's own "records by franchise" table (MLB, NBA, MLS, WNBA);
  for NBA and WNBA the year lists also agree exactly.
- 10 random titles printed next to their page row and checked by hand: all correct
  (1981 Raiders, 2004 Pistons, 1975 Reds, 1980 Phillies, 1944 Canadiens, 2023 Crew,
  1973 Dolphins, 2006 Shock, 1955 Nationals, 2012 Fever).
- Every metro_id/state_id used in teams/titles exists in entities.csv; entity ids are
  identical to geo.csv, and colleges.csv/events.csv ids all resolve.

## Conventions / judgement calls

- **Ids**: metro ids are snake_case metro names; states snake_case, except `new_york_state` and
  `washington_state`. Their display names are "New York State" / "Washington State" so they
  can't be confused with the metros on a board.
- **DC** is not a state: teams in Washington, D.C. have a blank `state_id`, and the `washington`
  metro has a blank `state`. Landover-based rows (Commanders, Capital Bullets, 1978 Bullets
  title) use `maryland`.
- **Season numbers**: if a season spans two years, first_season_in_metro is the year it started
  and last_season_in_metro the year the last season ended (SuperSonics 1967-2008, as in the spec).
  Title `season` = year won; pre-Super Bowl NFL titles use the season year (1965 title game was
  2 Jan 1966; it is stored as 1965).
- **League seasons only**: NFL counts AFL seasons (the NFL adopted AFL history) but not the AAFC,
  so Browns and 49ers start in 1950, Packers 1921. NBA counts the BAA but not the ABA/NBL
  (Pacers, Nuggets, Spurs, Nets start 1976). NHL ignores the WHA (Oilers, Jets I, Nordiques,
  Whalers start 1979). MLB counts the AA (Cardinals, Reds, Pirates 1882; Dodgers 1884) but not
  the NA (Braves and Cubs start 1876).
- **Former stints** are kept when the team was still in that metro in 1950 or later, including
  teams that folded in 1950 (Anderson Packers, Sheboygan, Waterloo, Chicago Stags, St. Louis
  Bombers, Denver Nuggets I, 1950 Baltimore Colts). Rows in places outside the pack's metros
  have a blank metro_id but a state_id: Tri-Cities (Moline, IL), Rochester, Syracuse, Fort Wayne,
  Anderson, Sheboygan, Waterloo, Greensboro (Hurricanes 1997-99).
- **Temporary moves are ignored**: Hornets in Oklahoma City 2005-07, Raptors in Tampa 2020-21,
  Blue Jays in Buffalo/Dunedin 2020-21, Canadian MLS clubs in 2020.
- **Hurricanes**: first season in Raleigh is 1999 (they played 1997-99 in Greensboro), by
  analogy with the spec's Titans example (Memphis 1997 -> Nashville 1998). Both "lost" years are
  stored as separate stints (Tennessee Oilers, memphis, 1997; Hurricanes, no metro, 1997-1999).
- **Charlotte Hornets**: the 1988-2002 Charlotte stint of the franchise now in New Orleans is NOT
  listed. The NBA credits that history to the current Hornets (NBA team table "founded 1988*"),
  so the current Hornets row starts 1988 and the Pelicans start 2002. Same idea for the
  Browns: one row from 1950, even though the club was inactive 1996-98.
- **Arizona Coyotes** (phoenix 1996-2024) are a former stint; the Utah Mammoth are a new
  franchise from 2024 (NHL page: founded/joined 2024).
- **Athletics**: active row in `sacramento` from 2025 (West Sacramento, 2025-2027 per the spec);
  Oakland 1968-2024 is a former stint.
- **Connecticut Sun (2026)**: the WNBA page's team table has already been updated to the
  "Houston Comets" (relocation for 2027). The 2026 team row is hand-entered from the Connecticut
  Sun page ("Connecticut Sun 2003-2026", Uncasville/Montville, CT). Uncasville is not in the
  Hartford metro, so the row has a blank metro_id and state `connecticut`. Hartford stays a
  former-only market.
- **WNBA relocated teams**: Dallas Wings 2016 and Las Vegas Aces 2018 come from their team pages'
  history lines (hand-entered, verified against the cached text on each run).
- **San Jose Earthquakes**: first season 1996. The original club moved to Houston in 2006 but
  the records stayed in San Jose and the club returned in 2008; the 2006-07 gap is not shown.
- **Title state overrides** (team's venue was in another state than its metro's main state):
  Giants Super Bowls 1987/1991/2008/2012 -> new_jersey (Giants Stadium from 1976);
  1978 Bullets -> maryland (Capital Centre, Landover); 2013 Sporting KC -> kansas (Sporting Park).
  The 2000 Kansas City Wizards title stays missouri (Arrowhead); Devils titles are new_jersey.
- **Titles excluded on purpose**: AFL championships 1960-69 (not NFL titles); NFL champions
  1966-69 (their seasons are covered by Super Bowls I-IV); the 1925 Stanley Cup (won by the
  WCHL's Victoria Cougars, not an NHL team).
- **Not finished as of Oct 2026, left out**: 2026 World Series, 2026 MLS Cup, 2026 WNBA Finals
  (the WNBA champions page lists Golden State Valkyries vs Atlanta Dream at 0-0). Included:
  Super Bowl LX (Seahawks), 2026 NBA (Knicks, 4-1 over the Spurs), 2026 Stanley Cup (Hurricanes).

## Uncertainties

- The 2026 results (Knicks NBA title, Hurricanes Cup, Seahawks Super Bowl LX) and the 2026 team
  facts (Toronto Tempo, Portland Fire, Valkyries, San Diego FC, Utah Mammoth, Athletics in West
  Sacramento, Sun -> Houston in 2027) are taken from the pages as fetched. I had no second source.
- Metro assignment of suburbs is a judgement per DATA_SPEC (PLACE_METRO in the script).
- The rule "kept if still there in 1950 or later" pulls in several one-season 1949-50 NBA clubs;
  drop rows with `last_season_in_metro == 1950` if they turn out to be noise.
- The big-four relocations come from list pages: NBA (List of relocated NBA teams), NHL (List of
  defunct and relocated NHL teams), MLB (List of defunct and relocated MLB teams), NFL (NFL
  franchise moves and mergers + List of defunct NFL franchises). A relocation missing from those
  pages would also be missing here. I checked the NFL/MLB/NBA/NHL bullets on "Relocation of
  major professional sports teams in the United States and Canada" by eye against the output:
  no gaps.

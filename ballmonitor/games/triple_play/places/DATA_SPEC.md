# Places pack: data spec

The pack mixes **metro areas** and **states/provinces** on one board. Facts are compiled
from Wikipedia article pages (`https://en.wikipedia.org/wiki/...`; robots.txt allows
`/wiki/`, disallows `/w/` and `/api/` — do not use those), one request at a time with a
pause (>= 2 s), honest User-Agent `ballmonitor-games/0.1 (personal, non-commercial)`. Cache
raw pages in `places/data/raw/` (gitignored). Every CSV row carries a `source` URL.
"Current" means the **2026** season (NFL 2026, NBA/NHL 2025-26, MLB 2026, MLS 2026, WNBA 2026).
Do not guess: if a fact can't be confirmed from a cited page, leave it out and list it in
`places/data/NOTES.md`.

## Entities

`entities.csv`: `id, name, kind (metro|state), state, country (USA|CAN), source`

- States: all 50 US states + the District of Columbia (kind `state`, name "Washington, D.C."
  is NOT a state — DC is listed only as part of the Washington metro; do not add DC as a state).
  Provinces: Ontario, Quebec, British Columbia, Alberta, Manitoba (kind `state`).
- Metros: every metro area with a **current** team in the NFL, NBA, MLB, NHL, MLS or WNBA,
  plus two former-only markets: Hartford (Whalers) and Quebec City (Nordiques).
  Use one metro per market, named as fans say it, and put teams that play in suburbs in
  their metro:
  New York (incl. North NJ: Giants, Jets, Devils, Red Bulls, NYCFC, Liberty),
  Los Angeles (incl. Anaheim, Inglewood, Carson: Angels, Ducks, Rams, Chargers, Clippers, Galaxy, LAFC, Sparks),
  Bay Area (San Francisco, Oakland, San Jose, Santa Clara), Dallas–Fort Worth (Arlington, Frisco),
  Washington (incl. Landover MD), Boston (incl. Foxborough), Miami (incl. Sunrise, Fort Lauderdale),
  Phoenix (incl. Glendale, Tempe, Scottsdale), Minneapolis–St. Paul, Tampa Bay, Raleigh (Hurricanes),
  Salt Lake City, Sacramento (Kings; the Athletics play in West Sacramento 2025-2027 — record it, the
  generator treats it as borderline), Las Vegas, Green Bay, Buffalo, etc. Canadian: Toronto, Montreal,
  Vancouver, Calgary, Edmonton, Ottawa, Winnipeg. Ids: snake_case (`dallas_fort_worth`, `texas`).

## Pro teams

`teams.csv`: `league (NFL|NBA|MLB|NHL|MLS|WNBA), team (full name), nickname, metro_id, state_id,
first_season_in_metro, active (Y|N), last_season_in_metro, source`

- One row per team **per metro stint**: current teams (active=Y) and every franchise that left a
  metro or folded since 1950 for the big four (NFL/NBA/MLB/NHL), e.g. Seattle SuperSonics
  (NBA, seattle, 1967-2008), Hartford Whalers, Quebec Nordiques, Montreal Expos, St. Louis Rams,
  Oakland Raiders (both stints), San Diego Chargers, Brooklyn Dodgers (new_york, -1957). For MLS
  and WNBA only current teams are needed.
- `first_season_in_metro`: the first season that franchise played in that metro (Colts in
  Indianapolis: 1984; Titans in the Nashville metro: 1998, they played 1997 in Memphis).
- For metros with a big-four team before 1950 that is still there (e.g. Cubs), the first season is
  fine as is (1876 etc.).

## Championships

`titles.csv`: `league, season (year the title was won; e.g. Super Bowl LIX = 2025, NBA 2024-25 = 2025,
Stanley Cup 2024-25 = 2025), team, metro_id, state_id, source`

- NFL: Super Bowl winners (1967-) and pre-Super Bowl NFL champions 1920-1965.
- NBA (incl. BAA 1947-49), MLB World Series (1903-), NHL Stanley Cup since 1918 (NHL era),
  MLS Cup (1996-), WNBA (1997-).
- `metro_id` = where the team was based **when it won** (Minneapolis Lakers titles -> minneapolis_st_paul,
  Oakland A's -> bay_area, Baltimore Colts -> baltimore). Through the 2025-26 seasons that are complete
  as of October 2026 (Super Bowl LX Feb 2026, NBA/NHL June 2026, WNBA 2026 Finals if finished; the 2026
  World Series and MLS Cup are not finished — leave them out).

## Colleges

`colleges.csv`: `school, conference (SEC|Big Ten|ACC|Big 12), campus_city, metro_id (blank if the campus
is not in one of the metros), state_id, source` — membership for the **2026-27** academic year
(e.g. Texas and Oklahoma in the SEC; USC, UCLA, Oregon, Washington in the Big Ten; Stanford, Cal, SMU in
the ACC; Arizona, Arizona State, Utah, Colorado in the Big 12).

## Events

`events.csv`: `event (super_bowl|olympics_summer|olympics_winter|world_cup_2026), year, metro_id (blank if
not in a listed metro), state_id, venue, source`

- Super Bowl host stadiums I-LX (metro of the stadium).
- Olympic Games held in the US/Canada (St. Louis 1904, Lake Placid 1932 and 1980, Los Angeles 1932 and
  1984, Squaw Valley 1960, Montreal 1976, Calgary 1988, Atlanta 1996, Salt Lake City 2002,
  Vancouver 2010). LA 2028 has not happened: leave it out.
- 2026 FIFA World Cup host cities in the US and Canada (venue metro).

## Places

`geo.csv`: `id, coast_atlantic (Y/N), coast_pacific, coast_gulf, great_lakes, borders_canada (states only;
metros blank), capital (Y if the metro contains its state/provincial capital or is Washington; states blank),
source` — coasts: on the open ocean/gulf coastline (a state touches it; a metro has an ocean/gulf coast in
the metro); Great Lakes: borders/touches one of the five.

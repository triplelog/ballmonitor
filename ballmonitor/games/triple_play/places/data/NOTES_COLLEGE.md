# Notes: college_towns.csv, geo_college.csv, college_titles.csv (and colleges.csv metro ids)

Built by `python -m ballmonitor.games.triple_play.places.collect_colleges [--offline]` from cached
`/wiki/` pages in `data/raw/` (fetched 2026-10-27, >= 2.5 s apart, User-Agent
`ballmonitor-games/0.1 (personal, non-commercial)`). `collect_other.py` now also applies the town
ids when it rewrites `colleges.csv`, so either script gives the same file. The build stops if a
school with no metro has no town, if a parsed champion has no campus mapping, or if a sport-year
in range has no champion and no explanation.

## college_towns.csv (41 towns)

- One town per SEC / Big Ten / ACC / Big 12 (2026-27) school whose `colleges.csv` metro was blank,
  plus Notre Dame. No two such schools share a town, so nothing was merged (`schools` has one name).
- Names as fans say them: Oxford (Ole Miss; campus city listed as "University"), Starkville
  (Mississippi State; listed as "Mississippi State"), State College (Penn State; "University Park"),
  Champaign (Illinois; "Champaign-Urbana"), South Bend (Notre Dame; the campus is the
  census-designated place Notre Dame, Indiana, directly north of South Bend, per *Notre Dame, Indiana*).
- Disambiguated: `columbia_mo` "Columbia, MO", `columbia_sc` "Columbia, SC", and `manhattan_ks`
  "Manhattan, KS" (to avoid confusion with New York's Manhattan). Athens, Lexington, Fayetteville,
  Oxford, Bloomington, Lincoln, Lawrence keep the plain name (no clash on the board).
- Louisville and Syracuse are cities rather than "college towns", but they have no pro team metro
  in `entities.csv`, so they are included by the rule.
- Campuses already in a metro got no town (Oklahoma/Norman -> oklahoma_city, Duke and UNC ->
  raleigh, Maryland -> washington, etc.; see NOTES_OTHER.md). Boulder, Provo, Ann Arbor and
  Lawrence were blank (own MSAs) and now have their own towns.
- `source`: the conference page whose members table gives the campus; South Bend also cites
  *Notre Dame Fighting Irish football*.

## colleges.csv changes

- `metro_id` of the 41 blank rows now holds the town id; nothing else changed.
- **Notre Dame has two rows**: the existing `ACC` row (Notre Dame is a full ACC member in non-football
  sports and is listed in the ACC members table) and a new `Independent` row (football; the football
  page infobox says "Conference: Independent"), both with metro `south_bend`. `model.py` reads
  conferences as a set, so "Independent" only adds a value; no category uses it.

## geo_college.csv (41 rows)

- No college town is on an ocean/Gulf coast or a Great Lake, so all four flags are N;
  `borders_canada` is blank (metro rule). Near-misses are recorded in `coast_note`: Tallahassee
  (~20 mi from the Gulf; Leon County has no coastline), South Bend (~15 mi from Lake Michigan),
  Syracuse (~30 mi from Lake Ontario; Onondaga Lake is not a Great Lake), Madison (Lakes Mendota and
  Monona), Baton Rouge (Mississippi River, ~80 mi from the Gulf). These distances are approximate,
  judgement only (they don't change any flag).
- Capitals are checked against the parsed *List of capitals in the United States*: Y for Baton Rouge,
  Columbia SC, Lincoln, Madison, Tallahassee. **East Lansing = N**: it is a separate city next to
  Lansing (the capital); capital_note says so. Columbia, MO = N (capital is Jefferson City).

## college_titles.csv (236 rows: football 27, mbb 86, wbb 44, baseball 79)

Sources: *BCS National Championship Game* (seasons 1998-2013) and *College Football Playoff National
Championship* (2014-2025) "Game results" tables; *NCAA Division I men's basketball tournament*
"Titles by school" table (the page has no year-by-year champion table, so years are inverted from
it; the build checks there is exactly one champion per year); *NCAA Division I women's basketball
tournament* champions table; *College World Series* "Results" table.

- **Football `year` is the season** (2025 = Indiana, title game 19 Jan 2026), as the task states
  ranges by season. Basketball/baseball `year` is the year of the tournament. Note this differs from
  `titles.csv`, which uses the year the title was won.
- **Vacated titles are left out**: football 2004 (USC; vacated by the BCS, marked * on the page) and
  mbb 2013 (Louisville; vacated by the NCAA, marked * on the page). Both years have no row. Add them
  back if the game should count titles won on the field.
- **2020: no tournament** in mbb, wbb or baseball (canceled, COVID-19) - no rows. Football 2020 has
  a champion (Alabama).
- Checked: one champion per sport-year; every year in range has a row except the four vacated/2020
  gaps above. Pre-1998 football (no BCS/CFP) is out of scope.
- Campus -> metro/town/state (hand-entered in `CAMPUS` for non-power-conference schools; others use
  their `colleges.csv` row):
  - UConn (Storrs) -> no metro, `connecticut`, as instructed. Borderline: Storrs (Mansfield, Tolland
    County) is inside the Hartford MSA as Census defined it before 2023; kept blank as told.
  - Holy Cross (Worcester) blank (Worcester is its own MSA, not Boston); UTEP/Texas Western (El Paso),
    Wyoming (Laramie), Oregon State (Corvallis), Louisiana Tech (Ruston), Old Dominion (Norfolk),
    Fresno State, Wichita State, Coastal Carolina (Conway) -> blank metro, own state.
  - CCNY -> new_york; La Salle and Villanova (Villanova, PA, Philadelphia MSA) -> philadelphia;
    Loyola Chicago -> chicago; Marquette -> milwaukee; San Francisco -> bay_area; UNLV -> las_vegas;
    Rice -> houston; Cal State Fullerton (Orange County) and Pepperdine (Malibu) -> los_angeles.
  - Georgetown -> washington with `state_id` blank (D.C. is not a state; same convention as titles.csv).
  - Schools that changed conference keep their 2026-27 campus mapping (location doesn't change).
  - Oklahoma baseball titles (1951, 1994, 2026) -> oklahoma_city (Norman).
- Spot-checked (all match the pages and general knowledge): football 2010 Auburn, 2014 Ohio State,
  2025 Indiana; mbb 1947 Holy Cross, 1950 CCNY, 1966 UTEP, 1985 Villanova, 2024 UConn, 2026 Michigan;
  wbb 1982 Louisiana Tech, 2001 Notre Dame, 2026 UCLA; baseball 1992 Pepperdine, 2016 Coastal
  Carolina, 2026 Oklahoma.
- Names are as printed on the pages (e.g. "Miami (FL)", "UTEP" for the 1966 Texas Western title,
  "USC").

# Notes: colleges.csv, events.csv, geo.csv

Built by `python -m ballmonitor.games.triple_play.places.collect_other [--offline]` from cached
`/wiki/` pages in `data/raw/` (fetched 2026-10-27, 2.5 s apart, User-Agent
`ballmonitor-games/0.1 (personal, non-commercial)`). The script stops if a parsed school, host
city or Olympics edition has no hand mapping, so page changes can't silently drop rows.

Extra columns beyond DATA_SPEC.md: `colleges.short_name`, `events.city` / `events.edition`,
`geo.capital_note` / `geo.coast_note`. `model.py` ignores unknown columns.

## colleges.csv (68 rows: SEC 16, Big Ten 18, ACC 18, Big 12 16)

Membership, campus city and state come from each conference page's members table (current as of
fall 2026 = the 2026-27 year). Metro assignment is hand-entered judgement:

- Rule used: the campus is in the metro's city or the metro's own core metropolitan area (MSA).
- **Duke (Durham) and North Carolina (Chapel Hill) -> `raleigh`**: the Durham-Chapel Hill MSA is
  separate from the Raleigh MSA; both are in the Raleigh-Durham "Triangle" combined area, which is
  the Hurricanes' market. Borderline, kept as instructed.
- **Oklahoma (Norman) -> `oklahoma_city`**: Norman is in the Oklahoma City MSA (Cleveland County).
- **Maryland (College Park) -> `washington`**, **Northwestern (Evanston) -> `chicago`**,
  **Rutgers (New Brunswick/Piscataway) -> `new_york`** (Middlesex County, NY MSA),
  **Boston College (Chestnut Hill) -> `boston`**, **Miami (Coral Gables) -> `miami`**,
  **Arizona State (Tempe) -> `phoenix`**, **Stanford, California (Berkeley) -> `bay_area`**,
  **SMU (Dallas/University Park), TCU -> `dallas_fort_worth`**.
- Left blank (own MSA, only in a wider combined area): Colorado (Boulder; Denver CSA),
  BYU (Provo; Salt Lake CSA), Michigan (Ann Arbor; Detroit CSA), Kansas (Lawrence; Kansas City CSA).
  Also blank: Louisville, Notre Dame, Syracuse, Wake Forest, Penn State, etc. (no listed metro).

## events.csv (84 rows: 60 Super Bowls, 11 Olympics, 13 World Cup venues)

- Super Bowls I-LX: venue/city/year (game date) parsed from *List of Super Bowl champions*.
  City -> metro is hand-mapped: Pasadena/Inglewood -> los_angeles, Pontiac -> detroit,
  Stanford/Santa Clara -> bay_area, Tempe/Glendale -> phoenix, Miami Gardens -> miami,
  Arlington -> dallas_fort_worth, East Rutherford -> new_york (state `new_jersey`),
  Paradise -> las_vegas, Tampa -> tampa_bay.
- Olympics: host list parsed from *List of Olympic Games host cities* (US/Canada, opening date on or
  before 2026-10-27, so LA 2028 / Utah 2034 are excluded); venue = infobox "Stadium" on each Games
  page. Lake Placid (1932, 1980) and Squaw Valley (1960) are not in any metro: metro blank, state
  `new_york_state` / `california`. 2010 Vancouver -> `vancouver` (Whistler co-hosted). The 1980
  venue is the Lake Placid Equestrian Stadium (opening ceremony site per the infobox).
- 2026 World Cup: 13 US/Canada venues from the venues table (Mexico's three skipped). Kansas City
  is credited to `missouri` (Arrowhead Stadium is in Kansas City, Missouri).

## geo.csv (107 rows: 50 states + 5 provinces + 52 metros)

Hand-entered flags. State coast/lake/border lists were checked against the text of *East Coast*,
*West Coast*, *Gulf Coast of the United States*, *Great Lakes region* and *Canada-United States
border* (every flagged state is mentioned there). Capitals are checked against the parsed tables
of *List of capitals in the United States* and *Provinces and territories of Canada*.

- States: Atlantic = the 14 East Coast states (Pennsylvania excluded, Delaware estuary only);
  Connecticut counts (Long Island Sound). Great Lakes = the 8 US states + Ontario; Quebec = N
  (St. Lawrence only). Borders Canada = the 13 states incl. Ohio and Pennsylvania (water boundary
  in Lake Erie). Provinces: `borders_canada` blank (U.S.-only category). **Quebec Atlantic = N**
  (Gulf of St. Lawrence; "Atlantic Canada" excludes Quebec) - borderline. Hudson Bay coasts
  (Ontario, Manitoba) are not counted for any column.
- Metro coasts (borderline calls flagged in `coast_note`):
  - **Seattle and Vancouver Pacific = Y** though they face Puget Sound / Strait of Georgia, not
    open ocean (conventional "Pacific coast cities").
  - **New Orleans Gulf = Y** (conventional Gulf Coast city; metro parishes reach the Gulf);
    **Houston Gulf = Y** (Galveston in the metro); Tampa Bay Gulf = Y; Miami Gulf = N.
  - Baltimore, Washington, Philadelphia, Hartford, Portland, Orlando: no coast (bay/estuary/inland).
  - **Detroit Great Lakes = Y** (Detroit River; St. Clair County on Lake Huron) - borderline.
    Green Bay = Y (bay of Lake Michigan). Montreal, Quebec City, Ottawa = N.
- Capitals (metros): Y for Atlanta, Austin, Boston, Columbus, Denver, Hartford, Indianapolis,
  Minneapolis-St. Paul, Nashville, Oklahoma City, Phoenix, Raleigh, Sacramento, Salt Lake City,
  Edmonton, Quebec City, Toronto, Winnipeg; national: Washington, Ottawa.
  **Baltimore = N** although Annapolis is in the Baltimore MSA (Anne Arundel County) - borderline.
- The metro list is the spec's list plus the obvious team markets; if `entities.csv` adds a metro
  id not in `METROS` (collect_other.py), add a geo row for it.

**Update:** schools with no metro now point at a campus-town id from `college_towns.csv`
(built by `collect_colleges.py`; see NOTES_COLLEGE.md). Notre Dame also has an `Independent` row.

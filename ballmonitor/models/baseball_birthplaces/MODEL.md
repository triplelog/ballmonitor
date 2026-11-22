# Where baseball players come from (`baseball_birthplaces`)

**Question:** Per million people, how many big-leaguers (and how many home runs, hits, wins...)
were born around each place, decade by decade?

**Status:** draft. These are descriptive maps with no forecast, so there is nothing to backtest.

## Inputs (CLI / `predict`)

| input | meaning | example |
|---|---|---|
| `place` | a label for the output | `"San Pedro de Macorís, D.R."` |
| `lat`, `lon` | the spot | `18.4539`, `-69.3086` |
| `decade` | birth decade (any year in it) | `1980` |
| `region` | instead of a place: an area's corners `[[lat, lon], ...]` (all decades) | see `examples/region_*.toml` |
| `name` | (region) a label | `"Dominican Republic"` |

Examples: `default` (San Pedro de Macorís, 1980s), `st_louis_1920s`, `home_runs_la_1950s` (run with
`--set 'formulas.value=HR'`). The public page computes the same value for every map cell in the
browser (`web/static/apps/birthplace_map.js`).

## Method

1. **Birthplaces.** Each Lahman player's birth city, state/province and country is matched to
   GeoNames (`geocode.py`). It uses the full country files for the Americas, every populated place
   (including historical and abandoned towns), and alternate names for renamed towns. When no town
   matches, a county or military base of that name is used. Among places with the same name, the
   one in the player's province wins, then the biggest. 22,560 players are placed. 1,710 are left
   off (`data/unplaced.csv`):
   - 1,130 have no recorded birthplace
   - 367 were born outside the Americas
   - 166 have a place that matches nothing
   - the rest have no birth year
2. **Decade.** A player belongs to his birth decade (`first_decade` 1840 also takes the few born
   earlier). The population used is the decade's middle year (1925 for the 1920s), clamped to the
   grid's 1850–2021.
3. **Frames.** The main map (lower 48, southern Canada, northern Mexico, the Caribbean, the
   Venezuelan coast), Alaska and Hawaii each have their own spherical Lambert azimuthal
   equal-area projection (`frame_*`: centre plus a lat/lon box). Distances inside a frame are
   within a few percent of true. Map cells are `cell_km` = 20 km.
4. **Circles, exactly one million.** The population grid is gathered into `pop_cell_km` = 10 km
   cells in the frame's projection, placed so every map cell's centre is a population cell's
   centre, with a margin of `max_radius_km`.
   1. A ladder of radii (`min_radius_km` to `max_radius_km`, each `radius_step` = 6% bigger) is
      tried with a disk convolution. This brackets the radius where the circle reaches `people` =
      1,000,000.
   2. Bisection (`exact_iterations` = 16) narrows the radius. It counts people with chord sums row
      by row (partial cells by the fraction covered), the same count that is stored.
   3. The population inside the stored circle is saved too (`grid/<decade>_<frame>_people.png`, in
      units of 50). Every sum is multiplied by 1,000,000 / that population, so map values are
      exactly per million even when a dense 10 km population cell makes the count jump past one
      million at some radius.

   With bisection, 98% of circles hold 0.997-1.002 million people (1920s) and 0.988-1.006 million
   (1990s); the scaling corrects the rest. A cell with fewer people within `max_radius_km` = 1,200
   km gets no circle (blank). These are Alaska and Hawaii in early decades.
5. **Spread of a birthplace.** A player is spread evenly over a disk of radius `spread` =
   `min(sqrt(place_pop / (pi * city_density)), max_spread_km)`. Here `place_pop` is the
   birthplace's GeoNames population. He counts in a circle by the share of that disk inside it
   (the area of intersection of two circles). Without this, everyone "born in Los Angeles" sits on
   one downtown point, and a 19 km circle there holds a million people but every LA birth.
6. **Map value.** For each cell: the players for whom formula `include` is non-zero, weighted by
   their share, give a sum of every career number (`engine.STATS`: G, AB, H, HR, W, K, AS, HOF...)
   and `players` (the weighted count), scaled per million (step 4). Formula `value` turns these
   into the cell's number. A value that can't be computed (0/0 with no players) leaves the cell
   blank.
7. **Several decades in one formula.** A plain name (`HR`) is the decade being shown. A name with a
   decade (`HR_1910`, `players_1980`) is that decade's sum, in that decade's own million-person
   circle around the same spot, so `HR_1980 / HR_1910` compares per-capita rates across eras.
   These names are allowed by the formula's `variable_pattern`. A cell blank in any decade the
   formula uses is blank. The page loads only the decades a formula names (about 400 KB each).

## Drawn areas (`region` input; the page's "Draw a region")

Any polygon in one frame (corners in lat/lon on the CLI, clicks on the page), no circles needed:

- **Population per decade.** `grid/<decade>_<frame>_pop.png` holds the people in each 20 km map
  cell, log-encoded (`round(log1p(people) x 4000)`, 0.025% steps). The 10 km cells are shared
  between map cells with tent weights, so totals are kept. Each cell counts by the share of its
  4x4 sample points inside the polygon.
- **Players.** Each player counts by the share of his birthplace disk's 19 sample points (centre
  plus rings of 6 and 12) inside the polygon. A town is one point.
- **Values.**
  - Per decade: formula `value` on the sums per million people living there then. `HR_1910` etc.
    work as on the map.
  - All decades together: every decade's births divided by that decade's population, i.e. per
    million people per decade.
- **On the page.** Several areas can be drawn and named. The page shows a comparison table
  (people, big-leaguers, per million, the value formula, Hall of Famers, All-Star picks, the
  player with the most games), a decade-by-decade chart and each area's players. Drawing loads
  every decade once (about 1.5 MB compressed).
- **Examples.** `region_dominican_republic` gives 930 big-leaguers, against 939 listed as born in
  the D.R. (the rest are outside the rough outline or unplaced). `region_southern_california`.

## Data

`fetch.py` (by hand, `ballmonitor fetch baseball_birthplaces`; needs `pip install -e '.[maps]'` for
h5py, and the Lahman CSVs from Triple Play's raw folder) downloads into `data/raw/` (gitignored, about
2.6 GB):

- **ISIMIP3a `population_histsoc_5arcmin_annual_1850_1900.nc` and `..._1901_2021.nc`**
  (files.isimip.org). This is historical gridded population derived from HYDE 3.2 (Klein Goldewijk
  et al. 2017) and scaled to national totals. The license of this dataset is not stated on the
  file server; verify (ISIMIP's site is CC BY 4.0).
- **GeoNames country files and `admin1CodesASCII.txt`** (CC BY 4.0).
- **Natural Earth 1:50m admin 0 / admin 1 shapefiles** (public domain).

It writes, committed:

- `players.csv`: placed players, birthplace, `place_pop` and career totals
- `unplaced.csv`
- `grid/<decade>_<frame>.png`: the circle radius per cell in 0.1 km, R = high byte, G = low byte;
  0 = water, 65535 = no circle. About 1.5 MB in all.
- `grid/meta.json`
- `borders.json`

The page's files (`site.py` `files()`) are written by the site build to
`/data/files/baseball_birthplaces/`, and the page loads one decade at a time (about 300 KB).

## Assumptions and known weaknesses

- **Birthplace, not hometown.** Players are counted where they were born, not where they grew up.
  Lahman has a birth city only.
- **Coarse city populations.** The population grid is HYDE-based and spreads cities over 5'
  (about 9 km) cells. With 5 km or 10 km gathering the same circles result (NYC 1925: 15 km where
  real 1920s density suggests about 7 km), so dense cores look emptier than they were. Small towns
  before 1950 are the least certain.
- **`place_pop` is today's population.** A city that was small when a player was born (LA in
  1905) is spread wider than it was. `city_density` is a DRAFT assumption (3,000 per km²).
- **Long careers dominate.** Career totals count a whole career, whenever and wherever it was
  played.
- **The last decade is incomplete.** The 2000s have only about 300 players so far.

## Variants

None yet. Try `--set city_density=…`, `--set max_spread_km=0` (pin players to points),
`--set people=500000`.

## Backtest data

None: descriptive.

## References

- Klein Goldewijk, K., Beusen, A., Doelman, J., Stehfest, E. (2017). Anthropogenic land use
  estimates for the Holocene, HYDE 3.2. *Earth Syst. Sci. Data* 9, 927–953.
- ISIMIP3a input data, socioeconomic, population histsoc (files.isimip.org).
- GeoNames (geonames.org), CC BY 4.0. Natural Earth (naturalearthdata.com), public domain.
- Lahman Baseball Database (SABR), CC BY-SA 3.0.

## Changelog

- 0.1.0 (2026-11-22): first version.

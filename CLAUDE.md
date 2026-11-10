# CLAUDE.md — ballmonitor

A collection of **simple, open, fully-tweakable models** that predict probabilities and
estimates for sports events (college and pro football, baseball, basketball, running races,
awards and polls), plus the sports games on the same site. Split out of `~/Desktop/projects/modelstuff` on
2026-10-30, which keeps the non-sports and retired models. Three promises
drive every decision:

1. **Uniform output.** Every model returns the same `Prediction` object and is rendered by
   the same code, so all outputs look alike (text, markdown, JSON).
2. **Everything is tweakable.** Every weight, constant and swappable formula lives in the
   model's `config.toml`, never hard-coded in Python. Users change them with `--set`,
   variant files, or by editing the config.
3. **Everything is documented.** Every parameter has a description and source; every model
   has a `MODEL.md` with its method, formulas, assumptions and weaknesses; every output
   prints the steps it took, the parameters used, and the key assumptions.

Prefer simple, explainable models over accurate black boxes. If a choice is between a
clever method and one a user can follow and tweak from the docs, choose the latter.

## Layout

```
ballmonitor/
  cli.py                  `ballmonitor` command (list, params, run, compare, backtest, new, serve)
  web/
    server.py             browser UI backend: stdlib http.server + JSON API (127.0.0.1:8765)
    static/               site.html/site.js/site.css = public page; index.html/app.js/style.css = editor (vanilla JS)
  core/
    config.py             load config.toml → apply variant → apply --set overrides
    params.py             ParamSpec / FormulaSpec / Params (attribute access + p.formula())
    formula.py            safe evaluator for config formulas (AST whitelist, no eval)
    prediction.py         Outcome + Prediction: the ONLY output type
    render.py             ALL output formatting lives here (text / md / json / compare / backtest)
    model.py              BaseModel: predict(), backtest_case(), score(), prediction() helper
    backtest.py           score a model against data/backtest.csv
    registry.py           discover/load models, examples, variants; scaffold new models
    views.py              public-site page format: page/table/col/bar/line/picker + check()
    stats.py, units.py    shared helpers (normal CDF, softmax, fits; time/distance parsing)
  models/
    _template/            copied by `ballmonitor new <name>`
    <name>/
      config.toml         [meta] + [params.*] + [formulas.*]   ← the tweakable surface
      model.py            exactly one BaseModel subclass
      MODEL.md            method, formulas, assumptions, data format, references, changelog
      examples/*.toml     input sets; `default.toml` is used when none is given
      variants/*.toml     named parameter/formula tweaks
      data/backtest.csv   historical cases (optional; columns documented in MODEL.md)
      site.py             optional: `page(model)` (or `pages(model)`) → the public page's pre-generated tables/charts (core/views.py)
      fetch.py            optional: `fetch(model_dir, offline)` downloads/builds data → `ballmonitor fetch <name>`
      research.py         optional: reproducible study → RESEARCH.md (generated, never hand-edited)
      test_model.py       model-specific tests
tests/
  test_core.py            framework tests
  test_contract.py        rules every model must pass (auto-discovers models)
  test_web.py             API tests for the browser UI
ROADMAP.md                planned models and ideas
attic/ballmonitor-2019/   saved code from the 2019 Ball Monitor site (not wired in; see its NOTES.md)
```

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,data,ml,ingest]'   # once (`video` for export-replay)
source .venv/bin/activate

ballmonitor list                                   # models, status, examples, variants
ballmonitor params race_time                       # every param/formula with docs + source
ballmonitor run race_time                          # examples/default.toml
ballmonitor run race_time --example one_race --format md
ballmonitor run race_time --in target=half --set riegel_exponent=1.08
ballmonitor run race_time --set 'formulas.predict=t * (D / d) ** 1.08'
ballmonitor compare race_time --variant curve_v04 --variant pure_riegel [--backtest]
ballmonitor backtest race_time --variant curve_v04 [--data other.csv]
ballmonitor new nfl_win_totals --title "NFL win totals"
ballmonitor serve                                  # browser UI at http://127.0.0.1:8765 (27K game at /27k/)
ballmonitor build-site --out dist                   # static bundle (GitHub Pages); CI runs update-and-build daily
ballmonitor views ncaaf_bowls [--out x.json]       # build + check one model's public page
ballmonitor tables [--check]                        # live data tables (web/tables.toml); --check asks their servers
python -m ballmonitor.data_tables.build [--only nba]  # CSVs for the QB / NBA / WNBA data tables (raw/ + csv/ gitignored)
ballmonitor update-and-build [--models ncaaf_bowls]  # fetch the models that are due ([fetch]), rebuild the whole site
ballmonitor fetch mlb_bullpen [--offline]          # download/rebuild a model's data
ballmonitor export-replay --game 401858275 --out x.mp4   # cfb_replay → vertical MP4 (needs `pip install -e '.[video]'` + ffmpeg)

pytest                                            # all tests (core + contract + every model)
pytest ballmonitor/models/race_time                # one model
```

## How a model is built (the contract)

- **config.toml**
  - `[meta]`: `title`, `version`, `status` (`stub` | `draft` | `calibrated`), `question`
    (one sentence), `description`, `assumptions` (plain-language list — printed with every run).
  - `[params.<name>]`: `value` (required), `description` (required), `unit`, `source`
    (citation, or "Judgement", or "DRAFT … verify"), `range = [lo, hi]` or `choices = [...]`.
    Range/choices/type are enforced on every override.
  - `[formulas.<name>]`: `expr`, `description`, `variables` (names model.py passes in).
    All numeric params are automatically available in every formula by name.
    Allowed syntax: arithmetic, comparisons, `a if c else b`, and the functions in
    `core/formula.py` `FUNCTIONS`. Add a function there if a model genuinely needs one.
  - `[fetch]` (optional, needs `fetch.py`): `auto = true` + `season = ["MM-DD", "MM-DD"]`
    (inclusive, may wrap the new year) makes the scheduled CI build (`update-and-build`) run
    fetch.py inside that window. Leave it out when fetch.py needs the local `data/raw/` cache
    (CI has none, so it would re-download everything) or the data is historical; those models
    are refreshed by hand (`ballmonitor fetch <name>`) and their built data committed.
- **model.py**
  - Read every tunable number from `self.params` (`p.fit_weight`). **No magic numbers.**
    Physical/definitional constants (meters per mile) are fine in `core/units.py`.
  - Where a user might reasonably want a different formula, compute it with
    `p.formula("name", **vars)` instead of Python.
  - Append a readable line to `steps` for each meaningful calculation; include the
    formula expression (`p.expr("name")`) and intermediate values.
  - Return `self.prediction(inputs=..., outcomes=[Outcome(...)], steps=..., interval_level=..., extras=...)`.
    `inputs` is a display dict; `extras` holds machine-readable intermediates for tests.
  - The **first outcome is the primary one** — backtests score it by default.
  - Outcome fields: `estimate` (+ `interval`) for numbers, `probability` for events,
    `fmt` ∈ `number | int | pct | time | currency | points`, `group` for table sections, `note`.
  - Implement `backtest_case(row) -> (inputs, actual)` to enable backtesting. Numeric
    `actual` → error metrics + interval coverage; string `actual` (the label of the outcome
    that happened) → Brier, log loss, top-pick accuracy. Override `score()` for anything else.
  - Monte Carlo models: take `simulations` and `seed` as params and use `random.Random(seed)`
    so runs are reproducible.
- **MODEL.md**: question, inputs table, method (step by step, naming each config formula),
  assumptions & known weaknesses, variants, backtest CSV columns, references, changelog.
- **Tests**: `test_model.py` checks known values (hand-calculated cases), that overrides
  move results the expected direction, and edge cases. `tests/test_contract.py` checks
  documentation, examples and output shape for every model automatically.

## Rules for changes

- **Never format output inside a model.** If the standard layout can't express something,
  extend `Outcome`/`Prediction` and `render.py` so every model benefits. Keep text width at 78.
- Changing a default value or formula in `config.toml` is a model change: bump `meta.version`,
  add a changelog line in `MODEL.md`, and update the param's `source`. Prefer adding a
  **variant** for experiments and only promote it to the default after a backtest.
- `status = "calibrated"` only when `data/backtest.csv` exists and the backtest results are
  summarised in MODEL.md. Uncalibrated models stay `draft`.
- **Data:** raw downloads go in `data/raw/` (gitignored); built, documented CSVs in `data/`. Backtest
  rows must contain only information known at the start (mind publication lags). Evaluations of
  fitted rules must be walk-forward/out-of-sample, report the number of *independent* periods, and
  flag any hindsight benchmark. Defaults chosen from a study cite it in `source`.
- Do not invent data. Example inputs that aren't real must be labelled as placeholders;
  draft parameter values whose source isn't verified must say "DRAFT … verify" in `source`.
- Keep the core stdlib-only. A model may add a dependency only if it's clearly worth it;
  add it to `pyproject.toml` and note it in that model's MODEL.md.
- Model directories are snake_case; the model class is the CamelCase name + `Model`.
- Run `pytest` after any change; the contract tests catch missing docs and output drift.

## Public site (ballmonitor.com)

- Made for fans, not analysts: each model's page is a few **pre-generated** tables/charts from its
  `site.py` (`page(model)` built with `core/views.py`), written to `data/views/<name>.json` by
  `build-site`; `site.js` only displays them (search, sort, "show all", bars, line charts,
  dropdown pickers). Nothing is computed in the browser. Home index: `data/site.json`.
- **Addresses are real paths** (`/ncaaf_bowls/`, `/ncaaf_bowls/team/georgia/`, `/tables/<id>/`,
  `/charts/<id>/`, `/about/`), not `#/` routes, so search engines see every page: `build_pages`
  (`web/pages.py`) writes a copy of site.html at each one with its own title, description, canonical and
  share tags and the page's words (headline, option links, "How this works") already in `<main>`;
  `site.js` then draws the page and follows links between pages without reloading (History API).
  Old `#/` links are turned into paths on arrival; `REDIRECTS` get stub pages. `sitemap.xml` lists every
  address. Page addresses may not use the site's own first parts (`pages.RESERVED`).
- **Page weight:** a page whose JSON is over 150 KB (`builder.SPLIT_BYTES`) has each top-level picker
  option's views written to `data/views/<address>/<picker>/<slug>.json` (`src` on the option); `site.js`
  fetches one when it's shown. `builder.load_page` reads a split page back whole (tests).
- **Head and assets:** every page shares `static/share.png` (1200×630; source `web/share-card.html`, render
  it with headless Chrome) as its link-preview image; the games' copied pages get the same tags at build
  time (`GAME_META`, their sources untouched). Fonts are self-hosted (`static/fonts.css` + `static/fonts/`,
  Latin + Latin Extended, OFL), no Google Fonts. `/static/*.css|js` links in the built pages carry
  `?v=<content hash>`. `editor.html` is titled "Model editor" and `noindex`.
- **Text pages** `/about/`, `/privacy/`, `/terms/`: HTML fragments in `web/pages/*.html` (claude-ui
  markers, on Claude UI's Content page), linked from the footer on every page. Keep `privacy.html`
  true to what the site sends where (hosts, fonts, table server, jsDelivr, local storage).
- One model can feed several pages: `site.py` defines `pages(model) -> {address: page}` instead
  of `page(model)` (e.g. `college_diamond` → `/college_baseball/` and `/college_softball/`), with
  text in `site_<address>.md`; old addresses go in the module's `REDIRECTS` (`site.js` follows them).
- **Which models are on the site:** `[web] public = false` in a model's config.toml keeps it off
  the static build (no page, not in the editor; still in the CLI, `serve` and tests). Off for now
  (2026-11-08, owner's call): the MLB models (`next_pitch`, `bvp_similarity`, `mlb_bullpen`),
  `cfb_replay` (until there's a YouTube Shorts account), `race_podium` and `dad`. The Pitch Guesser
  game is off too (not copied into `dist/`, no links; still at `/game` under `serve`).
- **Live data tables** (`web/tables.toml`, `web/tables.py`): big CSVs served by tabdn table servers
  (tabc/sqldn, ~/Desktop/portfolio/mathzetta/tabdn) get a page at `/tables/<id>/` with a live
  filter/sort table. The one exception to "nothing computed in the browser": the *server* filters
  and sorts; `site.js` loads tabview's embed from `<server><path>web/vendor/tabview-embed.js` and
  mounts it with the advanced controls hidden (adding columns, stats, groups) and `[table.labels]`
  as the headers (`labels`/`timing` need tabview from 2026-11-10 on the server). A table whose `[servers]` address is blank stays off the site. `ballmonitor tables
  [--check]` lists them and asks each server for its columns (and flags names in the config it lacks).
  `ballmonitor/data_tables/build.py` makes the CSVs for the QB, NBA and WNBA tables (nflverse,
  SportsDataverse/ESPN; see its README for licenses and the upload steps).
- **Baseball charts** (`/charts/`, `/charts/<id>/`): pyslots' embeddable form (Python chart
  templates with formula slots, ~/Desktop/portfolio/mathzetta/pyslots) and its chart templates and Lahman
  data, copied into `ballmonitor/charts/` by `scripts/sync-charts.sh` (committed, so CI needs nothing
  outside this repo; never edit them here) and to `dist/charts/` by the build. The second exception to
  "nothing computed in the browser": the visitor's formulas fill a matplotlib program that runs in their
  browser (Pyodide, from jsDelivr on the first run, a few seconds). `tests/test_charts.py` checks every
  listed template has its data and its title/axis slots. Which charts the page offers is `web/charts.toml` (`web/charts.py`): a
  plain name, an intro and starting formulas per chart, so one template gives several charts; grouped
  buttons at `/charts/<id>/`; checked by `tests/test_chart_pages.py`; on Claude UI's Content page. MathZetta's home links this page (mathzetta-sites'
  registry, `external`).
- In `dist/`, `index.html` is the public page and `editor.html` the (read-only) editor below,
  linked from each page's "How this works".
- Page rules: plain words (no internal stat names), ≤ ~8 table columns, real committed data only
  (CI has no `data/raw/`), off-season pages labelled as final, no private people's names,
  ≤ 60 s and ≤ ~1.5 MB per page. Page-only tunables are `site_*` params in config.toml.
  `views.check` runs on every build and in tests; a failing page fails the build.
- Page text the owner edits lives outside code: each model's `site.md` (marked `title`/`summary`/
  `how` sections, overriding site.py; `{placeholders}` come from `page(fill=...)`; `site_<address>.md`
  for multi-page models) and the home page
  / sidebar `<template>`s and meta tags in `site.html`. These are registered on Claude UI's
  Content page (project "ballmonitor"); when adding a model page, add its site.md and register it.
- Every page leads with a data-driven `headline` (`page(headline=...)`), and picker options with an
  `intro` one-liner: the one answer a fan wants first. Tables keep their name column in place when
  scrolled sideways (`col(sticky=True)`, default: first linked, else first text column).
- Pickers double as sub-pages: each option has an address `/<model>/<picker id>/<slug>/` (e.g.
  `/ncaaf_bowls/team/georgia/`), and a table column with `link="<picker id>"` links its cells there.
- Preview: `ballmonitor build-site --out /tmp/site && python3 -m http.server -d /tmp/site 8790`.
- Look: **Shioh style** (`static/shioh-style.css` is the unchanged Shioh base, update it by replacing
  the file; theme overrides and page-specific pieces in `site.css`; phone menu/toasts in `shioh.js`): pastel cells on black, sidebar + main column, Montserrat/Open Sans. Each sport
  owns one cell colour (`SPORT_CELL` in core/views.py, sent to site.js in data/site.json). The build also writes `robots.txt`,
  `sitemap.xml` (every page address + `GAME_PATHS` in builder.py) and copies the Shioh `404.html`. The editor and
  the games keep their own styles.

## Browser UI (`ballmonitor serve`)

- Shows every model; edits inputs (TOML), parameters (slider/field per param, with
  description, range, default and source) and formulas; auto-runs and shows the same
  text report as the CLI, plus Markdown / JSON / Docs (MODEL.md) / Backtest tabs.
  "Pin baseline" shows how each outcome moved after edits.
- Edits are sent as the same variant + `--set` override layers the CLI uses, so anything
  in the UI is reproducible from the command line.
- Saving writes only `variants/<name>.toml` and `examples/<name>.toml`. It never edits
  `config.toml` — promoting a variant to the defaults stays a deliberate change (see rules).
- The UI is generic: it builds editors from `config.toml`, so new models need no UI work.
  Param control is chosen from the default's type: number (+ slider if `range`), `choices`
  → dropdown, bool → checkbox, list/string → text field.
- Config/variant/example files are re-read on every request; changes to a model's Python
  need a server restart.
- Keep it stdlib + vanilla JS (no frameworks, no build step).
- A model's `config.toml` may have a `[web]` table with `hidden_examples` / `hidden_params`:
  research-only pieces that stay in the CLI, data and tests but are not shown on the site, and
  `public = false` to keep the whole model off the published site.
- The same page also runs as a **static site** (`build-site` → `dist/`): it uses live mode only when
  `/api/models` answers, otherwise it shows the precomputed result for each example and makes every
  editor read-only. Never fake a model client-side. The build fails if any example can't be computed.

## Dev servers

This machine runs Claude UI at http://127.0.0.1:3131, which keeps a Servers page. The UI
server is registered there as "ballmonitor · model editor" (port 8765). When you add,
rename or change how a server in this project starts, register it: fetch
http://127.0.0.1:3131/docs/agent-instructions.md and follow it (POST /api/servers/register).

## Typical workflows

**Tweak and test a model:** in the browser UI, pin a baseline, adjust, save as a variant — or
on the CLI: `ballmonitor params X` → try `--set` on `run` → save the tweak as
`variants/<name>.toml` (with a `description`) → `ballmonitor compare X --variant <name> --backtest`
→ if better, promote to `config.toml` (version bump + changelog).

**Add a model:** `ballmonitor new <name>` → fill `config.toml` (params, formulas, assumptions)
→ write `MODEL.md` → implement `predict` → add `examples/default.toml` → write `test_model.py`
→ `pytest` → add backtest data if available.

**Build out a stub:** stubs (status `stub`) have a plan in MODEL.md and draft params. Verify
the draft values, implement `predict`, add examples, flip status to `draft`.

## Current models

| model | status | approach |
|---|---|---|
| `race_time` | calibrated | weighted average of Riegel predictions from all the runner's races (b 1.09 M / 1.06 F) + empirical 50/80/95% bands from 2,560 runners' real errors; old curve method as variant `curve_v04`; see RESEARCH_BANDS.md |
| `race_podium` | calibrated | recency/field-weighted prior editions shifted to expected field size + cross-division prior + per-place fitted sigma; walk-forward on 397 editions; see RESEARCH.md |
| `next_pitch` | calibrated | per-pitcher recency-weighted context tree (Aaronson-style) + shared LightGBM correction; see RESEARCH.md |
| `bvp_similarity` | calibrated | regressed log5 platoon baseline + similar-player pool + count micro-sim, empirical-Bayes blend; tuned on 2025, tested on 2026; see RESEARCH.md |
| `mlb_bullpen` | calibrated | Monte Carlo game sim (conditional-logit reliever choice fitted on 2025 calls), recalibrated and blended with a direct per-reliever logistic model, plus expected bullpen runs vs average; trained 2025, tested 2026; see RESEARCH*.md |
| `ncaaf_bowls` | draft | ESPN FPI + full live schedule (`fetch.py`) → season Monte Carlo → 2026 12-team CFP + 2026-27 bowl tie-ins |
| `ncaaf_recruiting` | calibrated (football) | Plackett-Luce offer Elo → rank-decayed class scores + projected 4-season SRS; walk-forward vs consensus rankings; basketball unvalidated |
| `dad` | calibrated | opponent-adjusted margin strength vs a chosen default team in σ (shrunk) + result-based wins above default (WAD); real ESPN/football-data seasons; see RESEARCH_STRENGTH.md |
| `college_diamond` | calibrated | D-I baseball & softball: run-margin ridge ratings (compressed margins, last-season prior) → rest-of-season + conference-tournament + RPI-committee + NCAA bracket Monte Carlo; see RESEARCH.md |
| `cfb_replay` | draft | ESPN play-by-play + ESPN win probability → 60 s vertical replay: WP chart down the left, ~14 annotated plays (every score + biggest swings) revealed one by one on the right, time axis warped to fit them (variants: `chapters`, `plays_only`); rendered by web/static/replay.js; `ballmonitor export-replay` → MP4 |
| `ranked_choice` | draft | published ranked ballots (AP Top 25 football/men's basketball since 2014, BBWAA MLB awards since 2012, NBA 2014-15–2022-23 and PHWA NHL awards since 2017-18 from PDFs the user downloads with `tools/download.py`) re-counted with 15 methods (official points, Borda, plurality, first past the post, top-two runoff, IRV, Coombs, Baldwin, Bucklin, Copeland, Schulze, ranked pairs, minimax, Kemeny); `fetch.py` adds new AP weeks daily |

Games: `new27K/` (27K, at `/27k/`), `ballmonitor/games/lineup/` (Lineup daily batting-order puzzle at
`/lineup/`: nine real player-seasons since 1955, graded by exact expected runs (Markov chain,
`rules.toml` baserunning rates) against all 9! orders; puzzles prebuilt by `python -m ballmonitor.games.lineup.build`,
needs numpy and the Lahman CSVs from Triple Play; see its README), `web/static/game.html` (Pitch Guesser, local only for now) and
`ballmonitor/games/triple_play/` (Triple Play daily Venn puzzle at `/triple/`: 17 spots and 25 cards, a spare per part; baseball Tue-Sun (Sunday = 25 spots, 33 cards) from the
Lahman database, cities & states on Monday from Wikipedia lists; puzzles prebuilt by
`python -m ballmonitor.games.triple_play.build`; see its README).

Retired and non-sports models live in `~/Desktop/projects/modelstuff` (`archived_models/`: ncaab_seeding,
race_elevation, race_time_v0, sp500, polls, …).

See `ROADMAP.md` for more model ideas.

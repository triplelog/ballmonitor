# CLAUDE.md — ballmonitor

A collection of **simple, open, fully-tweakable models** that predict probabilities and
estimates for sports events (college and pro football, baseball, basketball, running races,
awards and polls), plus the sports games on the same site. Split out of `../modelstuff` on
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
    static/               index.html, app.js, style.css — vanilla JS, no build step
  core/
    config.py             load config.toml → apply variant → apply --set overrides
    params.py             ParamSpec / FormulaSpec / Params (attribute access + p.formula())
    formula.py            safe evaluator for config formulas (AST whitelist, no eval)
    prediction.py         Outcome + Prediction: the ONLY output type
    render.py             ALL output formatting lives here (text / md / json / compare / backtest)
    model.py              BaseModel: predict(), backtest_case(), score(), prediction() helper
    backtest.py           score a model against data/backtest.csv
    registry.py           discover/load models, examples, variants; scaffold new models
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
  research-only pieces that stay in the CLI, data and tests but are not shown on the site.
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
| `ranked_choice` | draft | published ranked ballots (AP Top 25 football/men's basketball since 2014, BBWAA MLB awards since 2012, NBA 2014-15–2022-23 and PHWA NHL awards since 2017-18 from PDFs the user downloads with `tools/download.py`) re-counted with 13 methods (official points, Borda, plurality, IRV, Coombs, Baldwin, Bucklin, Copeland, Schulze, ranked pairs, minimax, Kemeny); `fetch.py` adds new AP weeks daily |

Games: `new27K/` (27K, at `/27k/`), `web/static/game.html` (Pitch Guesser) and
`ballmonitor/games/triple_play/` (Triple Play daily Venn puzzle at `/triple/`: baseball Tue-Sun (Sunday = 25 cards) from the
Lahman database, cities & states on Monday from Wikipedia lists; puzzles prebuilt by
`python -m ballmonitor.games.triple_play.build`; see its README).

Retired and non-sports models live in `../modelstuff` (`archived_models/`: ncaab_seeding,
race_elevation, race_time_v0, sp500, polls, …).

See `ROADMAP.md` for more model ideas.

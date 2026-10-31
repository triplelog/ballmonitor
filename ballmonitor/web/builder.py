"""Static site builder for ballmonitor.

Generates a standalone static distribution directory (default: `dist/`) containing:
- Pre-rendered index.html, game.html, static assets (app.js, style.css)
- data/manifest.json (build timestamp, model registry index)
- data/models.json (all model descriptions and metadata)
- data/models/<name>.json (parameters, formulas, variants, examples, docs)
- data/models/<name>/examples/<example>.json (pre-computed model outputs)
- data/entities.json (static autocomplete dictionaries for pitchers, batters, teams, races)
- data/game_scenarios.json (offline scenarios for the Pitch Guesser game)

Runs via CLI:
    ballmonitor build-site [--out dist]
"""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path
from typing import Any

from ballmonitor.core import registry, render
from ballmonitor.core.config import read_toml
from ballmonitor.web import server

STATIC_DIR = Path(__file__).resolve().parent / "static"


def extract_entities() -> dict[str, Any]:
    """Build unified autocomplete dictionaries across all models."""
    pitchers: set[str] = set()
    batters: set[str] = set()
    college_teams: set[str] = set()
    mlb_teams = [
        "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
        "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
        "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSH"
    ]
    races: set[str] = set()

    # BvP similarity
    try:
        import pandas as pd
        bvp_dir = registry.model_dir("bvp_similarity") / "data"
        if (bvp_dir / "pitchers.parquet").exists():
            df_p = pd.read_parquet(bvp_dir / "pitchers.parquet")
            col = "name" if "name" in df_p.columns else ("player_name" if "player_name" in df_p.columns else None)
            if col:
                pitchers.update(n for n in df_p[col].dropna().astype(str).unique() if not n.isdigit() and len(n) > 2)
        if (bvp_dir / "batters.parquet").exists():
            df_b = pd.read_parquet(bvp_dir / "batters.parquet")
            col = "name" if "name" in df_b.columns else ("player_name" if "player_name" in df_b.columns else None)
            if col:
                batters.update(n for n in df_b[col].dropna().astype(str).unique() if not n.isdigit() and len(n) > 2)
    except Exception:
        pass

    # Next pitch
    try:
        import pandas as pd
        np_dir = registry.model_dir("next_pitch") / "data"
        if (np_dir / "pitchers.csv").exists():
            df_p = pd.read_csv(np_dir / "pitchers.csv")
            col = "name" if "name" in df_p.columns else ("pitcher" if "pitcher" in df_p.columns else None)
            if col:
                pitchers.update(n for n in df_p[col].dropna().astype(str).unique() if not n.isdigit() and len(n) > 2)
        if (np_dir / "batters.csv").exists():
            df_b = pd.read_csv(np_dir / "batters.csv")
            col = "name" if "name" in df_b.columns else ("batter" if "batter" in df_b.columns else None)
            if col:
                batters.update(n for n in df_b[col].dropna().astype(str).unique() if not n.isdigit() and len(n) > 2)
    except Exception:
        pass

    # College bowls
    try:
        bowls_teams_file = registry.model_dir("ncaaf_bowls") / "data" / "teams.json"
        if bowls_teams_file.exists():
            bdata = json.loads(bowls_teams_file.read_text(encoding="utf-8"))
            for item in (bdata.values() if isinstance(bdata, dict) else bdata):
                name = item.get("name") if isinstance(item, dict) else item
                if name:
                    college_teams.add(name)
    except Exception:
        pass

    # College recruiting
    try:
        import pandas as pd
        rec_dir = registry.model_dir("ncaaf_recruiting") / "data" / "recruits"
        if rec_dir.exists():
            for f in rec_dir.glob("*.csv"):
                if f.name in ("manifest.csv", "wbb_espn_classes.csv"):  # not recruit lists / ESPN mascot names
                    continue
                try:
                    df = pd.read_csv(f, on_bad_lines="skip")
                    for c in ("committed_to", "committed_team", "school"):
                        if c in df.columns:
                            college_teams.update(df[c].dropna().astype(str).unique())
                except Exception:
                    pass
    except Exception:
        pass

    # Race podium
    try:
        import pandas as pd
        pod_dir = registry.model_dir("race_podium") / "data"
        if (pod_dir / "runsignup" / "finishes.csv").exists():
            df_r = pd.read_csv(pod_dir / "runsignup" / "finishes.csv")
            if "race_name" in df_r.columns:
                races.update(df_r["race_name"].dropna().astype(str).unique())
    except Exception:
        pass

    # Add standard well-known marathon & road races
    races.update([
        "Cherry Blossom 10 Mile", "City Autumn 5K", "Run for the Oaks 10K",
        "Boston Marathon", "Chicago Marathon", "New York City Marathon",
        "Peachtree Road Race 10K", "Bolder Boulder 10K"
    ])

    return {
        "pitchers": sorted(pitchers),
        "batters": sorted(batters),
        "college_teams": sorted(college_teams),
        "mlb_teams": mlb_teams,
        "teams": sorted(college_teams | set(mlb_teams)),
        "races": sorted(races),
    }


def build_static_site(out_dir: Path | str = "dist", models: list[str] | None = None) -> Path:
    """Build the full static site into `out_dir`."""
    target = Path(out_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    data_dir = target / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_data_dir = data_dir / "models"
    models_data_dir.mkdir(parents=True, exist_ok=True)
    static_dest = target / "static"
    static_dest.mkdir(parents=True, exist_ok=True)

    # 1. Copy web assets to dist root and dist/static
    for name in ("index.html", "game.html", "style.css", "app.js", "replay.js", "replay.html"):
        src = STATIC_DIR / name
        if src.exists():
            shutil.copy2(src, target / name)
            if name.endswith((".css", ".js")):
                shutil.copy2(src, static_dest / name)

    # 1b. 27K pitching game (its own static build) -> dist/27k/
    if server.GAME_27K.is_dir():
        shutil.copytree(server.GAME_27K, target / "27k", dirs_exist_ok=True)
    # 1c. Triple Play (daily Venn puzzle; puzzles prebuilt by games/triple_play/build.py) -> dist/triple/
    if server.GAME_TRIPLE.is_dir():
        shutil.copytree(server.GAME_TRIPLE, target / "triple", dirs_exist_ok=True)

    # 2. Copy game scenarios for Pitch Guesser
    scenarios_src = registry.MODELS_DIR / "next_pitch" / "data" / "game_scenarios.json"
    if scenarios_src.exists():
        shutil.copy2(scenarios_src, data_dir / "game_scenarios.json")

    # 3. Export static entity autocomplete dictionaries
    entities = extract_entities()
    (data_dir / "entities.json").write_text(json.dumps(entities, indent=2), encoding="utf-8")

    # 4. Filter model list (stubs have nothing to run yet)
    available_models = [m for m in registry.model_names() if registry.config_for(m).status != "stub"]
    target_models = [m for m in (models or available_models) if m in available_models]

    # 5. Export models.json (model index list)
    all_models_meta = server.list_models()
    filtered_meta = [m for m in all_models_meta if m["name"] in target_models]
    (data_dir / "models.json").write_text(json.dumps(filtered_meta, indent=2), encoding="utf-8")

    # 6. Export per-model details and pre-computed example outputs
    failures: list[str] = []
    for mname in target_models:
        detail = server.model_detail(mname)
        (models_data_dir / f"{mname}.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")

        # Create examples dir
        ex_dir = models_data_dir / mname / "examples"
        ex_dir.mkdir(parents=True, exist_ok=True)

        model_inst = registry.load_model(mname)
        for ex_name in server.web_examples(mname):
            ex_path = registry.model_dir(mname) / "examples" / f"{ex_name}.toml"
            try:
                pred = model_inst.predict(read_toml(ex_path))
            except Exception as exc:
                failures.append(f"{mname}/{ex_name}: {type(exc).__name__}: {exc}")
                continue
            result_payload = {
                "text": render.render_text(pred),
                "markdown": render.render_markdown(pred),
                "prediction": pred.to_dict(),
            }
            (ex_dir / f"{ex_name}.json").write_text(json.dumps(result_payload, indent=2), encoding="utf-8")

    # A page with a missing result is a broken page: fail so CI never deploys it.
    if failures:
        raise RuntimeError("could not precompute examples:\n  " + "\n  ".join(failures))

    # 7. Write manifest.json with build metadata
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    manifest = {
        "build_time": now_utc.isoformat(),
        "build_date": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "model_count": len(target_models),
        "models": target_models,
        "static_mode": True,
        "entities_count": {k: len(v) for k, v in entities.items()},
    }
    (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return target

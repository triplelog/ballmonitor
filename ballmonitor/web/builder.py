"""Static site builder for ballmonitor.

Generates a standalone static distribution directory (default: `dist/`) containing:
- index.html: the public page (site.html + site.js/site.css), which only shows data/views/*.json
- editor.html: the model editor (index.html + app.js), read-only on the static site
- data/site.json + data/views/<name>.json: pre-generated tables/charts from models/<name>/site.py
- replay assets, the editor's app.js/style.css (Pitch Guesser's game.html is off the site for now)
- data/manifest.json (build timestamp, model registry index)
- data/models.json (all model descriptions and metadata)
- data/models/<name>.json (parameters, formulas, variants, examples, docs)
- data/models/<name>/examples/<example>.json (pre-computed model outputs)
- data/entities.json (static autocomplete dictionaries for pitchers, batters, teams, races)

Runs via CLI:
    ballmonitor build-site [--out dist]
"""

from __future__ import annotations

import datetime
import importlib
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ballmonitor.core import registry, render, views
from ballmonitor.core.config import read_toml
from ballmonitor.web import charts, pages, server, tables

STATIC_DIR = Path(__file__).resolve().parent / "static"
SITE_URL = "https://ballmonitor.com"  # canonical address (robots.txt, sitemap.xml)
# The games' own pages; every forecast, table, chart and text page is added by build_pages.
GAME_PATHS = ["/triple/", "/lineup/", "/27k/"]
# Share tags the build adds to the games' pages: path -> (title, description)
GAME_META = {
    "/triple/": ("Triple Play: a daily baseball Venn puzzle",
                 "A daily puzzle: put each player (or city) in the right part of three circles."),
    "/lineup/": ("Lineup: a daily batting-order puzzle",
                 "Nine real hitters from baseball history. Put them in the batting order that scores the most runs."),
    "/27k/": ("27K: a pitching game", "A baseball pitching game: get 27 outs."),
}


GONE_OPTION_SCRIPT = """<script>
// /<page>/<picker>/<option>/ that no longer exists: go to /<page>/ if that page is on the site
(function () {
	var p = location.pathname.split('/').filter(Boolean);
	if (p.length < 3 || !/^[a-z0-9_]+$/.test(p[0])) return;
	fetch('/data/views/' + p[0] + '.json', { method: 'HEAD' }).then(function (r) {
		if (r.ok) location.replace('/' + p[0] + '/');
	}).catch(function () {});
})();
</script>
"""


def game_head(html: str, path: str, title: str, description: str) -> str:
    """A game page with a description, canonical link and share tags (those it lacks) before </head>."""
    from html import escape
    url = SITE_URL + path
    tags = {
        'name="description"': f'<meta name="description" content="{escape(description)}">',
        'rel="canonical"': f'<link rel="canonical" href="{url}">',
        'property="og:title"': f'<meta property="og:title" content="{escape(title)}">',
        'property="og:description"': f'<meta property="og:description" content="{escape(description)}">',
        'property="og:url"': f'<meta property="og:url" content="{url}">',
        'property="og:type"': '<meta property="og:type" content="website">',
        'property="og:image"': f'<meta property="og:image" content="{SITE_URL}/static/share.png">',
        'name="twitter:card"': '<meta name="twitter:card" content="summary_large_image">',
    }
    add = "".join(f"  {tag}\n" for key, tag in tags.items() if key not in html)
    return html.replace("</head>", add + "</head>", 1) if add else html


def versioned(html: str, static_dir: Path) -> str:
    """/static/<file>.css|.js links get ?v=<content hash>, so a new build never pairs new pages with
    a browser's cached old script."""
    def tag(m: re.Match) -> str:
        f = static_dir / m.group(2)
        return m.group(0) if not f.is_file() else f'{m.group(1)}/static/{m.group(2)}?v={hashlib.sha1(f.read_bytes()).hexdigest()[:10]}"'
    return re.sub(r'((?:href|src)=")/static/([\w.-]+\.(?:css|js))"', tag, html)


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


def missing_import_targets(html_path: Path) -> list[str]:
    """Local files named by a page's <script type="importmap"> and stylesheet links that don't exist."""
    import re

    html = html_path.read_text(encoding="utf-8")
    refs = re.findall(r'"(\./[^"]+\.js)"', "".join(re.findall(r'<script type="importmap">(.*?)</script>', html, re.S)))
    refs += [h for h in re.findall(r'<link[^>]+href="([^"]+)"', html) if not h.startswith(("http:", "https:", "data:"))]
    return [r for r in refs if not (html_path.parent / r).is_file()]


def site_pages(name: str) -> dict[str, dict]:
    """The pre-generated public pages of one model, {address: page}, each checked with
    core.views.check; {} when the model has no site.py. A site.py defines `page(model)` (one page
    at /<model>/, text from site.md) or `pages(model) -> {address: page}` (several pages, e.g. one
    per sport; text from site_<address>.md). Every page records its `model` for the editor link."""
    directory = registry.model_dir(name)
    if not (directory / "site.py").exists():
        return {}
    module = importlib.import_module(f"ballmonitor.models.{name}.site")
    model = registry.load_model(name)
    if hasattr(module, "pages"):
        built = {address: (p, directory / f"site_{address}.md") for address, p in module.pages(model).items()}
    else:
        built = {name: (module.page(model), directory / "site.md")}
    out = {}
    for address, (p, text_file) in built.items():
        p = views.clean(p)
        views.apply_text(p, views.read_text_file(text_file))
        problems = views.check(p)
        if problems:
            raise ValueError(f"{name}/site.py ({address}): " + "; ".join(problems[:8]))
        out[address] = {**p, "model": name}
    return out


def site_redirects(name: str) -> dict[str, str]:
    """Old page addresses -> new ones, from site.py REDIRECTS (e.g. after splitting a page in two)."""
    if not (registry.model_dir(name) / "site.py").exists():
        return {}
    return dict(getattr(importlib.import_module(f"ballmonitor.models.{name}.site"), "REDIRECTS", {}))


def site_page(name: str) -> dict | None:
    """The single public page of a one-page model (None when it has no site.py)."""
    pages = site_pages(name)
    if len(pages) > 1:
        raise ValueError(f"{name} has several pages ({', '.join(pages)}): use site_pages")
    return next(iter(pages.values()), None)


SPLIT_BYTES = 150_000   # a page's JSON above this has its dropdown options' views moved to their own files


def app_versions() -> dict[str, str]:
    """apps/<name>.js -> content hash: site.js loads an app as /static/apps/<name>.js?v=<hash>, so a
    new build never runs a browser's cached old copy of a model's formulas."""
    return {f"apps/{f.name}": hashlib.sha1(f.read_bytes()).hexdigest()[:10]
            for f in sorted((STATIC_DIR / "apps").glob("*.js"))}


def split_options(page: dict, address: str, out: Path) -> dict:
    """A copy of `page` whose top-level picker options keep label/slug/intro and a `src`
    (/data/views/<address>/<picker>/<slug>.json, holding {"views": [...]}) instead of their views,
    which are written to those files. site.js fetches an option's file when it's shown."""
    page = {**page, "views": [dict(v) for v in page["views"]]}
    for v in page["views"]:
        if v.get("kind") != "picker":
            continue
        folder = out / address / v["id"]
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        options = []
        for o in v["options"]:
            slug = o.get("slug") or views.slug(o["label"])
            (folder / f"{slug}.json").write_text(json.dumps({"views": o["views"]}, separators=(",", ":"),
                                                            allow_nan=False), encoding="utf-8")
            options.append({**{k: x for k, x in o.items() if k != "views"}, "views": [],
                            "src": f"/data/views/{address}/{v['id']}/{slug}.json"})
        v["options"] = options
    return page


def load_page(views_dir: Path, address: str) -> dict:
    """A page as site.py made it: data/views/<address>.json with any split options' views read back."""
    page = json.loads((views_dir / f"{address}.json").read_text(encoding="utf-8"))
    for v in page["views"]:
        for o in v.get("options", []) if v.get("kind") == "picker" else []:
            if o.get("src"):
                o["views"] = json.loads((views_dir.parent.parent / o.pop("src").lstrip("/")).read_text(encoding="utf-8"))["views"]
    return page


def build_views(data_dir: Path, names: list[str], log=print) -> list[str]:
    """data/views/<address>.json for every page of every model with a site.py, plus
    data/site.json (the home page index and old-address redirects). Returns failures (a model
    whose page can't be built must not deploy half-done)."""
    out = data_dir / "views"
    out.mkdir(parents=True, exist_ok=True)
    index, redirects, failures = [], {}, []
    for name in names:
        started = time.perf_counter()
        try:
            pages = site_pages(name)
            redirects.update(site_redirects(name))
        except Exception as exc:  # noqa: BLE001 - reported, then the build fails
            failures.append(f"{name}/site.py: {type(exc).__name__}: {exc}")
            continue
        for address, p in pages.items():
            text = json.dumps(p, separators=(",", ":"), allow_nan=False)
            if len(text) > SPLIT_BYTES:   # a big page: each dropdown option's tables load when it's picked
                text = json.dumps(split_options(p, address, out), separators=(",", ":"), allow_nan=False)
            (out / f"{address}.json").write_text(text, encoding="utf-8")
            index.append({"name": address, **{k: p[k] for k in ("title", "summary", "sport", "updated", "order")}})
        if pages:
            shown = ", ".join(f"{a} ({len(p['views'])} views)" for a, p in pages.items())
            log(f"   views {name}: {shown} in {time.perf_counter() - started:.1f}s")
    order = {s: i for i, s in enumerate(views.SPORTS)}
    index.sort(key=lambda m: (order.get(m["sport"], 99), m["order"], m["title"]))
    live = tables.public()   # live data tables (web/tables.toml) whose server has an address
    if live:
        log(f"   tables: {', '.join(t['id'] for t in live)}")
    chart_list = charts.public()   # the baseball charts page's list (web/charts.toml)
    (data_dir / "site.json").write_text(json.dumps({"models": index, "redirects": redirects, "tables": live,
                                                    "charts": chart_list, "cells": views.SPORT_CELL,
                                                    "assets": app_versions()},
                                                   indent=1), encoding="utf-8")
    return failures


def build_static_site(out_dir: Path | str = "dist", models: list[str] | None = None, log=print) -> Path:
    """Build the full static site into `out_dir`."""
    target = Path(out_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    data_dir = target / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_data_dir = data_dir / "models"
    models_data_dir.mkdir(parents=True, exist_ok=True)
    static_dest = target / "static"
    static_dest.mkdir(parents=True, exist_ok=True)

    # 1. Copy web assets to dist/static (the pages load them from /static/); the root keeps only
    #    replay.html + replay.js (which loads it from beside itself) and the 404 page. The public
    #    page is index.html; the editor (index.html in the source, the live `serve` page) becomes
    #    editor.html, titled and kept out of search engines.
    for name in ("style.css", "app.js", "replay.js", "site.js", "site.css", "shioh-style.css", "shioh.js",
                 "fonts.css", "share.png"):
        shutil.copy2(STATIC_DIR / name, static_dest / name)
    shutil.copytree(STATIC_DIR / "fonts", static_dest / "fonts", dirs_exist_ok=True)
    shutil.copytree(STATIC_DIR / "apps", static_dest / "apps", dirs_exist_ok=True)   # views.app tools
    for name in ("replay.js", "replay.html"):
        shutil.copy2(STATIC_DIR / name, target / name)
    # the 404 page (the Shioh template, unchanged) + one script: an option that is no longer on its
    # page (a past poll week, a team that left the table) forwards to the page it belonged to
    (target / "404.html").write_text((STATIC_DIR / "404.html").read_text(encoding="utf-8").replace(
        "</body>", GONE_OPTION_SCRIPT + "</body>", 1), encoding="utf-8")
    editor = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    editor = re.sub(r"<title>[^<]*</title>", '<title>Model editor · Ball Monitor</title>\n  <meta name="robots" content="noindex">',
                    editor, count=1)
    (target / "editor.html").write_text(editor, encoding="utf-8")
    shutil.copy2(STATIC_DIR / "site.html", target / "index.html")   # build_pages rewrites it with the home page's words
    (target / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nDisallow: /editor.html\nDisallow: /replay.html\n\nSitemap: {SITE_URL}/sitemap.xml\n",
        encoding="utf-8")

    # 1b. 27K pitching game (its own static build) -> dist/27k/
    if server.GAME_27K.is_dir():
        dest_27k = target / "27k"
        if dest_27k.exists():
            shutil.rmtree(dest_27k)
        shutil.copytree(server.GAME_27K, dest_27k)
        missing = missing_import_targets(dest_27k / "index.html")
        if missing:  # e.g. a library folder that never got committed: fail rather than deploy a dead game
            raise RuntimeError("27K import map points at missing files: " + ", ".join(missing))
    # 1c. Triple Play (daily Venn puzzle; puzzles prebuilt by games/triple_play/build.py) -> dist/triple/
    if server.GAME_TRIPLE.is_dir():
        shutil.copytree(server.GAME_TRIPLE, target / "triple", dirs_exist_ok=True)
    # 1d. Lineup (daily batting-order puzzle; prebuilt by games/lineup/build.py) -> dist/lineup/
    if server.GAME_LINEUP.is_dir():
        shutil.copytree(server.GAME_LINEUP, target / "lineup", dirs_exist_ok=True)

    # 1d'. the games' own pages get the site's share tags (their sources stay as they are)
    for path, (title, description) in GAME_META.items():
        page = target / path.strip("/") / "index.html"
        if page.exists():
            page.write_text(game_head(page.read_text(encoding="utf-8"), path, title, description), encoding="utf-8")

    # 1e. the baseball charts (pyslots' form and templates, scripts/sync-charts.sh) -> dist/charts/
    if server.CHARTS.is_dir():
        shutil.copytree(server.CHARTS, target / "charts", dirs_exist_ok=True)

    # 2. (Pitch Guesser, game.html + data/game_scenarios.json, is off the site since 2026-11-08;
    #    it still runs locally at /game under `ballmonitor serve`.)

    # 3. Export static entity autocomplete dictionaries
    entities = extract_entities()
    (data_dir / "entities.json").write_text(json.dumps(entities, indent=2), encoding="utf-8")

    # 4. Filter model list (stubs have nothing to run yet; [web] public = false stays off the site)
    available_models = [m for m in registry.model_names()
                        if registry.config_for(m).status != "stub" and server.is_public(m)]
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

    # 6b. Pre-generated public pages
    failures += build_views(data_dir, target_models, log=log)

    # A page with a missing result is a broken page: fail so CI never deploys it.
    if failures:
        raise RuntimeError("could not precompute examples:\n  " + "\n  ".join(failures))

    # 6c. one HTML file per address (index.html too) + sitemap.xml
    build_pages(target, data_dir)

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


def build_pages(target: Path, data_dir: Path) -> list[str]:
    """Write a copy of site.html at every public address (web/pages.py), stubs at old addresses,
    and sitemap.xml listing them all. Reads what build_views wrote (data/site.json, data/views/).
    Returns the addresses written."""
    template = versioned((STATIC_DIR / "site.html").read_text(encoding="utf-8"), STATIC_DIR)
    site = json.loads((data_dir / "site.json").read_text(encoding="utf-8"))
    cell = views.cell_class
    out: dict[str, tuple[str, str, str]] = {
        "/": (pages.SITE_NAME, _meta_content(template, "description"), pages.home_page(site))}
    for m in site["models"]:
        if m["name"] in pages.RESERVED:
            raise ValueError(f"page address {m['name']!r} is used by the site itself")
        page = json.loads((data_dir / "views" / f"{m['name']}.json").read_text(encoding="utf-8"))
        out.update(pages.model_pages(m["name"], page, cell(page.get("sport", ""))))
    for t in site.get("tables", []):
        out[f"/tables/{t['id']}/"] = pages.table_page(t, cell(t.get("sport", "")))
    if site.get("charts"):
        # the chart files copied in (embed/, examples/...), not the output folder, which holds the
        # chart pages of an earlier build when building into the same folder again
        taken = {p.name for p in server.CHARTS.iterdir()} if server.CHARTS.is_dir() else set()
        clash = [c["id"] for c in site["charts"] if c["id"] in taken]
        if clash:
            raise ValueError(f"chart ids clash with files in charts/: {clash}")
        out.update(pages.chart_pages(site["charts"], cell("Baseball")))
    text = {f"/{name}/": pages.text_page(name) for name in pages.TEXT_PAGES}
    for path, (title, description, body) in {**out, **text}.items():
        pages.write(target, path, pages.shell(template, site_url=SITE_URL, path=path, title=title,
                                              description=description, body=body, static=path in text))
    for old, new in site.get("redirects", {}).items():
        if f"/{old}/" not in out:
            pages.write(target, f"/{old}/", pages.redirect_page(SITE_URL, f"/{new}/"))
    listed = [*out, *text, *GAME_PATHS]
    today = datetime.date.today().isoformat()
    (target / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{SITE_URL}{path}</loc><lastmod>{today}</lastmod></url>\n" for path in listed)
        + "</urlset>\n", encoding="utf-8")
    return listed


def _meta_content(template: str, name: str) -> str:
    import re
    m = re.search(rf'<meta name="{name}" content="([^"]*)">', template)
    return m.group(1) if m else ""


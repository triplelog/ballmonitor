"""Public page: projected matchups of star hitters against the busiest starting pitchers, and a
profile of each of those pitchers.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views bvp_similarity`); the page
only displays these numbers. Who counts as a "star hitter" / "top starter" comes from the
latest-season volumes in next_pitch's committed data (this model's own profiles stop at 2025);
when those files are missing it falls back to career plate appearances in the profiles.
"""

from __future__ import annotations

import csv
import json

from ballmonitor.core import views as V

PITCH_NAMES = {
    "pct_ff": "Four-seam fastball", "pct_si": "Sinker", "pct_fc": "Cutter", "pct_sl": "Slider",
    "pct_st": "Sweeper", "pct_cu": "Curveball", "pct_ch": "Changeup", "pct_fs": "Splitter",
}
HAND = {"R": "RHP", "L": "LHP"}
BATS = {"R": "bats right", "L": "bats left", "S": "switch-hitter"}


def _rows(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _active(profiles: list[dict], key: str, recent: list[dict], recent_key: str, volume: str,
            minimum: float) -> list[tuple[dict, dict]]:
    """(profile, latest-season row) for players with at least `minimum` latest-season volume."""
    by_id = {r[key]: r for r in profiles}
    return [(by_id[r[recent_key]], r) for r in recent
            if r[recent_key] in by_id and float(r.get(volume) or 0) >= minimum]


def _by_last_name(name: str) -> str:
    parts = [w for w in name.split() if w.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")]
    return (parts[-1] if parts else name) + " " + name


def page(model) -> dict:
    p = model.params
    data = model.dir / "data"
    meta = json.loads((data / "meta.json").read_text())
    train = meta["train_seasons"]
    seasons = f"{train[0]}–{train[-1]}"
    test_season = meta.get("backtest_season", train[-1] + 1)
    league = float(p.league_xwoba)

    pitchers = _rows(data / "pitchers.csv")
    batters = _rows(data / "batters.csv")
    np_data = model.dir.parent / "next_pitch" / "data"
    season_col = f"pitches_{test_season}"
    # best hitters of the latest season (wOBA, enough PA); fallback: career PA in the profiles
    hitters = _active(batters, "batter", _rows(np_data / "batters.csv"), "batter_id", "pa", p.site_min_pa)
    hitters.sort(key=lambda pr: -float(pr[1]["woba"] or 0))
    top_b = [b for b, _ in hitters] or sorted(batters, key=lambda r: -float(r["pa"]))
    top_b = top_b[: int(p.site_hitters)]
    # best regular starters of the latest season, ranked by career damage allowed
    starters = _active(pitchers, "pitcher", _rows(np_data / "pitchers.csv"), "pitcher_id", season_col,
                       p.site_min_pitches)
    top_p = [pr for pr, _ in starters if float(pr["pa"]) >= p.site_min_profile_pa] or \
        sorted(pitchers, key=lambda r: -float(r["pa"]))
    if starters:
        top_p.sort(key=lambda r: float(r["xwoba"]))
    top_p = top_p[: int(p.site_pitchers)]

    def quality(x: float) -> int:
        return round(100 * x / league)

    # matchups: every star hitter against every top pitcher
    similar: dict[str, list[str]] = {}
    options = []
    for b in top_b:
        rows = []
        for pr in top_p:
            res = model.predict({"pitcher": pr["pitcher"], "batter": b["batter"]})
            xw, k, bb = (o.estimate if o.estimate is not None else o.probability for o in res.outcomes[:3])
            similar.setdefault(pr["pitcher"], [s["name"] for s in res.extras["similar_pitchers"][:2]])
            rows.append({"pitcher": pr["name"], "hand": HAND.get(pr["throws"], pr["throws"]),
                         "quality": quality(xw), "k": round(k, 4), "bb": round(bb, 4),
                         "faced": int(res.extras["direct_pa"])})
        rows.sort(key=lambda r: -r["quality"])
        b["_sort"] = _by_last_name(b["name"])
        label = f"{b['name']} ({BATS.get(b['bats'], b['bats'])})"
        options.append(V.option(label, [V.table(
            f"vs_{b['batter']}", f"{b['name']} against {len(top_p)} top starters",
            [V.col("pitcher", "Pitcher"), V.col("hand", "Throws"),
             V.col("quality", "Hitting quality", "int", bar=True),
             V.col("k", "Strikeout chance", "pct"), V.col("bb", "Walk chance", "pct"),
             V.col("faced", f"Times faced {seasons}", "int")],
            rows, sort="quality",
            subtitle=(f"Best matchups for him first. Hitting quality: how much damage he is "
                      "expected to do per plate appearance, where 100 is an average hitter against an "
                      "average pitcher and 120 is 20% better."),
            note="Strikeout and walk chances are per plate appearance.")]))
    options = [o for _, o in sorted(zip([b["_sort"] for b in top_b], options), key=lambda t: t[0])]
    default = next((i for i, o in enumerate(options) if o["label"].startswith("Aaron Judge")), 0)
    picker = V.picker(
        "by_hitter", "How would he do against the top starters?", "Hitter", options, default=default,
        subtitle=(f"The {len(options)} best hitters of the past year ({p.site_min_pa:.0f}+ plate appearances), "
                  f"A to Z by last name, each against {len(top_p)} of the best regular starting pitchers."))

    # pitcher profiles
    prof_rows = []
    for pr in top_p:
        main = max(PITCH_NAMES, key=lambda c: float(pr[c] or 0))
        prof_rows.append({
            "pitcher": pr["name"], "hand": HAND.get(pr["throws"], pr["throws"]),
            "velo": round(float(pr["velo_fb"]), 1), "main": PITCH_NAMES[main],
            "k": round(float(pr["k_pct"]), 4), "bb": round(float(pr["bb_pct"]), 4),
            "allowed": quality(float(pr["xwoba"])),
            "similar": ", ".join(similar.get(pr["pitcher"], [])),
        })
    profiles = V.table(
        "pitchers", "The starting pitchers",
        [V.col("pitcher", "Pitcher"), V.col("hand", "Throws"), V.col("velo", "Fastball mph", "number", decimals=1),
         V.col("main", "Main pitch"), V.col("k", "Strikeout %", "pct", bar=True), V.col("bb", "Walk %", "pct"),
         V.col("allowed", "Hitting quality allowed", "int"), V.col("similar", "Most similar pitchers")],
        prof_rows, search=True,
        subtitle=(f"Pitchers with {p.site_min_pitches:,.0f}+ pitches in {test_season}, best first by hitting "
                  f"quality allowed in {seasons}. Hitting quality allowed: 100 is average, lower is better for "
                  "the pitcher. Similar pitchers have the closest mix of pitches, speed and results."))

    return V.page(
        title="Batter vs. pitcher matchups",
        summary="How baseball's best hitters would fare against the top starting pitchers: strikeouts, walks and damage.",
        sport="Baseball",
        updated=f"{test_season} season, final (players chosen on {test_season}; ratings from {seasons} pitches)",
        how=("Each matchup starts from the hitter's and pitcher's own rates, adjusted for left- and right-handed "
             "splits, then blends in how hitters like him have done against pitchers like him and, a little, "
             "their actual head-to-head history. Checked against real matchups from the "
             f"{test_season} season, using only {seasons} data to predict them."),
        views=[picker, profiles],
    )

"""Full-model backtest for college_diamond (part of research.py).

For every season and three snapshot dates (April 1, May 1, selection eve) the shipped
model is run exactly as a user would (CollegeDiamondModel.predict, default config) using
only games before the snapshot, plus the schedule that was actually played after it.
Every D-I team is then scored against what happened:

  bid      P(NCAA bid): Brier, log loss
  host     P(regional host): Brier, log loss
  stage    how far the team got, 6 classes (no bid, out in regional, super, World Series,
           finals, champion): multi-class log loss from the model's cumulative
           probabilities
  wins     projected final wins (incl. postseason) vs actual: MAE, 80% interval coverage
  seed     expected seed line vs actual seed line (baseball; teams in the field)

Benchmarks (no simulation):
  rpi_now  P(bid), P(host) = the selection study's RPI-only logistic models applied to the
           RPI rank on the snapshot date; stage = frequencies of each stage by RPI-rank
           bucket on the snapshot date, estimated on the development seasons
  chalk    rating-only, deterministic: the best-rated team of each conference is the
           automatic qualifier, the best-rated others fill the field, top 16 host (0/1
           probabilities, clipped at 1%/99% for log loss)
  base     constant rates (64/n bid, 16/n host)

Development seasons (baseball 2015-2019, softball 2017-2019) were used to tune the
ratings and the committee proxy, so their numbers are in-sample; the test seasons
(2021-2026) are the honest ones. Teams within a season are not independent; the number
of independent units is the number of seasons.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
from collections import defaultdict

from ballmonitor.core import registry
from ballmonitor.models.college_diamond.data import DATA_DIR, load_games, load_teams, load_tournaments
from ballmonitor.models.college_diamond.research_strength import DEV, TEST

STAGES = ["no bid", "regional", "super", "world series", "finals", "champion"]
SNAPSHOTS = ["04-01", "05-01", "selection"]
BUCKETS = [1, 4, 8, 16, 32, 50, 75, 100, 150, 400]


def bucket(rank: int) -> int:
    for i, b in enumerate(BUCKETS):
        if rank <= b:
            return i
    return len(BUCKETS)


def stage_probs(s: dict) -> list[float]:
    cum = [1.0, s["bid"], s["regional"], s["super"], s["finals"], s["title"]]
    probs = [cum[i] - (cum[i + 1] if i + 1 < len(cum) else 0.0) for i in range(len(cum))]
    return [max(p, 0.0) for p in probs]


def clip(p: float, lo: float = 1e-3) -> float:
    return min(max(p, lo), 1 - lo)


def actuals(sport: str, season: int) -> dict[str, dict]:
    teams = load_teams(sport)[season]
    field = load_tournaments()[sport][str(season)]["field"]
    w, l = defaultdict(int), defaultdict(int)
    for g in load_games(sport):
        if g.season == season and g.margin:
            a, b = (g.home, g.away) if g.margin > 0 else (g.away, g.home)
            w[a] += 1
            l[b] += 1
    out = {}
    for t in teams:
        f = field.get(t)
        out[t] = {"bid": int(f is not None), "host": int(bool(f and f["host"])),
                  "stage": f["reached"] if f else 0, "seed": f["seed"] if f else None,
                  "wins": w[t], "losses": l[t]}
    return out


def chalk(pred_extras: dict, teams: dict) -> dict[str, dict]:
    r = pred_extras["rating"]
    best = {}
    for t, v in teams.items():
        c = v["conference"]
        if c != "Independent" and (c not in best or r[t] > r[best[c]]):
            best[c] = t
    aq = set(best.values())
    rest = sorted((t for t in teams if t not in aq), key=lambda t: -r[t])[:64 - len(aq)]
    field = aq | set(rest)
    hosts = set(sorted(field, key=lambda t: -r[t])[:16])
    return {t: {"bid": float(t in field), "host": float(t in hosts)} for t in teams}


def run(log=print, simulations: int | None = None) -> dict:
    sel_study = json.loads((DATA_DIR / "research" / "selection.json").read_text())
    rows_out = []
    metrics: dict = defaultdict(lambda: defaultdict(list))
    # stage frequencies by RPI bucket on the snapshot date, from development seasons
    freq: dict = defaultdict(lambda: [1.0] * len(STAGES))   # (sport, snap, bucket) -> counts (+1 smoothing)
    calib: dict = defaultdict(list)
    overrides = {"simulations": simulations} if simulations else None
    model = registry.load_model("college_diamond", None, overrides)
    for sport in ("baseball", "softball"):
        coef = sel_study["sports"][sport]
        b_sel, b_host = coef["rpi_only_coef"], coef["host_rpi_only_coef"]
        for season in DEV[sport] + TEST[sport]:
            split = "dev" if season in DEV[sport] else "test"
            teams = load_teams(sport)[season]
            act = actuals(sport, season)
            for snap in SNAPSHOTS:
                as_of = "selection" if snap == "selection" else f"{season}-{snap}"
                pred = model.predict({"sport": sport, "season": season, "as_of": as_of})
                ex = pred.extras
                rk = ex["rpi_rank_now"]
                ch = chalk(ex, teams)
                fld = load_tournaments()[sport][str(season)]["field"]
                aqs = {t for t, v in fld.items() if v.get("auto_bid")} if sport == "baseball" else \
                    set(ex["finished_tournaments"].values())
                n = len(teams)
                for t in teams:
                    s, a = ex["teams"][t], act[t]
                    r = rk.get(t, n)
                    p_bid_rpi = 1 / (1 + math.exp(-(b_sel[0] - b_sel[1] * math.log(r))))
                    p_host_rpi = 1 / (1 + math.exp(-(b_host[0] - b_host[1] * math.log(r))))
                    sp = stage_probs(s)
                    k = (sport, snap, bucket(r))
                    if split == "dev":
                        freq[k][a["stage"]] += 1
                    rows_out.append({"sport": sport, "season": season, "snapshot": snap, "as_of": ex["as_of"],
                                     "split": split, "team": t, "conference": teams[t]["conference"],
                                     "rpi_rank_at_snapshot": r, "made_field": a["bid"], "host": a["host"],
                                     "stage_reached": a["stage"], "seed": a["seed"] or "",
                                     "final_wins": a["wins"], "final_losses": a["losses"],
                                     "p_bid": round(s["bid"], 4), "p_host": round(s["host"], 4),
                                     "p_title": round(s["title"], 4), "proj_wins": s["wins"]})
                    key = (sport, snap, split)
                    m = metrics[key]
                    bench = [("bid", s["bid"], a["bid"]), ("host", s["host"], a["host"])]
                    if snap == "selection":  # automatic qualifiers are known on selection eve
                        bench.append(("bid_rpi_aq", 0.999 if t in aqs else p_bid_rpi, a["bid"]))
                    if split == "test":
                        calib[sport].append((s["bid"], a["bid"]))
                    for name, p, y in bench + [
                                       ("bid_rpi_now", p_bid_rpi, a["bid"]), ("host_rpi_now", p_host_rpi, a["host"]),
                                       ("bid_chalk", ch[t]["bid"], a["bid"]), ("host_chalk", ch[t]["host"], a["host"]),
                                       ("bid_base", 64 / n, a["bid"]), ("host_base", 16 / n, a["host"])]:
                        m[name + "_brier"].append((p - y) ** 2)
                        m[name + "_ll"].append(-math.log(clip(p if y else 1 - p, 0.01 if "chalk" in name else 1e-3)))
                    m["stage_ll"].append(-math.log(clip(sp[a["stage"]])))
                    m["_stage_rpi"].append((k, a["stage"]))
                    m["wins_abs_err"].append(abs(s["wins"] - a["wins"]))
                    m["wins_in_80"].append(float(s["wins_iv"][0] <= a["wins"] <= s["wins_iv"][1])
                                           if "wins_iv" in s else math.nan)
                    if sport == "baseball" and a["seed"] and s["seed_line"]:
                        m["seed_line_abs_err"].append(abs(s["seed_line"] - a["seed"]))
                log(f"  {sport} {season} {snap}: done ({ex['simulations']} sims)")
    # stage benchmark log loss (frequencies from dev seasons)
    for key, m in metrics.items():
        ll = []
        for k, stage in m.pop("_stage_rpi"):
            c = freq[k]
            ll.append(-math.log(clip(c[stage] / sum(c))))
        m["stage_ll_rpi_bucket"] = ll
    summary = {}
    for (sport, snap, split), m in sorted(metrics.items()):
        summary[f"{sport}|{snap}|{split}"] = {k: (sum(v) / len(v) if v else None) for k, v in m.items()} | {
            "teams": len(m["bid_brier"])}
    seasons = {sp: {"dev": DEV[sp], "test": TEST[sp]} for sp in ("baseball", "softball")}
    with open(DATA_DIR / "backtest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
        w.writeheader()
        w.writerows(rows_out)
    bins = [0.0, 0.05, 0.2, 0.4, 0.6, 0.8, 0.95, 1.0001]
    reliability = {}
    for sport, pairs in calib.items():
        rows = []
        for lo, hi in zip(bins, bins[1:]):
            sel = [(p, y) for p, y in pairs if lo <= p < hi]
            if sel:
                rows.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "n": len(sel),
                             "mean_p": sum(p for p, _ in sel) / len(sel), "freq": sum(y for _, y in sel) / len(sel)})
        reliability[sport] = rows
    return {"summary": summary, "seasons": seasons, "rows": len(rows_out), "reliability_test_bid": reliability}

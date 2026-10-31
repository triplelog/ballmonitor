"""Committee proxy study for college_diamond (part of research.py; needs numpy).

At each past Selection Monday (baseball) / Sunday (softball), using only games played
before it, every D-I team gets: RPI rank (rpi.py, NCAA formula), rating rank (shipped
rating, ratings.py objective) and D-I win %. Two logistic models are fitted on the
development seasons only:

  at-large:  P(in field | not an automatic qualifier, win % >= .500)
  host:      P(regional host | in field)

with features -ln(RPI rank), -ln(rating rank), win %. The test seasons are scored once:
log loss / Brier, and the "top-N" rule the simulation uses (the N best scores fill the N
at-large places; the 16 best host scores host) vs. a benchmark that uses RPI rank alone.
Seed-line error (baseball, where 1-4 seeds are known) compares the implied order of the
field with the actual seed lines.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import fields

import numpy as np

from ballmonitor.models.college_diamond.data import DATA_DIR, load_games, load_teams
from ballmonitor.models.college_diamond.ratings import RatingParams, midweek_flags
from ballmonitor.models.college_diamond.research_strength import DEV, TEST, fit_np, final_ratings
from ballmonitor.models.college_diamond.rpi import RpiWeights, ranks, rpi

RPI_WEIGHTS = {"baseball": RpiWeights(), "softball": RpiWeights(home_win=1, road_win=1, home_loss=1, road_loss=1)}
FEATURES = ["neg_log_rpi_rank", "neg_log_rating_rank", "win_pct"]


def rating_params(sport: str) -> RatingParams:
    path = DATA_DIR / "research" / "strength.json"
    if path.exists():
        chosen = json.loads(path.read_text())["sports"][sport]["chosen"]
        return RatingParams(**{f.name: chosen[f.name] for f in fields(RatingParams) if f.name in chosen})
    return RatingParams(margin_cap=12.0, margin_power=0.7, ridge=8.0, half_life_days=120.0,
                        prior_carry=0.7, split_midweek=False)


def selection_dates(sport: str) -> dict[int, dt.date]:
    cov = json.loads((DATA_DIR / "coverage.json").read_text())
    return {int(k.split()[1]): dt.date.fromisoformat(v["selection"]) for k, v in cov.items()
            if k.startswith(sport)}


def prior_chain(sport: str, p: RatingParams) -> dict[int, dict[str, float]]:
    """Season -> preseason prior (prior_carry * last season's final rating, centred)."""
    out: dict[int, dict[str, float]] = {}
    seasons = sorted({g.season for g in load_games(sport)})
    prev_final = None
    for s in seasons:
        prior = {}
        if prev_final:
            mean = sum(prev_final.values()) / len(prev_final)
            prior = {t: p.prior_carry * (v - mean) for t, v in prev_final.items()}
        out[s] = prior
        prev_final = final_ratings(sport, s, p, prior) if p.prior_carry > 0 else None
    return out


def season_table(sport: str, season: int, as_of: dt.date, p: RatingParams, prior: dict) -> list[dict]:
    games = [g for g in load_games(sport) if g.season == season and g.day < as_of and g.game_type != "N"]
    r, _, _ = fit_np(games, midweek_flags(games), p, as_of, prior)
    res = [(g.home, g.away, 1.0 if g.margin > 0 else 0.0 if g.margin < 0 else 0.5, g.neutral) for g in games]
    rk = ranks(rpi(res, RPI_WEIGHTS[sport]))
    teams = load_teams(sport)[season]
    rr = ranks({t: r.get(t, 0.0) for t in teams})
    w, l = {}, {}
    for g in games:
        if g.margin:
            a, b = (g.home, g.away) if g.margin > 0 else (g.away, g.home)
            w[a] = w.get(a, 0) + 1
            l[b] = l.get(b, 0) + 1
    tour = json.loads((DATA_DIR / "ncaa_tournaments.json").read_text())[sport][str(season)]["field"]
    aq = auto_qualifiers(sport, season, games, tour, teams)
    out = []
    for t in teams:
        n = w.get(t, 0) + l.get(t, 0)
        f = tour.get(t)
        out.append({"team": t, "season": season, "rpi_rank": rk.get(t, len(rk)), "rating_rank": rr[t],
                    "win_pct": w.get(t, 0) / n if n else 0.0, "in_field": f is not None,
                    "host": bool(f and f["host"]), "seed": f["seed"] if f else None,
                    "auto": t in aq, "conference": teams[t]["conference"]})
    return out


def auto_qualifiers(sport, season, games, field, teams) -> set[str]:
    """Baseball: from the bracket data. Softball (not recorded): per conference with a team
    in the field, the winner of its last conference-tournament game if in the field, else
    its field team with the best conference record."""
    if sport == "baseball":
        return {t for t, v in field.items() if v.get("auto_bid")}
    last, cw, cl = {}, {}, {}
    for g in sorted(games, key=lambda g: g.date):
        c = teams.get(g.home, {}).get("conference")
        if g.game_type == "C":
            last[c] = g.home if g.margin > 0 else g.away
        if g.conf_game and g.margin:
            a, b = (g.home, g.away) if g.margin > 0 else (g.away, g.home)
            cw[a] = cw.get(a, 0) + 1
            cl[b] = cl.get(b, 0) + 1
    out = set()
    confs = {teams[t]["conference"] for t in field if t in teams} - {"Independent"}
    for c in confs:
        mem = [t for t in field if t in teams and teams[t]["conference"] == c]
        if last.get(c) in mem:
            out.add(last[c])
        else:
            out.add(max(mem, key=lambda t: cw.get(t, 0) / max(cw.get(t, 0) + cl.get(t, 0), 1)))
    return out


def X(rows) -> np.ndarray:
    return np.array([[1.0, -math.log(r["rpi_rank"]), -math.log(r["rating_rank"]), r["win_pct"]] for r in rows])


def logit_fit(Xm, y, l2=0.01) -> np.ndarray:
    b = np.zeros(Xm.shape[1])
    for _ in range(100):
        p = 1 / (1 + np.exp(-Xm @ b))
        g = Xm.T @ (y - p) - l2 * np.r_[0, b[1:]]
        Hm = -(Xm.T * (p * (1 - p))) @ Xm - l2 * np.diag(np.r_[0, np.ones(len(b) - 1)])
        step = np.linalg.solve(Hm, g)
        b -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b


def ll_brier(p, y) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"n": int(len(y)), "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            "brier": float(np.mean((p - y) ** 2))}


def topn_misses(rows, score, n) -> int:
    pick = sorted(rows, key=lambda r: -score(r))[:n]
    return sum(1 for r in pick if not r["in_field"])


def run(log=print) -> dict:
    out: dict = {"features": FEATURES, "sports": {}}
    for sport in ("baseball", "softball"):
        p = rating_params(sport)
        priors = prior_chain(sport, p)
        sel = selection_dates(sport)
        seasons = [s for s in DEV[sport] + TEST[sport] if s in sel]
        tables = {s: season_table(sport, s, sel[s], p, priors.get(s, {})) for s in seasons}
        elig = lambda rows: [r for r in rows if not r["auto"] and r["win_pct"] >= 0.5]  # noqa: E731
        dev = [r for s in DEV[sport] if s in tables for r in elig(tables[s])]
        b_at = logit_fit(X(dev), np.array([r["in_field"] for r in dev], float))
        devf = [r for s in DEV[sport] if s in tables for r in tables[s] if r["in_field"]]
        b_host = logit_fit(X(devf), np.array([r["host"] for r in devf], float))
        b_rpi = logit_fit(X(dev)[:, :2], np.array([r["in_field"] for r in dev], float))
        b_host_rpi = logit_fit(X(devf)[:, :2], np.array([r["host"] for r in devf], float))
        res = {"at_large_coef": dict(zip(["intercept"] + FEATURES, map(float, b_at))),
               "host_coef": dict(zip(["intercept"] + FEATURES, map(float, b_host))),
               "rpi_only_coef": list(map(float, b_rpi)), "host_rpi_only_coef": list(map(float, b_host_rpi)),
               "seasons": {}}
        tot = {"misses": 0, "misses_rpi": 0, "at_large": 0, "host_hits": 0, "host_hits_rpi": 0,
               "line_err": [], "line_err_rpi": []}
        test_rows, test_f = [], []
        for s in TEST[sport]:
            if s not in tables:
                continue
            rows = tables[s]
            el = elig(rows)
            n_at = sum(1 for r in rows if r["in_field"] and not r["auto"])
            sc = lambda r: float(X([r])[0] @ b_at)  # noqa: E731
            m = topn_misses(el, sc, n_at)
            m_rpi = topn_misses(el, lambda r: -r["rpi_rank"], n_at)
            field_ = [r for r in rows if r["in_field"]]
            hs = sorted(field_, key=lambda r: -float(X([r])[0] @ b_host))[:16]
            hr = sorted(field_, key=lambda r: r["rpi_rank"])[:16]
            hh, hh_rpi = sum(r["host"] for r in hs), sum(r["host"] for r in hr)
            line_err = line_err_rpi = None
            if sport == "baseball" and all(r["seed"] for r in field_):
                order = hs + sorted((r for r in field_ if r not in hs), key=lambda r: -float(X([r])[0] @ b_at))
                order_r = sorted(field_, key=lambda r: r["rpi_rank"])
                line_err = float(np.mean([abs(1 + i // 16 - r["seed"]) for i, r in enumerate(order)]))
                line_err_rpi = float(np.mean([abs(1 + i // 16 - r["seed"]) for i, r in enumerate(order_r)]))
                tot["line_err"].append(line_err)
                tot["line_err_rpi"].append(line_err_rpi)
            res["seasons"][s] = {"at_large": n_at, "misses": m, "misses_rpi_rule": m_rpi, "host_hits": hh,
                                 "host_hits_rpi_rule": hh_rpi, "seed_line_mae": line_err,
                                 "seed_line_mae_rpi_rule": line_err_rpi}
            tot["misses"] += m
            tot["misses_rpi"] += m_rpi
            tot["at_large"] += n_at
            tot["host_hits"] += hh
            tot["host_hits_rpi"] += hh_rpi
            test_rows += el
            test_f += field_
            log(f"  {sport} {s}: at-large {n_at} misses {m} (RPI rule {m_rpi}); hosts {hh}/16 (RPI {hh_rpi})")
        yt = np.array([r["in_field"] for r in test_rows], float)
        res["test_at_large"] = ll_brier(1 / (1 + np.exp(-X(test_rows) @ b_at)), yt)
        res["test_at_large_rpi_only"] = ll_brier(1 / (1 + np.exp(-X(test_rows)[:, :2] @ b_rpi)), yt)
        yh = np.array([r["host"] for r in test_f], float)
        res["test_host"] = ll_brier(1 / (1 + np.exp(-X(test_f) @ b_host)), yh)
        res["test_host_rpi_only"] = ll_brier(1 / (1 + np.exp(-X(test_f)[:, :2] @ b_host_rpi)), yh)
        res["totals"] = {k: (float(np.mean(v)) if isinstance(v, list) and v else v) for k, v in tot.items()}
        res["n_test_seasons"] = len([s for s in TEST[sport] if s in tables])
        out["sports"][sport] = res
    return out

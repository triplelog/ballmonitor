"""College baseball & softball projections. See MODEL.md."""

from __future__ import annotations

import ast
import datetime as dt
import json
import statistics
from collections import ChainMap
from typing import Any, Callable

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core import formula as formula_engine
from ballmonitor.models.college_diamond import data as D
from ballmonitor.models.college_diamond.ratings import RatingParams, fit, midweek_flags
from ballmonitor.models.college_diamond.rpi import RpiWeights, ranks, rpi
from ballmonitor.models.college_diamond.sim import SimInputs, SimParams, Simulator, quantile

SPORTS = ("baseball", "softball")
PRIOR_DEPTH = 3          # seasons of rating history used to build the preseason prior
CONF_SHORT = {"Coastal Athletic": "CAA", "Conference USA": "CUSA", "Missouri Valley": "MVC",
              "Mountain West": "MWC", "Western Athletic": "WAC", "Summit League": "Summit",
              "Horizon League": "Horizon", "Patriot League": "Patriot", "Ivy League": "Ivy",
              "Mid-American": "MAC", "America East": "AmEast", "Atlantic 10": "A-10", "West Coast": "WCC",
              "Ohio Valley": "OVC", "Southern": "SoCon", "Independent": "Ind."}
LABEL_WIDTH = 34   # keeps the result table inside 78 columns


def label(name: str, conf: str) -> str:
    text = f"{name} ({CONF_SHORT.get(conf, conf)})"
    return text if len(text) <= LABEL_WIDTH else text[:LABEL_WIDTH - 1] + "…"


_CACHE: dict = {}  # one simulation per (sport, season, as_of, params) serves every team
ROUND_NAMES = {"baseball": "Omaha (CWS)", "softball": "OKC (WCWS)"}


def fast_formula(p, name: str) -> Callable[..., float]:
    """Compile a config formula once (it has passed formula.check's whitelist when the
    config was validated) so the Monte Carlo can call it thousands of times."""
    spec = p.formulas[name]
    formula_engine.check(spec.expr, set(p.numeric_values()) | set(spec.variables))
    code = compile(ast.parse(spec.expr.strip(), mode="eval"), f"<formula {name}>", "eval")
    base = {**formula_engine.FUNCTIONS, **formula_engine.CONSTANTS, **p.numeric_values()}
    glob = {"__builtins__": {}}
    return lambda **v: float(eval(code, glob, ChainMap(v, base)))  # noqa: S307 (whitelisted AST)


def selection_date(sport: str, season: int) -> dt.date:
    cov = json.loads((D.DATA_DIR / "coverage.json").read_text())
    return dt.date.fromisoformat(cov[f"{sport} {season}"]["selection"])


def rating_params(p, sport: str) -> RatingParams:
    g = lambda k: p[f"{sport}_{k}"]  # noqa: E731
    return RatingParams(margin_cap=float(g("margin_cap")), margin_power=float(g("margin_power")),
                        ridge=float(g("ridge")), midweek_ridge=float(g("midweek_ridge")),
                        midweek_beta=float(g("midweek_beta")), midweek_weight=float(g("midweek_weight")),
                        half_life_days=float(g("half_life_days")), prior_carry=float(g("prior_carry")),
                        split_midweek=bool(g("midweek_split")))


def preseason_prior(sport: str, season: int, rp: RatingParams, depth: int = PRIOR_DEPTH) -> dict[str, float]:
    """prior_carry * last season's final rating (centred), built recursively `depth` deep."""
    if rp.prior_carry <= 0 or depth <= 0:
        return {}
    seasons = sorted({g.season for g in D.load_games(sport)})
    prev = [s for s in seasons if s < season]
    if not prev:
        return {}
    last = prev[-1]
    games = D.season_games(sport, last)
    end = max(g.day for g in games) + dt.timedelta(days=1)
    final = fit(games, RatingParams(**{**rp.__dict__, "half_life_days": 0.0}), end,
                preseason_prior(sport, last, rp, depth - 1))
    mean = sum(final.weekend.values()) / len(final.weekend)
    return {t: rp.prior_carry * (v - mean) for t, v in final.weekend.items()}


def find_team(key: str, teams: dict[str, dict]) -> str:
    k = key.strip().lower()
    norm = lambda s: s.lower().replace(".", "").replace("state", "st").replace("-", " ").strip()  # noqa: E731
    for t, v in teams.items():
        if k in (t, v["name"].lower()):
            return t
    for t, v in teams.items():
        if norm(k) in (norm(t), norm(v["name"])):
            return t
    raise ValueError(f"unknown team {key!r} for this season; use an NCAA name such as "
                     f"{', '.join(sorted(v['name'] for v in teams.values())[:5])} ... (data/teams_<sport>.csv)")


class CollegeDiamondModel(BaseModel):
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        sport = str(inputs.get("sport", "baseball")).strip().lower()
        if sport not in SPORTS:
            raise ValueError("input 'sport' must be 'baseball' or 'softball'")
        season = int(inputs.get("season", 2026))
        all_teams = D.load_teams(sport)
        if season not in all_teams:
            raise ValueError(f"no {sport} data for {season}; seasons: {sorted(all_teams)}")
        teams = all_teams[season]
        sel = selection_date(sport, season)
        raw_as_of = str(inputs.get("as_of", "selection")).strip()
        as_of = sel if raw_as_of.lower() in ("selection", "selection eve") else dt.date.fromisoformat(raw_as_of)
        steps: list[str] = []
        if as_of > sel:
            steps.append(f"as_of {as_of} is after selection ({sel}); in-tournament updating is not "
                         f"supported, so the projection is made from selection eve.")
            as_of = sel
        team = find_team(str(inputs.get("team", "")), teams) if inputs.get("team") else None

        key = (sport, season, as_of, tuple(sorted((k, repr(v.value)) for k, v in p.specs.items())),
               tuple(sorted((k, f.expr) for k, f in p.formulas.items())))
        if key not in _CACHE:
            if len(_CACHE) > 8:
                _CACHE.clear()
            _CACHE[key] = self._simulate(sport, season, as_of, sel, teams)
        sim_steps, summary, ratings, now_rpi, n, n_nat, tour, n_formats, done = _CACHE[key]
        steps += sim_steps
        top = int(inputs.get("top", 8))
        outcomes: list[Outcome] = []
        inputs_disp = {"Sport": sport, "Season": f"{season} (historical; data complete)", "As of": str(as_of),
                       "Selection": str(sel)}
        if team:
            s = summary[team]
            name, conf = teams[team]["name"], teams[team]["conference"]
            inputs_disp["Team"] = f"{name} ({conf})"
            g = "NCAA tournament"
            outcomes += [
                Outcome(f"{name[:LABEL_WIDTH - 21]} makes the NCAA field", probability=s["bid"], fmt="pct", group=g,
                        note="automatic or at-large"),
                Outcome("Automatic bid (conference)", probability=s["auto_bid"], fmt="pct", group=g),
                Outcome("Hosts a regional", probability=s["host"], fmt="pct", group=g),
                Outcome("National seed", probability=s["national_seed"], fmt="pct", group=g,
                        note=f"top {n_nat}"),
                Outcome("Expected seed line if in field", estimate=s["seed_line"], fmt="number", group=g,
                        note="1 = host ... 4") if s["seed_line"] is not None else
                Outcome("Expected seed line if in field", probability=0.0, fmt="pct", group=g, note="never in"),
                Outcome("Wins its regional", probability=s["regional"], fmt="pct", group=g),
                Outcome(f"Reaches {ROUND_NAMES[sport]}", probability=s["super"], fmt="pct",
                        group=g),
                Outcome("Reaches the finals", probability=s["finals"], fmt="pct", group=g),
                Outcome("Wins the national title", probability=s["title"], fmt="pct", group=g),
            ]
            g = "Season"
            outcomes += [
                Outcome("Final wins (incl. postseason)", estimate=s["wins"], interval=s["wins_iv"], fmt="number",
                        group=g, note=f"losses {s['losses']:.1f}"),
                Outcome("Regular-season wins", estimate=s["reg_wins"], interval=s["reg_wins_iv"], fmt="number",
                        group=g, note=f"losses {s['reg_losses']:.1f}"),
                Outcome("Conference wins (reg. season)", estimate=s["conf_wins"], interval=s["conf_wins_iv"],
                        fmt="number", group=g, note=f"losses {s['conf_losses']:.1f}"),
                Outcome("Conference regular-season title", probability=s["reg_title"], fmt="pct", group=g,
                        note="incl. ties"),
                Outcome("Conference tournament title", probability=s["conf_tourney"], fmt="pct", group=g),
                Outcome("RPI rank at selection (median)", estimate=s["rpi_rank"], fmt="int", group=g,
                        note=f"now {now_rpi.get(team, '-')}"),
                Outcome("Rating (runs vs avg D-I, neutral)",
                        estimate=round(ratings.weekend[team] * float(p[f'{sport}_runs_per_unit']), 2),
                        fmt="number", group=g, note=f"rank {ranks(ratings.weekend)[team]}"),
            ]
        contenders = sorted(teams, key=lambda t: -summary[t]["title"])[:top]
        for t in contenders:
            s = summary[t]
            outcomes.append(Outcome(label(teams[t]["name"], teams[t]["conference"]), probability=s["title"],
                                    fmt="pct", group="Title contenders (P title)",
                                    note=f"host {s['host']:.0%}, final 4 {s['finals']:.0%}"[:30]))
        bubble = sorted((t for t in teams if 0.15 <= summary[t]["bid"] <= 0.85 and summary[t]["auto_bid"] < 0.5),
                        key=lambda t: -summary[t]["bid"])[:top]
        for t in bubble:
            s = summary[t]
            outcomes.append(Outcome(label(teams[t]["name"], teams[t]["conference"]), probability=s["bid"],
                                    fmt="pct", group="Bubble (P bid)",
                                    note=f"RPI now {now_rpi.get(t, '-')}, sel. {s['rpi_rank']:.0f}"))
        if not outcomes:
            raise ValueError("nothing to show")
        actual = self._actual(team, tour) if team else None
        if actual:
            steps.append(f"What actually happened in {season}: {actual}.")
        extras = {
            "sport": sport, "season": season, "as_of": str(as_of), "selection": str(sel), "team": team,
            "simulations": n, "home_edge": ratings.home_edge, "resid_sd": ratings.resid_sd,
            "teams": summary,
            "rating": {t: round(ratings.weekend[t], 4) for t in teams},
            "team_info": {t: {"name": teams[t]["name"], "conference": teams[t]["conference"]} for t in summary},
            "rpi_rank_now": now_rpi, "formats_used": n_formats, "finished_tournaments": done,
        }
        return self.prediction(inputs=inputs_disp, outcomes=outcomes, steps=steps, interval_level=0.8,
                               extras=extras)

    def _simulate(self, sport, season, as_of, sel, teams):
        p = self.params
        steps: list[str] = []
        games = sorted(D.season_games(sport, season), key=lambda g: g.date)
        flags = midweek_flags(games)
        completed = [g for g in games if g.day < as_of and g.game_type != "N"]
        remaining = [(g, f) for g, f in zip(games, flags) if g.day >= as_of and g.game_type == "R"]
        rp = rating_params(p, sport)
        prior = preseason_prior(sport, season, rp)
        cflags = [f for g, f in zip(games, flags) if g.day < as_of and g.game_type != "N"]
        ratings = fit(completed, rp, as_of, prior, cflags)
        for t in teams:
            ratings.weekend.setdefault(t, prior.get(t, 0.0))
            ratings.midweek.setdefault(t, 0.0)
        steps.append(
            f"Data: {len(games)} D-I {sport} games in {season} ({len(completed)} before {as_of}, "
            f"{len(remaining)} regular-season games left); {len(teams)} D-I teams; selection {sel}.")
        steps.append(
            f"Ratings: weighted ridge on margins T(m) = sign(m)*min(|m|,{rp.margin_cap:g})^{rp.margin_power:g}, "
            f"ridge {rp.ridge:g} games toward a prior of {rp.prior_carry:g} x last season's rating, "
            f"half-life {rp.half_life_days:g} days, midweek split {'on' if rp.split_midweek else 'off'}; "
            f"home edge {ratings.home_edge:.2f}, residual sd {ratings.resid_sd:.2f} (transformed units).")

        scale = float(p[f"{sport}_win_scale"])
        wp_f = fast_formula(p, "win_probability")
        win_prob = lambda d: wp_f(diff=d, scale=scale)  # noqa: E731
        sd_f = fast_formula(p, "rating_sd")
        rating_sd = {t: max(sd_f(resid_sd=ratings.resid_sd, games=ratings.played.get(t, 0), ridge=rp.ridge), 0.0)
                     for t in teams}
        sel_f, host_f = fast_formula(p, "selection_score"), fast_formula(p, "host_score")
        sel_rpi, host_rpi = float(p[f"{sport}_sel_rpi"]), float(p[f"{sport}_host_rpi"])
        steps.append(f"Win probability: {p.expr('win_probability')} with scale {scale:g}; "
                     f"P(win) for a 1-run-better team at home = "
                     f"{win_prob(1 / float(p[f'{sport}_runs_per_unit']) + ratings.home_edge):.1%}.")

        loc = bool(p[f"{sport}_rpi_location"])
        rw = float(p.rpi_road_win)
        weights = RpiWeights(float(p.rpi_w_wp), float(p.rpi_w_owp), float(p.rpi_w_oowp),
                             home_win=2 - rw if loc else 1.0, road_win=rw if loc else 1.0,
                             home_loss=rw if loc else 1.0, road_loss=2 - rw if loc else 1.0)
        now_rpi = ranks(rpi([(g.home, g.away, 1.0 if g.margin > 0 else 0.0 if g.margin < 0 else 0.5, g.neutral)
                             for g in completed], weights))

        formats = dict(D.load_formats().get(sport, {}).get(str(season), {}))
        tour = D.load_tournaments().get(sport, {}).get(str(season), {})
        done = self._finished_tournaments(sport, games, teams, as_of, tour)
        n_nat = int(tour.get("n_national_seeds", 16) or 16)
        si = SimInputs(sport, season, as_of, teams, completed, remaining, ratings.weekend, ratings.midweek,
                       ratings.home_edge, rating_sd, formats, done, n_nat, weights)
        sp = SimParams(
            simulations=int(p.simulations), seed=int(p.seed), win_prob=win_prob,
            selection_score=lambda rk, rr, w: sel_f(rpi_rank=rk, rating_rank=rr, win_pct=w, sel_rpi=sel_rpi),
            host_score=lambda rk, rr, w: host_f(rpi_rank=rk, rating_rank=rr, win_pct=w, host_rpi=host_rpi),
            committee_noise=float(p.committee_noise), min_at_large_win_pct=float(p.min_at_large_win_pct),
            field_size=int(p.field_size), hosts=int(p.hosts),
            conf_tourney_home=1.0 if p.conf_tourney_home else 0.0,
            keep_conference_apart=bool(p.keep_conference_apart))
        tally = Simulator(si, sp).run()
        n = tally.n
        n_formats = sum(1 for c in {v["conference"] for v in teams.values()} if c in formats)
        steps.append(
            f"Simulated {n} seasons (seed {sp.seed}): remaining games, standings, {n_formats} conference "
            f"tournaments per data/conference_formats.json ({len(done)} already finished: real champion), "
            f"RPI ({'site-weighted' if loc else 'unweighted'}), committee proxy {p.expr('selection_score')} "
            f"+ logistic noise x{sp.committee_noise:g}, {sp.hosts} hosts by {p.expr('host_score')}, "
            "S-curve regionals, supers 1v16 ..., two 4-team World Series brackets, best-of-3 finals.")

        summary = {t: self._summary(t, tally) for t in teams}
        return steps, summary, ratings, now_rpi, n, n_nat, tour, n_formats, done

    # --- backtest (data/backtest.csv, written by research.py backtest) -------------
    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        as_of = "selection" if row["snapshot"] == "selection" else row["as_of"]
        inputs = {"sport": row["sport"], "season": int(row["season"]), "as_of": as_of, "team": row["team"]}
        actual = {"bid": int(row["made_field"]), "host": int(row["host"]), "stage": int(row["stage_reached"]),
                  "wins": int(row["final_wins"])}
        return inputs, actual

    def backtest_group(self, row: dict[str, str]) -> str | None:
        return f"{row['sport']} {row['snapshot']} {row['split']}"

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """P(bid) (primary), P(host), stage reached (6 classes) and final wins."""
        import math
        s = prediction.extras["teams"][prediction.extras["team"]]
        clip = lambda q: min(max(q, 1e-3), 1 - 1e-3)  # noqa: E731
        cum = [1.0, s["bid"], s["regional"], s["super"], s["finals"], s["title"]]
        stage = [max(cum[i] - (cum[i + 1] if i < 5 else 0.0), 0.0) for i in range(6)]
        return {
            "brier": (s["bid"] - actual["bid"]) ** 2,
            "log_loss": -math.log(clip(s["bid"] if actual["bid"] else 1 - s["bid"])),
            "brier_host": (s["host"] - actual["host"]) ** 2,
            "log_loss_stage": -math.log(clip(stage[actual["stage"]])),
            "abs_error": abs(s["wins"] - actual["wins"]),
            "in_80": float(s["wins_iv"][0] <= actual["wins"] <= s["wins_iv"][1]),
        }

    @staticmethod
    def _finished_tournaments(sport, games, teams, as_of, tour) -> dict[str, str]:
        """Conference tournaments whose every game is before as_of -> champion (baseball:
        the recorded automatic qualifier; else the winner of the conference's last game)."""
        last: dict[str, Any] = {}
        for g in games:
            if g.game_type == "C":
                c = teams[g.home]["conference"]
                if c not in last or g.date >= last[c].date:
                    last[c] = g
        aq = {teams[t]["conference"]: t for t, v in tour.get("field", {}).items()
              if v.get("auto_bid") and t in teams}
        out = {}
        for c, g in last.items():
            if g.day < as_of:
                out[c] = aq.get(c) or (g.home if g.margin > 0 else g.away)
        return out

    @staticmethod
    def _summary(t: str, tally) -> dict:
        n = max(tally.n, 1)
        c = tally.c[t]
        lines = tally.seed_line.get(t, [])
        mean = lambda xs: statistics.fmean(xs) if xs else 0.0  # noqa: E731
        iv = lambda xs: (quantile(xs, 0.1), quantile(xs, 0.9))  # noqa: E731
        return {
            "bid": c["bid"] / n, "auto_bid": c["auto_bid"] / n, "host": c["host"] / n,
            "national_seed": c["national_seed"] / n, "regional": c["regional"] / n, "super": c["super"] / n,
            "finals": c["finals"] / n, "title": c["title"] / n, "reg_title": c["reg_title"] / n,
            "conf_tourney": c["conf_tourney"] / n,
            "seed_line": round(mean(lines), 2) if lines else None,
            "wins": round(mean(tally.wins[t]), 1), "losses": round(mean(tally.losses[t]), 1),
            "wins_iv": iv(tally.wins[t]),
            "reg_wins": round(mean(tally.reg_wins[t]), 1), "reg_losses": round(mean(tally.reg_losses[t]), 1),
            "reg_wins_iv": iv(tally.reg_wins[t]),
            "conf_wins": round(mean(tally.conf_wins[t]), 1), "conf_losses": round(mean(tally.conf_losses[t]), 1),
            "conf_wins_iv": iv(tally.conf_wins[t]),
            "rpi_rank": statistics.median(tally.rpi_rank[t]) if tally.rpi_rank[t] else None,
        }

    @staticmethod
    def _actual(team: str, tour: dict) -> str | None:
        f = tour.get("field", {}).get(team)
        if not tour.get("field"):
            return None
        if f is None:
            return "not in the NCAA field"
        stage = ["", "lost in the regional", "lost in the super regional", "lost at the World Series",
                 "lost in the finals", "won the national title"][min(f["reached"], 5)]
        bits = [f"{'host, ' if f['host'] else ''}"
                f"{'national seed ' + str(f['national_seed']) + ', ' if f.get('national_seed') else ''}"
                f"{str(f['seed']) + ' seed, ' if f.get('seed') else ''}{stage}"]
        return "".join(bits).strip(", ")

"""DAD (Deviations Above Default) rating model. See MODEL.md."""

from __future__ import annotations

import math
from datetime import date
from statistics import NormalDist
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.dad.matchups import classify_game, detect_mlb_division

STANDARD_NORMAL = NormalDist()


def _poisson_pmf(k: int, lmbda: float) -> float:
    if k < 0 or lmbda <= 0:
        return 0.0
    return math.exp(-lmbda + k * math.log(lmbda) - math.lgamma(k + 1))


def _skellam_win_prob(lmbda1: float, lmbda2: float, draw_val: float = 0.5) -> float:
    """Win probability + draw_val * draw probability under independent Poisson distributions."""
    p_draw = 0.0
    p_win = 0.0
    for j in range(25):
        pj2 = _poisson_pmf(j, lmbda2)
        if pj2 == 0.0:
            continue
        p_draw += _poisson_pmf(j, lmbda1) * pj2
        for k in range(1, 25):
            p_win += _poisson_pmf(j + k, lmbda1) * pj2
    return p_win + draw_val * p_draw


# Canonical sports and the names accepted for each.
SPORT_ALIASES: dict[str, tuple[str, ...]] = {
    "basketball": ("basketball", "mbb", "ncaab", "cbb", "nba", "mens_basketball", "college_basketball"),
    "wbb": ("wbb", "ncaaw", "womens_basketball", "women_basketball", "wcbb"),
    "football": ("football", "cfb", "ncaaf", "nfl", "college_football"),
    "soccer": ("soccer", "epl", "premier_league", "ucl", "laliga", "la_liga", "seriea", "serie_a",
               "bundesliga", "bundes", "ligue1", "mls"),
    "mlb": ("mlb", "baseball"),
    "college_baseball": ("college_baseball", "ncaa_baseball"),
    "softball": ("softball", "college_softball", "ncaa_softball"),
}
_SPORT_LOOKUP = {alias: canon for canon, aliases in SPORT_ALIASES.items() for alias in aliases}

# Baseline names accepted for every sport -> canonical baseline key.
BASELINE_ALIASES: dict[str, tuple[str, ...]] = {
    "champion": ("champion", "title", "title_contender", "league_winner", "national_champion",
                 "world_series", "ws_champ", "omaha", "omaha_champ", "wcws", "wcws_champ"),
    "top_4_seed": ("top_4_seed", "top4_seed", "top4", "top_4", "4_seed", "four_seed", "host",
                   "national_seed", "division_champ", "division_winner", "ucl", "champions_league"),
    "europa": ("europa", "uel", "conference", "europe"),
    "average": ("average", "midtable", "mid_table", "median", "d1_average", "500"),
    "bubble": ("bubble", "standard_bubble", "ncaab_bubble", "wbb_bubble", "regional_bubble",
               "wildcard", "wildcard_bubble", "relegation", "relegation_bubble", "survival"),
    "replacement": ("replacement", "replacement_level", "promoted", "war_baseline"),
}
_BASELINE_LOOKUP = {alias: canon for canon, aliases in BASELINE_ALIASES.items() for alias in aliases}

# sport -> canonical baseline -> (label, param name)
BASELINES: dict[str, dict[str, tuple[str, str]]] = {
    "soccer": {
        "champion": ("Title Contender Standard", "soccer_champion_rating"),
        "top_4_seed": ("Champions League (Top 4) Standard", "soccer_ucl_rating"),
        "europa": ("European Places Standard", "soccer_europa_rating"),
        "average": ("Mid-Table Average (10th)", "soccer_average_rating"),
        "bubble": ("Relegation Survival Bubble (17th)", "soccer_relegation_bubble_rating"),
        "replacement": ("Replacement Level (20th)", "soccer_replacement_rating"),
    },
    "wbb": {
        "champion": ("NCAAW Champion Standard", "wbb_champion_rating"),
        "top_4_seed": ("NCAA Women's 4-Seed Host", "wbb_top4_seed_rating"),
        "average": ("Division-I WBB Average", "wbb_average_rating"),
        "bubble": ("NCAA Women's Bubble", "wbb_bubble_rating"),
        "replacement": ("Replacement Level", "wbb_replacement_rating"),
    },
    "softball": {
        "champion": ("WCWS Champion Standard", "softball_champion_rating"),
        "top_4_seed": ("NCAA Softball National Seed", "softball_national_seed_rating"),
        "average": ("Division-I Softball Average", "softball_average_rating"),
        "bubble": ("NCAA Softball Regional Bubble", "softball_regional_bubble_rating"),
        "replacement": ("Replacement Level", "softball_replacement_rating"),
    },
    "college_baseball": {
        "champion": ("Omaha Champion Standard", "college_baseball_champion_rating"),
        "top_4_seed": ("NCAA National Seed", "college_baseball_national_seed_rating"),
        "average": ("Division-I Average", "college_baseball_average_rating"),
        "bubble": ("NCAA Regional Bubble", "college_baseball_regional_bubble_rating"),
        "replacement": ("Replacement Level", "college_baseball_replacement_rating"),
    },
    "mlb": {
        "champion": ("World Series Champion Standard", "mlb_champion_rating"),
        "top_4_seed": ("MLB Division Champion", "mlb_division_champ_rating"),
        "average": ("MLB Average (.500)", "mlb_average_rating"),
        "bubble": ("MLB Wild Card Bubble", "mlb_wildcard_bubble_rating"),
        "replacement": ("MLB Replacement Level", "mlb_replacement_rating"),
    },
    # Football presets are FBS college values (NFL ratings are narrower: pass a number).
    "football": {
        "champion": ("FBS Title Contender (~#2)", "football_champion_rating"),
        "top_4_seed": ("FBS Top-4 (CFP bye)", "football_top4_rating"),
        "average": ("FBS Average", "football_average_rating"),
        "bubble": ("12-Team Playoff Bubble (~#12)", "football_bubble_rating"),
        "replacement": ("FBS Replacement Level (~#120)", "football_replacement_rating"),
    },
    "basketball": {
        "champion": ("National Champion Standard", "champion_rating_ncaab"),
        "top_4_seed": ("Top-4 Seed Standard", "top4_seed_rating_ncaab"),
        "average": ("Division-I Average", "average_rating_ncaab"),
        "bubble": ("Standard Bubble Team", "bubble_rating_ncaab"),
        "replacement": ("Replacement Level", "replacement_rating_ncaab"),
    },
}

# Football margins clump at these key numbers (Stern 1991).
FOOTBALL_KEY_NUMBERS = (3, 7)

# Sport -> family whose strength settings apply (prior_games_<f>, half_life_days_<f>).
SPORT_FAMILY = {"basketball": "basketball", "wbb": "basketball", "football": "football",
                "soccer": "soccer", "mlb": "baseball", "college_baseball": "college_baseball",
                "softball": "softball"}
# Sport -> param holding the per-game margin noise σ.
MARGIN_SD_PARAM = {"basketball": "basketball_margin_sd", "wbb": "wbb_margin_sd",
                   "football": "football_margin_sd", "soccer": "soccer_margin_sd",
                   "mlb": "mlb_margin_sd", "college_baseball": "college_baseball_margin_sd",
                   "softball": "softball_margin_sd"}
SPORT_UNIT = {"basketball": "pts", "wbb": "pts", "football": "pts", "soccer": "goals",
              "mlb": "runs", "college_baseball": "runs", "softball": "runs"}
# Keys copied when a single game is given at the top level of the inputs.
GAME_KEYS = ("opponent", "opponent_rating", "margin", "team_score", "opponent_score",
             "location", "xg_for", "xg_against", "xg_margin", "xgd", "weight", "date", "notes")


def _norm(text: Any) -> str:
    return str(text).strip().lower().replace("'", "").replace("-", "_").replace(" ", "_")


def canonical_sport(sport: Any) -> str:
    """Map a sport name or alias to its canonical key (ValueError if unknown)."""
    key = _norm(sport)
    if key not in _SPORT_LOOKUP:
        raise ValueError(
            f"unknown sport {sport!r}; use one of: "
            + ", ".join(f"{c} ({'/'.join(a[1:])})" if len(a) > 1 else c for c, a in SPORT_ALIASES.items())
        )
    return _SPORT_LOOKUP[key]


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number, got {value!r}")
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number, got {value!r}") from None
    if math.isnan(out) or math.isinf(out):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return out


class DadModel(BaseModel):
    def _resolve_baseline(self, baseline_input: Any, sport: str) -> tuple[str, float]:
        """Convert baseline name or number into (label, net_rating). `sport` is canonical."""
        p = self.params

        if isinstance(baseline_input, (int, float)) and not isinstance(baseline_input, bool):
            val = _num(baseline_input, "baseline")
            return f"Custom ({val:+.2f})", val

        b_str = _norm(baseline_input if baseline_input not in (None, "") else p.default_baseline)

        # Numeric string like "1.25" or "-1.5"
        try:
            val = float(b_str.replace("_", ""))
            if math.isfinite(val):
                return f"Custom ({val:+.2f})", val
        except ValueError:
            pass

        table = BASELINES.get(sport, BASELINES["basketball"])
        canon = _BASELINE_LOOKUP.get(b_str)
        if canon is None or canon not in table:
            raise ValueError(
                f"unknown baseline {baseline_input!r} for {sport}; use a number or one of: "
                + ", ".join(table)
            )
        label, param_name = table[canon]
        return label, float(getattr(p, param_name))

    def _get_sport_constants(self, sport: str) -> tuple[float | None, float, float | None, float | None]:
        """Return (margin_sd, home_advantage, total_scoring_units, pythagorean_exponent).

        Only the values the sport's win-strength method uses are set; the rest are None.
        Normal-CDF sports use margin_sd; soccer uses total goals (Skellam); baseball and
        softball use total runs + Pythagorean exponent.
        """
        p = self.params
        if sport == "softball":
            return None, float(p.home_advantage_softball), float(p.softball_total_runs), float(p.softball_exponent)
        if sport == "college_baseball":
            return (
                None,
                float(p.home_advantage_college_baseball),
                float(p.college_baseball_total_runs),
                float(p.college_baseball_exponent),
            )
        if sport == "mlb":
            return None, float(p.home_advantage_baseball), float(p.mlb_total_runs), float(p.mlb_exponent)
        if sport == "soccer":
            return None, float(p.home_advantage_soccer), float(p.soccer_total_goals), None
        if sport == "wbb":
            return float(p.wbb_margin_sd), float(p.home_advantage_wbb), None, None
        if sport == "football":
            return float(p.football_margin_sd), float(p.home_advantage_football), None, None
        return float(p.basketball_margin_sd), float(p.home_advantage_basketball), None, None

    def _method_text(self, sport: str) -> str:
        sigma, hca, total, exponent = self._get_sport_constants(sport)
        if sport in ("mlb", "college_baseball", "softball"):
            return (f"Pythagorean win strength (total runs = {total:g}, exponent = {exponent:g}), "
                    f"HCA = {hca:g} runs")
        if sport == "soccer":
            return (f"Skellam win strength (total goals = {total:g}, draw value = "
                    f"{self.params.soccer_draw_point_value:g}), HCA = {hca:g} goals")
        extra = (f", key-number bump {self.params.football_key_number_bump:g} at "
                 f"{'/'.join(str(k) for k in FOOTBALL_KEY_NUMBERS)}" if sport == "football" else "")
        return f"normal-CDF win strength Φ(margin / σ), σ = {sigma:g}{extra}, HCA = {hca:g} points"

    def _resolve_game_weight(
        self,
        team_name: str,
        opponent_name: str,
        game: dict[str, Any],
        sport: str,
    ) -> tuple[float, str]:
        """Determine weighting factor for a contest based on stakes, rotation usage, and auto-detection."""
        p = self.params
        s = sport  # canonical

        # 1. Direct explicit weight in game dict
        if "weight" in game:
            w = _num(game["weight"], f"{team_name} vs {opponent_name} weight")
            if w < 0:
                raise ValueError(f"{team_name} vs {opponent_name}: weight cannot be negative")
            return w, f"weight={w:g}"

        # 2. College Baseball rules (auto-detect conference, weekend, midweek, postseason)
        if s == "college_baseball":
            info = classify_game(team_name, opponent_name, game, sport)
            cls = info["classification"]
            reason = info["reason"]

            if cls == "postseason":
                w = float(p.college_baseball_postseason_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "conference":
                w = float(p.college_baseball_conference_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "weekend":
                w = float(p.college_baseball_weekend_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "midweek":
                w = float(p.college_baseball_midweek_weight)
                return w, f"{reason} (w={w:g})"

        # 3. College Softball rules (auto-detect conference, weekend, midweek, postseason)
        if s == "softball":
            info = classify_game(team_name, opponent_name, game, sport)
            cls = info["classification"]
            reason = info["reason"]

            if cls == "postseason":
                w = float(p.softball_postseason_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "conference":
                w = float(p.softball_conference_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "weekend":
                w = float(p.softball_weekend_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "midweek":
                w = float(p.softball_midweek_weight)
                return w, f"{reason} (w={w:g})"

        # 4. MLB division matchup auto-detection
        if s == "mlb":
            div_a = detect_mlb_division(team_name)
            div_b = detect_mlb_division(opponent_name)
            if div_a and div_b and div_a == div_b:
                w = float(p.mlb_division_weight)
                return w, f"auto-detected {div_a} matchup (w={w:g})"

        # 5. Soccer rules (European Cup, Derby, Domestic Cup)
        if s == "soccer":
            info = classify_game(team_name, opponent_name, game, sport)
            cls = info["classification"]
            reason = info["reason"]

            if cls == "european_cup":
                w = float(p.soccer_european_cup_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "derby":
                w = float(p.soccer_derby_weight)
                return w, f"{reason} (w={w:g})"
            if cls == "domestic_cup":
                w = float(p.soccer_domestic_cup_weight)
                return w, f"{reason} (w={w:g})"

        return 1.0, "w=1.0"

    def _calc_win_prob(self, margin_or_spread: float, sport: str) -> float:
        """Map a point/goal/run margin or spread to an implied win probability."""
        p = self.params
        sigma, _, total, exponent = self._get_sport_constants(sport)

        if sport in ("mlb", "college_baseball", "softball"):
            # Pythagorean expectation on run differential
            r_for = max(0.01, (total + margin_or_spread) / 2.0)
            r_against = max(0.01, (total - margin_or_spread) / 2.0)
            prob = (r_for ** exponent) / (r_for ** exponent + r_against ** exponent)
        elif sport == "soccer":
            # Skellam distribution with expected match total goals
            l1 = max(0.05, (total + margin_or_spread) / 2.0)
            l2 = max(0.05, (total - margin_or_spread) / 2.0)
            prob = _skellam_win_prob(l1, l2, float(p.soccer_draw_point_value))
        elif sport == "football":
            # Normal CDF plus a step at each key number crossed (3 and 7): a win by 3+
            # is worth a little more than the normal curve says. Steps are cumulative so
            # the mapping stays monotone in the margin.
            base = STANDARD_NORMAL.cdf(margin_or_spread / sigma)
            crossed = sum(1 for k in FOOTBALL_KEY_NUMBERS if abs(margin_or_spread) >= k - 0.5)
            sign = 1.0 if margin_or_spread > 0 else -1.0
            prob = base + sign * crossed * float(p.football_key_number_bump)
        else:
            # Basketball Gaussian probit
            prob = STANDARD_NORMAL.cdf(margin_or_spread / sigma)

        return min(max(prob, float(p.min_prob_clamp)), float(p.max_prob_clamp))

    # ── v0.7.0 helpers: margin scale, strength, result-based WAD ──────────────

    def _family(self, sport: str) -> str:
        """Sport family whose strength settings (prior games, half-life) apply."""
        return SPORT_FAMILY[sport]

    def _margin_sd(self, sport: str) -> float:
        """Per-game margin noise σ (points/goals/runs) used to express deviations."""
        return float(getattr(self.params, MARGIN_SD_PARAM[sport]))

    def _expected_result(self, spread: float, sport: str) -> float:
        """P(win) + ½·P(draw) for a team favoured by `spread` (a real result probability).

        Normal CDF Φ(spread/σ) in basketball/football (no key-number steps: those shape
        win strength from a margin, not the chance of winning), Skellam in soccer,
        Pythagorean run expectation in baseball/softball.
        """
        p = self.params
        if sport in ("basketball", "wbb", "football"):
            prob = STANDARD_NORMAL.cdf(spread / self._margin_sd(sport))
        else:
            prob = self._calc_win_prob(spread, sport)
        return min(max(prob, float(p.min_prob_clamp)), float(p.max_prob_clamp))

    def _game_inputs(self, team_name: str, idx: int, g: Any, base_hca: float) -> dict[str, Any]:
        """Validate one game dict -> opponent, rating, location, margin, xG margin, date."""
        if not isinstance(g, dict):
            raise ValueError(f"{team_name}: game {idx} must be a table with opponent/opponent_rating/margin")
        opp = str(g.get("opponent", f"Opponent {idx}")).strip()
        where = f"{team_name} game {idx} ({opp})"
        if "opponent_rating" not in g:
            raise ValueError(f"{where}: missing opponent_rating")
        opp_rating = _num(g["opponent_rating"], f"{where} opponent_rating")
        loc = str(g.get("location", "neutral")).strip().lower()
        if loc in ("home", "h"):
            loc, sign, loc_label = "home", 1.0, "vs"
        elif loc in ("away", "road", "a"):
            loc, sign, loc_label = "away", -1.0, "@"
        elif loc in ("neutral", "n", ""):
            loc, sign, loc_label = "neutral", 0.0, "vs (N)"
        else:
            raise ValueError(f"{where}: location must be home, away or neutral, got {g['location']!r}")
        if "margin" in g:
            margin = _num(g["margin"], f"{where} margin")
        elif "team_score" in g and "opponent_score" in g:
            margin = _num(g["team_score"], f"{where} team_score") - _num(
                g["opponent_score"], f"{where} opponent_score")
        else:
            raise ValueError(f"{where}: give margin, or team_score and opponent_score")
        xg_margin = None
        xg = None
        if "xg_for" in g and "xg_against" in g:
            xg = (max(0.01, _num(g["xg_for"], f"{where} xg_for")),
                  max(0.01, _num(g["xg_against"], f"{where} xg_against")))
            xg_margin = xg[0] - xg[1]
        elif "xg_margin" in g or "xgd" in g:
            xg_margin = _num(g.get("xg_margin", g.get("xgd")), f"{where} xg_margin")
        return {"opp": opp, "opp_rating": opp_rating, "loc": loc, "loc_label": loc_label,
                "hca": sign * base_hca, "margin": margin, "xg": xg, "xg_margin": xg_margin,
                "date": _parse_date(g.get("date"), where)}

    def _eval_team_games(
        self,
        team_name: str,
        games: list[dict[str, Any]],
        sport: str,
        baseline_label: str,
        baseline_rating: float,
        as_of: Any = None,
    ) -> dict[str, Any]:
        p = self.params
        _, base_hca, _, _ = self._get_sport_constants(sport)
        if not isinstance(games, list) or not games:
            raise ValueError(f"{team_name}: needs at least one game in [[games]]")
        probit = p.dad_scale == "probit"
        result_wad = p.wad_mode == "result"
        sigma = self._margin_sd(sport)
        fam = self._family(sport)
        prior_games = float(getattr(p, f"prior_games_{fam}"))
        half_life = float(getattr(p, f"half_life_days_{fam}"))
        blend = float(p.xg_blend)
        draw_val = float(p.soccer_draw_point_value)

        parsed = [self._game_inputs(team_name, i, g, base_hca) for i, g in enumerate(games, 1)]
        dates = [x["date"] for x in parsed if x["date"] is not None]
        ref = _parse_date(as_of, "as_of") if as_of not in (None, "") else (max(dates) if dates else None)

        def perf(margin: float) -> float:
            return p.formula("game_performance", margin=margin, sigma=sigma)

        game_records = []
        total_dad = total_wad = total_xdad = 0.0
        w_sum = w_adj = 0.0          # recency-weighted sums for the strength rating
        wins = draws = losses = 0
        has_xg = False
        for idx, (g, x) in enumerate(zip(games, parsed), 1):
            margin, opp_rating, hca = x["margin"], x["opp_rating"], x["hca"]
            if margin > 0:
                wins += 1
            elif margin < 0:
                losses += 1
            else:
                draws += 1
            result = 1.0 if margin > 0 else 0.0 if margin < 0 else draw_val
            weight, weight_label = self._resolve_game_weight(team_name, x["opp"], g, sport)
            exp_spread = p.formula("expected_spread", default_rating=baseline_rating,
                                   opponent_rating=opp_rating, hca=hca)
            # Strength: the game's opponent-adjusted performance (what it says the
            # team's rating is), recency-weighted. Stakes weights are résumé-only.
            performance = perf(margin)
            adjusted = performance + opp_rating - hca
            days_ago = (ref - x["date"]).days if (ref is not None and x["date"] is not None) else 0
            rw = p.formula("recency_weight", days_ago=max(days_ago, 0), half_life=half_life)
            w_sum += rw
            w_adj += rw * adjusted

            p_default = self._calc_win_prob(exp_spread, sport)
            p_actual = self._calc_win_prob(margin, sport)
            p_default_result = self._expected_result(exp_spread, sport)
            p_xg = None
            if x["xg_margin"] is not None:
                has_xg = True
                if x["xg"] is not None:
                    p_xg = _skellam_win_prob(x["xg"][0], x["xg"][1], draw_val)
                else:
                    tot = float(p.soccer_total_goals)
                    p_xg = _skellam_win_prob(max(0.05, (tot + x["xg_margin"]) / 2.0),
                                             max(0.05, (tot - x["xg_margin"]) / 2.0), draw_val)
            if probit:
                if p_xg is not None and blend > 0.0:
                    p_actual = (1.0 - blend) * p_actual + blend * p_xg
                g_dad = p.formula("game_dad_probit", p_actual=p_actual, p_default=p_default,
                                  weight=weight)
                g_xdad = (p.formula("game_dad_probit", p_actual=p_xg, p_default=p_default,
                                    weight=weight) if p_xg is not None else g_dad)
            else:
                eff = margin
                if x["xg_margin"] is not None and blend > 0.0:
                    eff = (1.0 - blend) * margin + blend * x["xg_margin"]
                g_dad = p.formula("game_dad", performance=perf(eff), expected_spread=exp_spread,
                                  sigma=sigma, weight=weight)
                g_xdad = (p.formula("game_dad", performance=perf(x["xg_margin"]),
                                    expected_spread=exp_spread, sigma=sigma, weight=weight)
                          if x["xg_margin"] is not None else g_dad)
            if result_wad:
                g_wad = p.formula("game_wad", result=result, p_default=p_default_result,
                                  weight=weight)
            else:
                g_wad = p.formula("game_wad_strength", p_actual=p_actual, p_default=p_default,
                                  weight=weight)
            total_dad += g_dad
            total_xdad += g_xdad
            total_wad += g_wad
            rec = {
                "game_idx": idx, "opponent": x["opp"], "opp_rating": opp_rating,
                "location": x["loc"], "loc_label": x["loc_label"], "margin": margin,
                "exp_spread": exp_spread, "performance": performance, "adjusted": adjusted,
                "recency_weight": rw, "p_default": p_default, "p_actual": p_actual,
                "p_default_result": p_default_result, "result": result,
                "weight": weight, "weight_label": weight_label, "dad": g_dad, "wad": g_wad,
            }
            if p_xg is not None:
                rec["p_xg"] = p_xg
                rec["xdad"] = g_xdad
                if x["xg"] is not None:
                    rec["xg_for"], rec["xg_against"] = x["xg"]
            game_records.append(rec)

        n_games = len(games)
        strength = p.formula("strength_rating", weighted_sum=w_adj, weight_total=w_sum,
                             prior_games=prior_games)
        strength_vs_default = strength - baseline_rating
        strength_dad = p.formula("strength_dad", strength=strength,
                                 default_rating=baseline_rating, sigma=sigma)
        raw_dad_pg = total_dad / n_games
        best_game = max(game_records, key=lambda r: r["dad"])
        worst_game = min(game_records, key=lambda r: r["dad"])
        return {
            "team": team_name,
            "dad_scale": p.dad_scale,
            "total_dad": total_dad,
            "total_wad": total_wad,
            "total_xdad": total_xdad,
            "luck_dad": total_dad - total_xdad,
            "has_xg": has_xg,
            # primary per-game number: shrunk strength in σ (margin scale) or the
            # v0.6.0 mean probit deviation (probit scale)
            "dad_per_game": raw_dad_pg if probit else strength_dad,
            "dad_per_game_raw": raw_dad_pg,
            "strength_rating": strength,
            "strength_vs_default": strength_vs_default,
            "strength_dad": strength_dad,
            "win_prob_vs_default": self._expected_result(strength_vs_default, sport),
            "adjusted_margin_raw": sum(r["adjusted"] for r in game_records) / n_games,
            "margin_per_game": sum(r["margin"] for r in game_records) / n_games,
            "sigma": sigma,
            "prior_games": prior_games,
            "half_life_days": half_life,
            "baseline_rating": baseline_rating,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "games_count": n_games,
            "game_records": game_records,
            "best_game": best_game,
            "worst_game": worst_game,
        }

    @staticmethod
    def _record(r: dict[str, Any]) -> str:
        if r["draws"]:
            return f"{r['wins']}-{r['draws']}-{r['losses']}"
        return f"{r['wins']}-{r['losses']}"

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        sport = canonical_sport(inputs.get("sport", "basketball"))
        baseline_input = inputs.get("baseline", p.default_baseline)
        base_label, base_rating = self._resolve_baseline(baseline_input, sport)
        method = self._method_text(sport)
        probit = p.dad_scale == "probit"
        unit = SPORT_UNIT[sport]
        sigma = self._margin_sd(sport)
        fam = self._family(sport)
        as_of = inputs.get("as_of")

        if probit:
            dad_rule = (f"DAD (v0.6.0 probit scale) = {p.expr('game_dad_probit')}, "
                        f"cap {p.game_dad_cap:g}σ; {method}.")
        else:
            dad_rule = (f"Game DAD = {p.expr('game_dad')} with performance = "
                        f"{p.expr('game_performance')}, σ = {sigma:g} {unit} "
                        f"(per-game margin noise).")
        wad_rule = (f"WAD = {p.expr('game_wad')} (result 1/½/0; p_default = chance the "
                    f"default team wins that game)" if p.wad_mode == "result"
                    else f"WAD (v0.6.0) = {p.expr('game_wad_strength')}")
        strength_rule = (
            f"Strength = {p.expr('strength_rating')} over adjusted games "
            f"(margin + opponent rating − home edge), prior_games = "
            f"{getattr(p, f'prior_games_{fam}'):g}, half-life = "
            f"{getattr(p, f'half_life_days_{fam}'):g} days (0 = off); "
            f"DAD per game = {p.expr('strength_dad')}.")

        teams_input = inputs.get("teams")
        if teams_input is not None:
            if not isinstance(teams_input, list) or not teams_input:
                raise ValueError("'teams' must be a non-empty list of tables ([[teams]] with name and games)")
            team_results = []
            for i, t_data in enumerate(teams_input, 1):
                if not isinstance(t_data, dict):
                    raise ValueError(f"team #{i} in [[teams]] must be a table with name and games")
                t_name = str(t_data.get("name", t_data.get("team", "Unknown"))).strip()
                team_results.append(self._eval_team_games(
                    t_name, t_data.get("games", []), sport, base_label, base_rating, as_of))
            sort_key = "total_dad" if probit else "dad_per_game"
            team_results.sort(key=lambda r: r[sort_key], reverse=True)
            outcomes = []
            for rank, tr in enumerate(team_results, 1):
                if probit:
                    outcomes.append(Outcome(
                        label=f"#{rank} {tr['team']} DAD", estimate=round(tr["total_dad"], 3),
                        fmt="number", group="DAD Leaderboard",
                        note=f"{tr['total_dad']:+.2f}σ total ({self._record(tr)}, "
                             f"WAD {tr['total_wad']:+.2f})"))
                else:
                    outcomes.append(Outcome(
                        label=f"#{rank} {tr['team']} DAD/game", estimate=round(tr["dad_per_game"], 3),
                        fmt="number", group="DAD Leaderboard",
                        note=f"{tr['strength_vs_default']:+.1f} {unit}/game vs default, "
                             f"{self._record(tr)}, WAD {tr['total_wad']:+.2f}"))
            top = team_results[0]
            steps = [
                f"Multi-team run for {len(team_results)} teams in sport '{sport}'.",
                f"Default baseline: {base_label} (rating = {base_rating:+.2f}).",
                f"Per game: spread = {p.expr('expected_spread')}. {dad_rule}",
                strength_rule,
                wad_rule + ".",
                f"Ranked by {'total DAD' if probit else 'DAD per game (strength)'}; "
                f"#1 {top['team']} = {top[sort_key]:+.3f}σ.",
            ]
            return self.prediction(
                inputs={"Sport": sport.title(), "Baseline": base_label,
                        "Baseline Rating": f"{base_rating:+.2f}",
                        "Teams Count": str(len(team_results))},
                outcomes=outcomes, steps=steps, extras={"leaderboard": team_results})

        team_name = str(inputs.get("team", "Team")).strip()
        if "games" in inputs and isinstance(inputs["games"], list):
            games = inputs["games"]
        elif "opponent" in inputs:
            games = [{k: inputs[k] for k in GAME_KEYS if k in inputs}]
        else:
            games = []
        res = self._eval_team_games(team_name, games, sport, base_label, base_rating, as_of)
        record_str = self._record(res)
        sv, wp = res["strength_vs_default"], res["win_prob_vs_default"]

        strength_outcomes = [
            Outcome(label="Strength vs default", estimate=round(sv, 2), fmt="number",
                    group="Strength (predictive)",
                    note=f"{unit} per game better than {base_label}, adjusted for "
                         f"opponents and venue, shrunk toward average"),
            Outcome(label="Win chance vs default", probability=wp, fmt="pct",
                    group="Strength (predictive)",
                    note=f"vs {base_label} on a neutral field"
                         + (" (draw = ½)" if sport == "soccer" else "")),
            Outcome(label="Strength rating", estimate=round(res["strength_rating"], 2),
                    fmt="number", group="Strength (predictive)",
                    note=f"{unit}/game vs an average team (opponent-rating scale)"),
        ]
        resume_outcomes = [
            Outcome(label=f"{team_name} Total DAD", estimate=round(res["total_dad"], 3),
                    fmt="number", group="Résumé",
                    note=(f"{res['total_dad']:+.2f}σ summed vs {base_label}"
                          + ("" if probit else f" ({res['dad_per_game_raw']:+.2f}σ/game, "
                                               "unshrunk)"))),
            Outcome(label=f"{team_name} Total WAD", estimate=round(res["total_wad"], 3),
                    fmt="number", group="Résumé",
                    note=f"{res['total_wad']:+.2f} wins above what {base_label} would win"
                    if p.wad_mode == "result" else
                    f"{res['total_wad']:+.2f} win-strength above {base_label} (v0.6.0)"),
        ]
        if res["has_xg"]:
            resume_outcomes += [
                Outcome(label=f"{team_name} Total xDAD", estimate=round(res["total_xdad"], 3),
                        fmt="number", group="Résumé",
                        note=f"{res['total_xdad']:+.2f}σ vs {base_label} from xG margins"),
                Outcome(label="Finishing & Goalkeeping Luck", estimate=round(res["luck_dad"], 3),
                        fmt="number", group="Résumé",
                        note=f"{res['luck_dad']:+.2f}σ (DAD - xDAD)"),
            ]
        resume_outcomes.append(Outcome(label="Record (Wins)", estimate=res["wins"], fmt="int",
                                       group="Résumé", note=f"{record_str} overall record"))
        bg, wg = res["best_game"], res["worst_game"]
        key_outcomes = [
            Outcome(label="Best Performance DAD", estimate=round(bg["dad"], 3), fmt="number",
                    group="Key Matchups",
                    note=f"{bg['loc_label']} {bg['opponent']} (margin {bg['margin']:+g}, "
                         f"{bg['dad']:+.2f}σ)"),
            Outcome(label="Worst Performance DAD", estimate=round(wg["dad"], 3), fmt="number",
                    group="Key Matchups",
                    note=f"{wg['loc_label']} {wg['opponent']} (margin {wg['margin']:+g}, "
                         f"{wg['dad']:+.2f}σ)"),
        ]
        if probit:
            outcomes = resume_outcomes[:2] + [Outcome(
                label="DAD per Game", estimate=round(res["dad_per_game"], 3), fmt="number",
                group="Résumé", note=f"Average across {res['games_count']} games (v0.6.0)")] \
                + resume_outcomes[2:] + strength_outcomes + key_outcomes
        else:
            primary = Outcome(
                label=f"{team_name} DAD per game", estimate=round(res["dad_per_game"], 3),
                fmt="number", group="Strength (predictive)",
                note=f"{res['dad_per_game']:+.2f}σ = {sv:+.1f} {unit}/game vs {base_label}; "
                     f"beats it {wp:.0%} on a neutral field")
            outcomes = [primary] + strength_outcomes + resume_outcomes + key_outcomes

        steps = [
            f"Sport: {sport.title()}; default baseline: {base_label} "
            f"(rating {base_rating:+.2f} {unit}/game vs an average team).",
            f"Per game: default team's expected spread = {p.expr('expected_spread')}. "
            + dad_rule,
            strength_rule,
            wad_rule + ".",
        ]
        for gr in res["game_records"][:12]:
            w_info = f" [{gr['weight_label']}]" if gr["weight"] != 1.0 else ""
            xg_info = f" xDAD {gr['xdad']:+.2f}σ;" if "xdad" in gr else ""
            steps.append(
                f"G{gr['game_idx']} {gr['loc_label']} {gr['opponent']} "
                f"(rating {gr['opp_rating']:+.2f}): margin {gr['margin']:+g}, default "
                f"spread {gr['exp_spread']:+.2f} -> DAD {gr['dad']:+.3f}σ{w_info};{xg_info} "
                f"adjusted {gr['adjusted']:+.2f}; P(default wins) "
                f"{gr['p_default_result']:.3f} -> WAD {gr['wad']:+.3f}.")
        if len(res["game_records"]) > 12:
            steps.append(f"... and {len(res['game_records']) - 12} more games.")
        steps.append(
            f"Strength rating = {res['strength_rating']:+.2f} {unit}/game (raw adjusted "
            f"mean {res['adjusted_margin_raw']:+.2f} over {res['games_count']} games, shrunk "
            f"with {res['prior_games']:g} average-team games) -> {sv:+.2f} vs default = "
            f"{res['strength_dad']:+.3f}σ per game; win chance vs default {wp:.1%}.")
        steps.append(
            f"Season Total DAD = Σ game DAD = {res['total_dad']:+.3f}σ; Total WAD = "
            f"{res['total_wad']:+.3f} wins over {res['games_count']} games.")
        if res["has_xg"]:
            steps.append(f"xDAD (xG margins) = {res['total_xdad']:+.3f}σ; luck (DAD - xDAD) = "
                         f"{res['luck_dad']:+.3f}σ.")
        return self.prediction(
            inputs={"Team": team_name, "Sport": sport.title(), "Baseline": base_label,
                    "Baseline Rating": f"{base_rating:+.2f}", "Games": str(res["games_count"]),
                    "Record": record_str},
            outcomes=outcomes, steps=steps, extras=res)

    # ── backtest: first half of a season -> second half (data/backtest.csv) ──

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], float]:
        """Row = one team-season half (see MODEL.md). Actual = second-half
        schedule-adjusted margin per game, expressed like DAD per game: σ above the
        row's baseline."""
        games = []
        for item in row["games"].split(";"):
            rating, margin, loc, day = item.split(":")
            games.append({"opponent_rating": float(rating), "margin": float(margin),
                          "location": {"h": "home", "a": "away", "n": "neutral"}[loc],
                          "date": f"{day[:4]}-{day[4:6]}-{day[6:]}"})
        sport = canonical_sport(row["sport"])
        inputs = {"team": row["team"], "sport": sport, "baseline": row.get("baseline") or "average",
                  "as_of": row["split_date"], "games": games}
        _, base_rating = self._resolve_baseline(inputs["baseline"], sport)
        actual = (float(row["actual_adj_margin"]) - base_rating) / self._margin_sd(sport)
        return inputs, actual

    def backtest_group(self, row: dict[str, str]) -> str | None:
        return row["league"]

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """Errors of DAD per game (σ) plus, in points/goals/runs, of the strength rating
        and two naive predictors (unshrunk adjusted margin, raw margin per game)."""
        ex = prediction.extras
        sd = ex["sigma"]
        target_pts = actual * sd + ex["baseline_rating"]
        err = ex["dad_per_game"] - actual
        return {
            "abs_error": abs(err),
            "bias": err,
            "abs_error_pts_strength": abs(ex["strength_rating"] - target_pts),
            "abs_error_pts_adjusted_unshrunk": abs(ex["adjusted_margin_raw"] - target_pts),
            "abs_error_pts_raw_margin": abs(ex["margin_per_game"] - target_pts),
        }


def _parse_date(value: Any, where: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValueError(f"{where}: date must be YYYY-MM-DD, got {value!r}") from None

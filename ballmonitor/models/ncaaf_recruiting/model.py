"""College recruiting team strength model (NCAAF, MBB, WBB)."""

from __future__ import annotations

import csv
import difflib
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction

# Ensure model subpackage can import src
MODEL_DIR = Path(__file__).resolve().parent
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from src.data_loader import DataLoader
from src.elo_engine import EloEngine
from src.mbb_seed import seed_prior
from src.models import RankingMethod
from src.position_model import PositionalRankingEngine

SPORT_LABELS = {"ncaaf": "NCAAF Football", "mbb": "Men's Basketball", "wbb": "Women's Basketball"}


def available_years(data_dir: Path, sport: str) -> list[int]:
    pattern = "football*done.csv" if sport == "ncaaf" else f"recruits_{sport}_*.csv"
    years = []
    for f in (data_dir / "recruits").glob(pattern):
        digits = f.stem.replace("football", "").replace("done", "").rsplit("_", 1)[-1]
        if digits.isdigit():
            years.append(int(digits))
    return sorted(years)


def class_status(data_dir: Path, sport: str, year: int) -> dict[str, str]:
    """Row of data/recruits/manifest.csv (written by fetch.py) for this file, if any."""
    path = data_dir / "recruits" / "manifest.csv"
    if path.exists():
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                if row["sport"] == sport and row["year"] == str(year):
                    return row
    return {}


class NcaafRecruitingModel(BaseModel):
    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        """data/backtest.csv (research.py): one FBS program-class per row; actual is the
        program's mean SRS over the class's four seasons (season year .. year+3)."""
        inputs = {"sport": "ncaaf", "year": int(row["year"]), "team": row["team"]}
        return inputs, float(row["future_srs"])

    def backtest_group(self, row: dict[str, str]) -> str | None:
        return row.get("year")

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """Scores the projected 4-season SRS (not the class score, which has no units)."""
        proj = prediction.extras.get("projection")
        if not proj:
            raise ValueError("no projection for this prediction (football, plackett_luce only)")
        err = proj["estimate"] - float(actual)
        lo, hi = proj["interval"]
        return {"abs_error": abs(err), "bias": err, "in_interval": float(lo <= actual <= hi)}

    def rank_class(self, sport: str, year: int, method: RankingMethod = RankingMethod.PLACKETT_LUCE) -> dict[str, Any]:
        """Rank every program for one sport-year (used by predict() and the public page).

        Returns the engine result (all teams and scored recruits) plus the settings used."""
        p = self.params
        is_bball = sport in ("mbb", "wbb")
        decay = float(p.rotation_decay) if is_bball else float(p.rank_decay)
        q_power = float(p.bball_quality_power) if is_bball else float(p.quality_power)
        l2_reg = float(p.bball_l2_reg) if is_bball else float(p.l2_reg)
        c_weight = float(p.cornerstone_weight) if is_bball else 0.0

        data_dir = MODEL_DIR / "data"
        loader = DataLoader(data_dir)
        try:
            recruits = loader.load_recruits(year, geolocate=False, sport=sport)
        except FileNotFoundError:
            raise ValueError(
                f"no {SPORT_LABELS[sport]} recruit data for {year}; available years: "
                f"{', '.join(str(y) for y in available_years(data_dir, sport)) or 'none'}"
            ) from None

        # The method needs competing offers; a file without them (e.g. the ESPN
        # WBB 2024 scrape, commits only) cannot produce meaningful scores.
        committed = [r for r in recruits if r.committed_team]
        coverage = (
            sum(1 for r in committed if any(t != r.committed_team for t in r.offers)) / len(committed)
            if committed else 0.0
        )
        if coverage < float(p.min_offer_coverage):
            raise ValueError(
                f"{SPORT_LABELS[sport]} {year} data has competing offers for only {coverage:.0%} of "
                f"committed recruits (min_offer_coverage = {float(p.min_offer_coverage):.0%}); "
                "offer-based rankings are not meaningful for this file"
            )

        # Optionally fit program prestige on earlier classes' offer battles too (they are
        # known when this class signs); only this class is scored.
        history: list = []
        prestige_years = int(p.prestige_years) if sport == "ncaaf" else 1
        for back in range(1, prestige_years):
            try:
                history.extend(loader.load_recruits(year - back, geolocate=False, sport=sport))
            except FileNotFoundError:
                break
        fit_recruits = recruits + history if history else None
        status = class_status(data_dir, sport, year)

        def points(rating: float, rank: int) -> float:
            return float(p.formula("recruit_points", rating=rating, rank=rank, decay=decay))

        seed_beta = float(p.bball_seed_beta) if sport == "mbb" else 0.0
        prior = seed_prior(data_dir, year, {t for r in recruits for t in r.all_teams}, seed_beta)
        engine = EloEngine(
            method=method,
            prior_gamma=prior,
            commit_weight=float(p.bball_commit_weight) if is_bball else 0.0,
            aggregate=str(p.bball_aggregate) if is_bball else "sum",
            l2_reg=l2_reg,
            quality_power=q_power,
            rank_decay=decay,
            volume_discount=float(p.volume_discount),
            cornerstone_weight=c_weight,
            base_elo=float(p.base_elo),
            points_fn=points,
        )
        result = engine.run(year, recruits, fit_recruits=fit_recruits)
        return {"recruits": recruits, "coverage": coverage, "history": history,
                "prestige_years": prestige_years, "status": status, "result": result,
                "decay": decay, "q_power": q_power, "l2_reg": l2_reg, "c_weight": c_weight}

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        sport = str(inputs.get("sport", "ncaaf")).strip().lower()
        if sport not in SPORT_LABELS:
            raise ValueError(f"unknown sport {sport!r}; use one of {', '.join(SPORT_LABELS)}")
        try:
            year = int(inputs.get("year", 2024))
        except (TypeError, ValueError):
            raise ValueError(f"year must be an integer class year, got {inputs.get('year')!r}") from None
        team_input = str(inputs.get("team", "Georgia")).strip()
        method_str = str(inputs.get("method", "plackett_luce")).strip().lower()
        methods = {m.value: m for m in RankingMethod}
        if method_str not in methods:
            raise ValueError(f"unknown method {method_str!r}; use one of {', '.join(methods)}")
        method = methods[method_str]

        run = self.rank_class(sport, year, method)
        recruits, coverage, history = run["recruits"], run["coverage"], run["history"]
        prestige_years, status, result = run["prestige_years"], run["status"], run["result"]
        decay, q_power, l2_reg, c_weight = run["decay"], run["q_power"], run["l2_reg"], run["c_weight"]
        is_bball = sport in ("mbb", "wbb")
        if not result.teams:
            raise ValueError(f"no rankable programs in {SPORT_LABELS[sport]} {year} data")

        key = team_input.lower()
        target = next((t for t in result.teams if t.name.lower() == key), None)
        if target is None:
            names = [t.name for t in result.teams]
            close = difflib.get_close_matches(team_input, names, n=3, cutoff=0.6)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise ValueError(
                f"team {team_input!r} has no committed recruits in {SPORT_LABELS[sport]} {year} data.{hint}"
            )

        t_name = target.name
        sport_label = SPORT_LABELS[sport]

        # Gather top committed recruits for the selected team
        team_commits = [
            r for r in result.recruits if r.committed_team.lower() == t_name.lower()
        ]
        team_commits.sort(key=lambda r: r.score, reverse=True)

        outcomes = [
            Outcome(
                label=f"{t_name} Class Score",
                estimate=round(float(target.total_score), 1),
                fmt="number",
                group="Class Summary",
                note=f"National rank #{target.rank} of {len(result.teams)}",
            ),
            Outcome(
                label="Total Commits",
                estimate=float(target.commits_count),
                fmt="int",
                group="Class Summary",
                note="Commits so far" if status.get("status") == "in_progress" else "Signed recruits",
            ),
            Outcome(
                label="Program Offer Elo",
                estimate=round(float(target.elo), 0),
                fmt="number",
                group="Class Summary",
                note="Offer-win prestige",
            ),
            Outcome(
                label="Average Recruit Caliber",
                estimate=round(float(target.avg_recruit_score), 2),
                fmt="number",
                group="Class Summary",
                note="Mean recruit score",
            ),
        ]

        # Football: translate the national class rank into an expected team strength
        # (mean SRS over the class's four seasons), fitted in research.py.
        projection = None
        if sport == "ncaaf" and method is RankingMethod.PLACKETT_LUCE:
            est = float(p.formula("projected_srs", rank=target.rank))
            half = NormalDist().inv_cdf(0.5 + float(p.projection_level) / 2) * float(p.projection_sd)
            projection = {"estimate": round(est, 1), "interval": [round(est - half, 1), round(est + half, 1)]}
            outcomes.insert(1, Outcome(
                label="Projected 4-season SRS",
                estimate=round(est, 1),
                interval=(round(est - half, 1), round(est + half, 1)),
                fmt="number",
                group="Class Summary",
                note="pts/game vs avg FBS, seasons Y..Y+3",
            ))

        # Positional unit breakdown for NCAAF (needs per-recruit Plackett-Luce scores)
        unit_breakdown = None
        if sport == "ncaaf" and method is RankingMethod.PLACKETT_LUCE:
            pos_engine = PositionalRankingEngine()
            pos_res = pos_engine.evaluate(result)
            pos_team = pos_res.by_name.get(t_name.lower())
            if pos_team:
                unit_breakdown = {
                    "offense_score": round(pos_team.offense_score, 1),
                    "defense_score": round(pos_team.defense_score, 1),
                    "run_offense_score": round(pos_team.run_offense_score, 1),
                    "pass_offense_score": round(pos_team.pass_offense_score, 1),
                    "run_defense_score": round(pos_team.run_defense_score, 1),
                    "pass_defense_score": round(pos_team.pass_defense_score, 1),
                }
                outcomes.append(
                    Outcome(
                        label="Offense Class Score",
                        estimate=round(float(pos_team.offense_score), 1),
                        fmt="number",
                        group="Positional breakdown (undiscounted sums)",
                        note=f"pass {pos_team.pass_offense_score:.1f}, run {pos_team.run_offense_score:.1f}",
                    )
                )
                outcomes.append(
                    Outcome(
                        label="Defense Class Score",
                        estimate=round(float(pos_team.defense_score), 1),
                        fmt="number",
                        group="Positional breakdown (undiscounted sums)",
                        note=f"pass {pos_team.pass_defense_score:.1f}, run {pos_team.run_defense_score:.1f}",
                    )
                )

        # Top 10 national class rankings
        for t in result.teams[:10]:
            outcomes.append(
                Outcome(
                    label=f"#{t.rank} {t.name}",
                    estimate=round(float(t.total_score), 1),
                    fmt="number",
                    group="National Class Standings",
                    note=f"Elo {t.elo:.0f}, {t.commits_count} commits",
                )
            )

        in_progress = status.get("status") == "in_progress"
        if method is RankingMethod.PLACKETT_LUCE:
            steps = [
                f"Loaded {len(recruits)} committed {sport_label} recruits for {year} "
                f"({coverage:.0%} with competing offers)"
                + (f"; class still in progress (fetched {status.get('fetched') or '?'})" if in_progress else ""),
                f"Fitted Plackett-Luce prestige for {len(result.teams)} programs by MAP (L2 = {l2_reg:g}) on "
                + (f"{len(history)} recruits from {prestige_years - 1} earlier class(es) plus this class; "
                   if history else "this class's offers; ")
                + f"Elo = {p.base_elo:g} + 400/ln(10) * gamma",
                f"Recruit score = (sum of exp(gamma) over losing offers) ^ {q_power:g}",
                f"Class score = sum over commits of {p.expr('recruit_points')} (decay = {decay:g})"
                + (f", times (top-2 avg / median recruit) ^ {c_weight:g}" if c_weight > 0 else ""),
                f"{t_name}: #{target.rank} of {len(result.teams)}, {target.total_score:.1f} points "
                f"from {target.commits_count} commits",
            ]
            if projection:
                steps.append(
                    f"Projected SRS = {p.expr('projected_srs')} at rank {target.rank} = "
                    f"{projection['estimate']:+.1f}; {float(p.projection_level):.0%} range "
                    f"+/- {half:.1f} (projection_sd = {float(p.projection_sd):g})"
                )
        else:
            steps = [
                f"Loaded {len(recruits)} committed {sport_label} recruits for {year}",
                "Ran the legacy sequential Elo ranking (k-factor updates in offer-count order, "
                "benchmark-tier points); rank_decay, quality_power and recruit_points are not used",
                f"{t_name}: #{target.rank} of {len(result.teams)}, {target.total_score:.1f} points",
            ]

        extras = {
            "sport": sport,
            "sport_label": sport_label,
            "year": year,
            "team": t_name,
            "rank": target.rank,
            "score": round(float(target.total_score), 1),
            "elo": round(float(target.elo), 0),
            "commits": target.commits_count,
            "avg_score": round(float(target.avg_recruit_score), 2),
            "unit_breakdown": unit_breakdown,
            "projection": projection,
            "class_status": status.get("status", "complete"),
            "team_commits": [
                {
                    "rank": idx,
                    "name": r.name,
                    "position": r.position,
                    "stars": r.stars,
                    "hometown": r.hometown,
                    "offers_count": r.total_offers,
                    "score": round(float(r.score), 2),
                }
                for idx, r in enumerate(team_commits[:12], 1)
            ],
            "rankings": [
                {
                    "rank": t.rank,
                    "team": t.name,
                    "score": round(float(t.total_score), 1),
                    "elo": round(float(t.elo), 0),
                    "commits": t.commits_count,
                    "offers": t.offers_count,
                    "avg_score": round(float(t.avg_recruit_score), 2),
                }
                for t in result.teams[:25]
            ],
        }

        display_inputs = {
            "Sport": sport_label,
            "Year": str(year),
            "Team": t_name,
            "Method": method.value,
            "Rank decay": f"{decay:.2f}" + (" (rotation_decay)" if is_bball else " (rank_decay)"),
        }

        return self.prediction(
            inputs=display_inputs,
            outcomes=outcomes,
            steps=steps,
            interval_level=float(p.projection_level) if projection else None,
            extras=extras,
        )

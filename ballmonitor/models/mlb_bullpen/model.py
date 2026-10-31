"""MLB bullpen usage model: Monte Carlo simulation with situational managerial policy."""

from __future__ import annotations

import json
import math
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.mlb_bullpen.calibration import (
    appear_probability,
    direct_features,
    direct_logit,
    first_direct_score,
    first_features,
    first_probabilities,
)
from ballmonitor.models.mlb_bullpen.ledger import BullpenLedger
from ballmonitor.models.mlb_bullpen.runs import bullpen_runs, expected_outs, parse_history, reliever_rate
from ballmonitor.models.mlb_bullpen.simulator import GameSimulator, MonteCarloSimulator
from ballmonitor.models.mlb_bullpen.tendency import log_usage_ratio

TENDENCY_INPUTS = ("team_recent_relievers", "team_recent_games", "league_recent_relievers")


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    raise ValueError(f"{name} must be true or false, got {value!r}")


class MlbBullpenModel(BaseModel):
    """Predicts which relievers will enter an MLB game and their usage distribution."""

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        steps: list[str] = []

        # 1. Parse Starter and Game Context
        starter_name = str(inputs.get("starter_name", "Starting Pitcher"))
        starter_hand = str(inputs.get("starter_hand", "R")).upper()
        if starter_hand not in ("R", "L"):
            raise ValueError(f"starter_hand must be 'R' or 'L', got {inputs.get('starter_hand')!r}")
        raw_stamina = inputs.get("starter_stamina", p.starter_stamina_default)
        try:
            starter_stamina = int(round(float(raw_stamina)))
        except (TypeError, ValueError):
            raise ValueError(f"starter_stamina must be a pitch count, got {raw_stamina!r}") from None
        if starter_stamina <= 0:
            raise ValueError(f"starter_stamina must be positive, got {starter_stamina}")
        is_home = _as_bool(inputs.get("is_home", True), "is_home")
        off_day_tomorrow = _as_bool(inputs.get("off_day_tomorrow", False), "off_day_tomorrow")
        raw_lineup = inputs.get("lineup", ["R"] * 9)
        if isinstance(raw_lineup, str):
            raw_lineup = [x for x in raw_lineup.replace(",", " ").split() if x]
        lineup = [str(h).strip().upper() for h in raw_lineup]
        if not lineup or any(h not in ("R", "L", "S") for h in lineup):
            raise ValueError(f"lineup must be a non-empty list of 'R', 'L' or 'S', got {inputs.get('lineup')!r}")

        steps.append(
            f"Starter: {starter_name} ({starter_hand}HP), stamina threshold = {starter_stamina} pitches. "
            f"Home team: {is_home}. Off-day tomorrow: {off_day_tomorrow}. Opponent lineup: {len(lineup)} batters ({lineup.count('L')} LHB, {lineup.count('R')} RHB)."
        )

        # 2. Parse Bullpen and Evaluate Rest Ledger
        relievers_data = inputs.get("relievers", [])
        if not relievers_data:
            raise ValueError("inputs need at least one reliever in [[relievers]]")

        ledger = BullpenLedger.from_inputs(relievers_data, p)
        # run-prevention history (validated here; ledger.from_inputs already checked the list)
        ra_hist = {str(item.get("name", "")).strip(): parse_history(item, str(item.get("name", "")))
                   for item in relievers_data}
        n_inferred = sum(1 for r in ledger.relievers.values() if r.role_source != "given")
        steps.append(
            f"Bullpen: {len(ledger.relievers)} relievers; {n_inferred} roles inferred from usage "
            f"history (closer = most saves >= {p.closer_min_saves:g}, setup = next "
            f"{p.setup_count:g} by holds >= {p.setup_min_holds:g}, long = "
            f">= {p.long_min_outs_per_app:g} outs per outing)."
        )
        steps.append(
            f"Usage term = usage_weight ({p.usage_weight:g}) x ln(rate / {p.usage_prior_rate:g}), "
            f"rate = (apps + {p.usage_prior_games:g} x {p.usage_prior_rate:g}) / "
            f"(games + {p.usage_prior_games:g})."
        )

        for rel in ledger.relievers.values():
            status_desc = ledger.describe_status(rel, p, off_day_tomorrow=off_day_tomorrow)
            pitches_str = ", ".join(str(x) for x in rel.pitches_days) if rel.pitches_days else "0"
            usage = (
                f"{rel.apps}/{rel.games} g, usage {rel.usage_score(p):+.2f}" if rel.games
                else f"no history, usage {rel.usage_score(p):+.2f}"
            )
            steps.append(
                f"  • {rel.name} ({rel.hand}HP, {rel.role}; {rel.role_source}): {status_desc} "
                f"[pitches last 5 d: {pitches_str}; {usage}]."
            )

        # 3. Initialize Simulator and Run Monte Carlo
        n_sims = int(p.num_simulations)
        simulator = GameSimulator(
            starter_name=starter_name,
            starter_hand=starter_hand,
            starter_stamina=starter_stamina,
            ledger=ledger,
            lineup=lineup,
            params=p,
            is_home=is_home,
            off_day_tomorrow=off_day_tomorrow,
        )

        mc = MonteCarloSimulator(simulator)
        stats = mc.run(num_simulations=n_sims, seed=int(p.seed))

        steps.append(
            f"Fatigue penalty per reliever = {p.expr('fatigue_penalty')}"
            + (f", x {p.off_day_tomorrow_discount} (off-day tomorrow)." if off_day_tomorrow else ".")
        )
        steps.append(
            f"Simulated {n_sims} full MLB games (seed {int(p.seed)}) with plate-appearance transitions, "
            f"starter hook thresholds, the 3-batter minimum rule, and a softmax choice "
            f"(temperature {p.temperature}) over score = role base + situation bonus "
            f"(sit_<situation>_<role>) + usage + platoon - fatigue."
        )

        # 4. Post-simulation adjustments: recalibration, team tendency, direct model
        eps = 0.5 / n_sims  # Monte Carlo frequencies of 0 or 1 are clipped
        log_ratio, shrunk = log_usage_ratio(
            inputs.get("team_recent_relievers"), inputs.get("team_recent_games"),
            inputs.get("league_recent_relievers"), p,
        )
        if shrunk is None:
            steps.append("Team tendency: no recent-usage inputs, log ratio = 0.")
        else:
            steps.append(
                f"Team tendency: {inputs.get('team_recent_relievers', 'n/a')} relievers/g over "
                f"{inputs.get('team_recent_games', 0)} g, league {inputs.get('league_recent_relievers', 'n/a')}"
                f"; shrunk ({p.tendency_prior_games:g} pseudo-g) = {shrunk:.2f}; log ratio vs "
                f"{p.bullpen_baseline_relievers:g} = {log_ratio:+.3f}."
            )
        use_direct = float(p.blend_weight_direct) != 0.0
        avail = {n: ledger.is_available(r, p) for n, r in ledger.relievers.items()}
        n_avail = sum(avail.values())
        p_sim = {n: stats[n].appearances / n_sims for n in ledger.relievers}
        p_app: dict[str, float] = {}
        p_dir: dict[str, float] = {}
        for name, rel in ledger.relievers.items():
            ld = 0.0
            if use_direct:
                ld = direct_logit(direct_features(
                    rel, available=avail[name], n_available=n_avail, starter_stamina=starter_stamina,
                    off_day_tomorrow=off_day_tomorrow, is_home=is_home, log_ratio=log_ratio, params=p,
                ), p)
                p_dir[name] = 1.0 / (1.0 + math.exp(-ld))
            p_app[name] = appear_probability(p_sim[name], rel.role, log_ratio, ld, p, eps) if rel.active else 0.0
        use_first_direct = float(p.first_weight_direct) != 0.0
        first_scores = {
            n: first_direct_score(first_features(
                r, available=avail[n], starter_stamina=starter_stamina, params=p), p)
            for n, r in ledger.relievers.items()
        } if use_first_direct else {}
        p_first = first_probabilities(
            {n: stats[n].first_in_count / n_sims for n in ledger.relievers}, first_scores,
            {n: r.active for n, r in ledger.relievers.items()}, p, eps,
        )
        steps.append(
            f"P(appear) = logistic({p.expr('appear_logit')}), logit_sim = logit(simulated "
            f"frequency); intercepts closer {p.calib_intercept_closer:+g}, setup "
            f"{p.calib_intercept_setup:+g}, middle {p.calib_intercept_middle:+g}, long "
            f"{p.calib_intercept_long:+g}."
        )
        if use_direct:
            steps.append(
                "logit_direct = direct logistic model (direct_<feature> weights x pre-game "
                "features: role, usage, rest, starter length, pool size, tendency)."
            )
        steps.append(
            f"P(first) = softmax of {p.first_weight_sim:g} x ln P_sim(first)"
            + (f" + {p.first_weight_direct:g} x direct score (first_direct_<feature> x "
               "first-out rate, role, rest, starter length)" if use_first_direct else "")
            + f"; arms off the active roster get 0. Expected relievers used: "
            f"{sum(p_app.values()):.2f} (simulated {sum(p_sim.values()):.2f})."
        )

        # 5. Bullpen runs: ratings x expected outs (runs.py)
        rates = {n: reliever_rate(*ra_hist[n], p) for n in ledger.relievers}
        x_outs = {n: expected_outs(p_app[n], stats[n].appearances, stats[n].total_outs, n_sims, p)
                  for n in ledger.relievers}
        br = bullpen_runs(x_outs, rates, {n: r.outs for n, r in ledger.relievers.items()}, p)
        X = br["expected_outs"]
        vs_avg = p.formula("bullpen_runs_vs", expected_runs=br["expected_runs"], expected_outs=X,
                           baseline_rate=float(p.runs_league_rate))
        vs_usual = p.formula("bullpen_runs_vs", expected_runs=br["expected_runs"], expected_outs=X,
                             baseline_rate=br["usual_rate"])
        league_runs = br["league_runs"]
        half = float(p.runs_interval_halfwidth) * math.sqrt(max(X, 0.0))
        vs_avg_iv = (max(vs_avg - half, -league_runs), vs_avg + half)
        exp_runs = league_runs + vs_avg
        exp_iv = (max(exp_runs - half, 0.0), exp_runs + half)
        n_hist = sum(1 for n in ledger.relievers if ra_hist[n][0] > 0)
        steps.append(
            f"Reliever rating (runs per out) = {p.expr('reliever_rating')} over earlier relief "
            f"outings (ra_runs on the mound / ra_outs); {n_hist} of {len(ledger.relievers)} arms have "
            f"history, the rest get {float(p.runs_prior_rate):.3f}. League reliever rate "
            f"{float(p.runs_league_rate):.4f} ({float(p.runs_league_rate) * 27:.2f} per 9)."
        )
        steps.append(
            "Expected outs per arm = "
            + ("P(appear) x simulated outs per simulated appearance"
               if str(p.runs_outs_source) != "simulated" else "simulated outs per game")
            + f"; bullpen total {X:.1f} outs ({X / 3:.1f} IP). Expected runs = sum(outs x rating) = "
            f"{br['expected_runs']:.2f}; a league-average pen: {league_runs:.2f}."
        )
        steps.append(
            f"Bullpen runs vs average = {p.expr('bullpen_runs_vs')} with baseline = league rate "
            f"= {vs_avg:+.2f}; vs usual (baseline = ratings weighted by recent relief outs, "
            f"{br['usual_rate']:.4f}) = {vs_usual:+.2f}. Interval: +- "
            f"{float(p.runs_interval_halfwidth):g} x sqrt(outs) = +-{half:.2f} runs "
            f"({float(p.runs_interval_level):.0%})."
        )

        # 6. Outcomes, sorted by appearance probability
        sorted_relievers = sorted(ledger.relievers.values(), key=lambda r: p_app[r.name], reverse=True)

        outcomes: list[Outcome] = []

        # Primary outcome: top predicted reliever to enter the game
        top_rel = sorted_relievers[0]
        top_stat = stats[top_rel.name]
        top_p = p_app[top_rel.name]
        top_xip = (top_stat.total_outs / n_sims) / 3.0

        outcomes.append(
            Outcome(
                label=f"Most likely to pitch: {top_rel.name}",
                probability=top_p,
                fmt="pct",
                note=f"{top_rel.role.title()} ({top_rel.hand}HP) | xIP: {top_xip:.1f} | 1st in pen: {p_first[top_rel.name]:.0%}",
            )
        )

        # Section 1: Appearance Probabilities for all relievers
        for rel in sorted_relievers:
            st = stats[rel.name]
            x_ip = (st.total_outs / n_sims) / 3.0
            extra = "" if rel.active else " | not active"
            direct = f", direct {p_dir[rel.name]:.0%}" if rel.name in p_dir else ""
            outcomes.append(
                Outcome(
                    label=f"{rel.name} ({rel.hand}HP)",
                    probability=p_app[rel.name],
                    fmt="pct",
                    group="Appearance Probability",
                    note=(f"role: {rel.role} | sim {p_sim[rel.name]:.0%}{direct} | xIP {x_ip:.1f} "
                          f"| first in: {p_first[rel.name]:.0%} | RA9 {rates[rel.name] * 27:.2f}{extra}"),
                )
            )

        # Section 2: Save Opportunities (for pitchers recording saves)
        for rel in sorted_relievers:
            st = stats[rel.name]
            p_save = st.saves / n_sims
            if p_save >= 0.01 or rel.role == "closer":
                outcomes.append(
                    Outcome(
                        label=f"{rel.name} Save Chance",
                        probability=p_save,
                        fmt="pct",
                        group="Save Probability",
                        note=f"role: {rel.role}",
                    )
                )

        # Section 3: Bullpen runs (run prevention of the expected usage)
        # The interval goes in the note (and extras), not Outcome.interval: an interval column
        # would push the shared table past 78 columns for long reliever names.
        lvl = f"{float(p.runs_interval_level):.0%}"
        outcomes.append(Outcome(
            label="Bullpen runs vs average", estimate=round(vs_avg, 2), fmt="number", group="Bullpen Runs",
            note=(f"{lvl}: {vs_avg_iv[0]:+.1f} to {vs_avg_iv[1]:+.1f} | + = more runs than a "
                  "league-average pen in the same outs"),
        ))
        outcomes.append(Outcome(
            label="Bullpen runs vs usual", estimate=round(vs_usual, 2), fmt="number", group="Bullpen Runs",
            note="availability: today's likely arms vs this pen's usual mix",
        ))
        outcomes.append(Outcome(
            label="Expected bullpen runs", estimate=round(exp_runs, 2), fmt="number", group="Bullpen Runs",
            note=f"{lvl}: {exp_iv[0]:.1f} to {exp_iv[1]:.1f} | xIP {X / 3:.1f} | league-average pen {league_runs:.2f}",
        ))

        shown_inputs = {
            "starter": f"{starter_name} ({starter_hand}HP, limit {starter_stamina} pitches)",
            "bullpen size": f"{len(ledger.relievers)} pitchers",
            "simulations": str(n_sims),
        }

        extras = {
            "n_simulations": n_sims,
            "p_appear": p_app,
            "p_first": p_first,
            "p_sim_appear": p_sim,
            "p_direct": p_dir,
            "log_ratio": log_ratio,
            "ratings": rates,
            "expected_outs": x_outs,
            "bullpen_runs": {
                "expected_outs": X, "expected_runs_raw": br["expected_runs"], "league_runs": league_runs,
                "usual_rate": br["usual_rate"], "raw_vs_average": br["vs_average"],
                "raw_vs_usual": br["vs_usual"], "vs_average": vs_avg, "vs_usual": vs_usual,
                "expected_runs": exp_runs, "interval": list(exp_iv), "vs_average_interval": list(vs_avg_iv),
                "interval_level": float(p.runs_interval_level),
            },
            "stats": {
                name: {
                    "appearances": st.appearances,
                    "first_in": st.first_in_count,
                    "saves": st.saves,
                    "total_outs": st.total_outs,
                    "total_pitches": st.total_pitches,
                }
                for name, st in stats.items()
            }
        }

        return self.prediction(
            inputs=shown_inputs,
            outcomes=outcomes,
            steps=steps,
            extras=extras,
        )

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        """Convert a row from data/backtest.csv into (inputs, actual)."""
        inputs = {
            "starter_name": row["starter_name"],
            "starter_hand": row.get("starter_hand") or "R",
            "is_home": row.get("is_home", "1") in ("1", "true", "True"),
            "off_day_tomorrow": row.get("off_day_tomorrow", "0") in ("1", "true", "True"),
            "lineup": [x.strip() for x in row["lineup"].split(",") if x.strip()],
            "relievers": json.loads(row["relievers_json"]),
        }
        # Pre-game stamina estimate (mean pitches in the starter's last 5 earlier starts).
        # Blank -> starter_stamina_default. Never the game's actual pitch count.
        if (row.get("starter_stamina") or "").strip():
            inputs["starter_stamina"] = int(float(row["starter_stamina"]))
        # Pre-game team / league bullpen usage (earlier dates only; blank = unknown).
        for key in TENDENCY_INPUTS:
            if (row.get(key) or "").strip():
                inputs[key] = float(row[key])
        actual = {
            "first_reliever": row["first_reliever"],
            "used": [x.strip() for x in row["actual_relievers_used"].split(";") if x.strip()],
        }
        if (row.get("bullpen_runs") or "").strip():
            actual["bullpen_runs"] = float(row["bullpen_runs"])  # outcome: runs while relievers pitched
        return inputs, actual

    def backtest_group(self, row: dict[str, str]) -> str | None:
        """Group backtest metrics by team."""
        return row.get("team", "All")

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """Score against what happened. Only relievers in the listed pool are scored;
        first-reliever metrics are NaN (skipped) when the first arm out of the pen was not
        in the pool (position player, rotation starter) or nobody relieved."""
        if not isinstance(actual, dict):
            return super().score(prediction, actual)

        stats = prediction.extras.get("stats", {})
        n_sims = int(prediction.extras["n_simulations"])
        p_app = prediction.extras.get("p_appear") or {k: v["appearances"] / n_sims for k, v in stats.items()}
        p_first = prediction.extras.get("p_first") or {k: v["first_in"] / n_sims for k, v in stats.items()}
        eps = 0.5 / n_sims  # probabilities of 0 or 1 are clipped for log loss
        actual_used = set(actual.get("used", []))
        first_reliever = actual.get("first_reliever", "")

        sq, ll, first_sq = [], [], []
        for name, pa in p_app.items():
            pc = min(max(pa, eps), 1 - eps)
            y = 1.0 if name in actual_used else 0.0
            sq.append((pa - y) ** 2)
            ll.append(-math.log(pc if y else 1 - pc))
            first_sq.append((p_first.get(name, 0.0) - (name == first_reliever)) ** 2)

        ranked = sorted(p_app, key=lambda k: p_app[k], reverse=True)
        used_in_pool = actual_used & set(p_app)
        scores = {
            "brier": sum(sq) / len(sq) if sq else math.nan,
            "log_loss_appear": sum(ll) / len(ll) if ll else math.nan,
            "top_pick_correct": float(bool(ranked) and ranked[0] in actual_used),
            "top_3_recall": (
                len(set(ranked[:3]) & used_in_pool) / min(3, len(used_in_pool))
                if used_in_pool else math.nan
            ),
            "brier_first": math.nan,
            "log_loss": math.nan,
        }
        br = prediction.extras.get("bullpen_runs")
        if br and "bullpen_runs" in actual:
            err = actual["bullpen_runs"] - br["expected_runs"]
            scores["bullpen_runs_sq_error"] = err * err
        if first_reliever in p_first:
            scores["brier_first"] = sum(first_sq)
            scores["log_loss"] = -math.log(max(p_first[first_reliever], eps))
        return scores

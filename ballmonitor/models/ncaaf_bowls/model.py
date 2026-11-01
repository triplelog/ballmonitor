"""NCAAF bowl projections and College Football Playoff simulation model."""

from __future__ import annotations

import json
from dataclasses import fields
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.ncaaf_bowls.config import DATA_DIR, SimConfig
from ballmonitor.models.ncaaf_bowls.engine import BowlEngine

_DEFAULTS = SimConfig()


class NcaafBowlsModel(BaseModel):
    def engine(self, simulations: int | None = None) -> BowlEngine:
        """The season engine with every tunable taken from config.toml (shared by predict()
        and site.py, which reads all teams from one run). `simulations` overrides the param."""
        p = self.params
        sims = int(simulations or p.simulations)
        seed = int(p.random_seed)

        # Ratings are fixed within a run, so the same (diff, home) pairs recur
        # thousands of times; cache the formula evaluation.
        wp_cache: dict[tuple[float, int], float] = {}

        def win_prob(rating_diff: float, home: int) -> float:
            k = (rating_diff, home)
            if k not in wp_cache:
                wp_cache[k] = float(p.formula("win_probability", rating_diff=rating_diff, home=home))
            return wp_cache[k]

        sample_wp = win_prob(7.0, 1)
        if not 0.0 <= sample_wp <= 1.0:
            raise ValueError(
                f"formula win_probability returned {sample_wp!r}; it must give a probability in [0, 1]"
            )

        # Every SimConfig tunable that has a same-named param in config.toml is
        # taken from there, so all weights stay editable via --set / variants.
        overrides = {
            f.name: type(getattr(_DEFAULTS, f.name))(p[f.name])
            for f in fields(SimConfig)
            if f.name in p.specs and f.name != "win_prob_fn"
        }
        cfg = SimConfig(**{**overrides, "simulations": sims, "random_seed": seed, "win_prob_fn": win_prob})
        return BowlEngine(config=cfg, ratings_source=str(p.ratings_source))

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        team_input = str(inputs.get("team", "Georgia")).strip()
        if not team_input:
            raise ValueError("input 'team' must be a non-empty FBS team name")
        sims = int(p.simulations)
        seed = int(p.random_seed)
        home_points = float(p.home_field_points)
        margin_sd = float(p.margin_sd)
        bowl_wins = int(p.bowl_eligible_wins)

        sample_wp = float(p.formula("win_probability", rating_diff=7.0, home=1))

        # Look up the requested team before running the simulation.
        engine = self.engine()
        meta = json.loads((DATA_DIR / "meta.json").read_text())
        key = team_input.lower()
        match = next(
            (t for t in engine.teams
             if key in (t.id.lower(), t.name.lower(), t.id.lower().replace("_", " "))),
            None,
        )
        if match is None:
            raise ValueError(
                f"unknown team {team_input!r}; use an FBS team name from data/teams.json "
                f"(e.g. 'Georgia', 'Ohio State', 'Boise State')"
            )

        res = engine.run(num_sims=sims)
        target_summary = res.team_summaries[match.id]
        t_name = target_summary.team_name

        outcomes = [
            Outcome(
                label=f"{t_name} makes the CFP",
                probability=target_summary.p_cfp,
                fmt="pct",
                group="Postseason Outlook",
                note="12-team field",
            ),
            Outcome(
                label="National Championship chance",
                probability=target_summary.national_champ_prob,
                fmt="pct",
                group="Postseason Outlook",
            ),
            Outcome(
                label="Conference Title chance",
                probability=target_summary.p_conf_champ,
                fmt="pct",
                group="Postseason Outlook",
                note=f"{target_summary.conf} champion",
            ),
            Outcome(
                label="First-round CFP bye",
                probability=target_summary.p_cfp_bye,
                fmt="pct",
                group="Postseason Outlook",
                note="Top-4 ranked team",
            ),
            Outcome(
                label="Bowl eligibility chance",
                probability=target_summary.p_eligible,
                fmt="pct",
                group="Postseason Outlook",
                note=f">= {bowl_wins} wins",
            ),
            Outcome(
                label="Wins a postseason game",
                probability=target_summary.p_win_any_bowl,
                fmt="pct",
                group="Postseason Outlook",
                note="Any bowl/CFP game",
            ),
            Outcome(
                label="Projected wins",
                estimate=round(target_summary.record_mean_wins, 1),
                fmt="number",
                group="Regular Season",
                note=f"rating {target_summary.rating:.1f}",
            ),
            Outcome(
                label="Projected losses",
                estimate=round(target_summary.record_mean_losses, 1),
                fmt="number",
                group="Regular Season",
            ),
        ]
        # (Win/loss totals include the conference title game when played.)

        # Top bowl destinations (a CFP team can appear in two CFP bowls, e.g. a
        # quarterfinal and a semifinal, so these are not mutually exclusive).
        for bid, bname, prob in target_summary.top_bowls[:4]:
            if prob > 0.01:
                outcomes.append(
                    Outcome(
                        label=bname,
                        probability=prob,
                        fmt="pct",
                        group="Bowl appearances (not exclusive)",
                        note=f"wins it {target_summary.bowls_detail[bid].p_win_conditional:.0%}"
                        if bid in target_summary.bowls_detail else "",
                    )
                )

        # Top CFP contenders
        top_cfp = sorted(res.team_summaries.values(), key=lambda s: s.p_cfp, reverse=True)[:12]
        for s in top_cfp[:8]:
            outcomes.append(
                Outcome(
                    label=f"{s.team_name} ({s.conf})",
                    probability=s.p_cfp,
                    fmt="pct",
                    group="CFP Field Projections",
                    note=f"title {s.national_champ_prob:.0%}, "
                    f"{s.record_mean_wins:.1f}-{s.record_mean_losses:.1f}",
                )
            )

        steps = [
            f"Loaded {len(engine.teams)} FBS teams, {meta['completed_games']} completed and "
            f"{len(engine.schedule)} remaining regular-season games, {len(engine.bowls)} bowls "
            f"(ESPN snapshot {meta['snapshot_utc']} UTC, {meta['season']} season)",
            f"Ratings: {p.ratings_source} (FCS opponents {engine.config.fcs_opponent_rating:+.1f})",
            f"Win probability: {p.expr('win_probability')} "
            f"(home={home_points:.1f}, sd={margin_sd:.1f}; P(win | +7, home) = {sample_wp:.1%})",
            f"Ran {sims} Monte Carlo seasons (seed={seed}): regular season, conference title games",
            "Applied 12-team CFP selection (P4 champions + best Group-of-6 champion + 7 at-large; "
            "straight seeding, top 4 ranked get byes)",
            f"Ran conference bowl tie-in selection across {len(res.bowl_summaries)} bowls and simulated every game",
            f"{t_name}: CFP {target_summary.p_cfp:.1%}, bowl-eligible {target_summary.p_eligible:.1%}, "
            f"mean record {target_summary.record_mean_wins:.1f}-{target_summary.record_mean_losses:.1f} "
            "(incl. conference title game)",
        ]

        extras = {
            "team": t_name,
            "conference": target_summary.conf,
            "rating": round(target_summary.rating, 1),
            "simulations": sims,
            "projected_record": f"{target_summary.record_mean_wins:.1f}-{target_summary.record_mean_losses:.1f}",
            "p_cfp": round(target_summary.p_cfp, 4),
            "p_conf_champ": round(target_summary.p_conf_champ, 4),
            "p_cfp_bye": round(target_summary.p_cfp_bye, 4),
            "national_champ_prob": round(target_summary.national_champ_prob, 4),
            "top_bowls": [
                {
                    "bowl": bname,
                    "probability": round(prob, 4),
                    "win_prob_cond": round(target_summary.bowls_detail[bid].p_win_conditional, 4)
                    if bid in target_summary.bowls_detail else 0.0,
                }
                for bid, bname, prob in target_summary.top_bowls[:6]
            ],
            "top_opponents": [
                {"opponent": opp, "probability": round(prob, 4), "win_rate": round(wr, 4)}
                for opp, prob, wr in target_summary.overall_opponents[:6]
            ],
            "cfp_teams": [
                {
                    "rank": idx,
                    "team": s.team_name,
                    "conf": s.conf,
                    "record": f"{s.record_mean_wins:.1f}-{s.record_mean_losses:.1f}",
                    "cfp_prob": round(s.p_cfp, 4),
                    "bye_prob": round(s.p_cfp_bye, 4),
                    "champ_prob": round(s.national_champ_prob, 4),
                }
                for idx, s in enumerate(top_cfp, 1)
            ],
        }

        display_inputs = {
            "Team": t_name,
            "Conference": target_summary.conf,
            "Season": f"{meta['season']} (ESPN data through {meta['last_completed_game']})",
            "Ratings": str(p.ratings_source),
        }

        return self.prediction(
            inputs=display_inputs,
            outcomes=outcomes,
            steps=steps,
            extras=extras,
        )

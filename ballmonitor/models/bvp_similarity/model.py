"""Batter vs. Pitcher Similarity Matchup Model.

Predicts plate appearance outcomes (xwOBA, K%, BB%) by synthesizing count-conditioned
pitch-by-pitch micro-simulation, peer archetype sample pooling, and Empirical Bayes
hierarchical shrinkage.
"""

from __future__ import annotations

import math
import unicodedata
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.stats import z_for_level
from ballmonitor.models.bvp_similarity import features as F


def _plain(name: Any) -> str:
    """Lower-case, accent-free name key ('José Berríos' -> 'jose berrios')."""
    text = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


@lru_cache(maxsize=4)
def _load_bvp_tables_cached(
    data_dir_str: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int], dict[str, int]]:
    data_dir = Path(data_dir_str)
    model_dir = data_dir.parent
    p_path = data_dir / "pitchers.parquet"
    b_path = data_dir / "batters.parquet"
    m_path = data_dir / "matchups.parquet"

    if not p_path.exists() or not b_path.exists() or not m_path.exists():
        from ballmonitor.models.bvp_similarity.build import build_datasets
        build_datasets(model_dir)

    pitchers = pd.read_parquet(p_path)
    batters = pd.read_parquet(b_path)
    matchups = pd.read_parquet(m_path)

    # tables are sorted busiest first, so a shared name resolves to the busiest player
    name_to_p_id: dict[str, int] = {}
    for pid, name in pitchers["name"].items():
        name_to_p_id.setdefault(_plain(name), int(pid))
        name_to_p_id[str(pid)] = int(pid)

    name_to_b_id: dict[str, int] = {}
    for bid, name in batters["name"].items():
        name_to_b_id.setdefault(_plain(name), int(bid))
        name_to_b_id[str(bid)] = int(bid)

    return pitchers, batters, matchups, name_to_p_id, name_to_b_id


class BvpSimilarityModel(BaseModel):
    """Predicts matchup outcomes between a batter and a pitcher using count micro-sim and peer pooling."""

    def __init__(self, config: Any, model_dir: Path):
        super().__init__(config, model_dir)
        self._pitchers: pd.DataFrame | None = None
        self._batters: pd.DataFrame | None = None
        self._matchups: pd.DataFrame | None = None
        self._name_to_p_id: dict[str, int] = {}
        self._name_to_b_id: dict[str, int] = {}
        # research.py points this at tables built from earlier seasons (walk-forward folds)
        self.data_dir = model_dir / "data"

    def _ensure_data(self) -> None:
        """Lazily load cached feature tables and matchup history."""
        if self._pitchers is not None:
            return
        (
            self._pitchers,
            self._batters,
            self._matchups,
            self._name_to_p_id,
            self._name_to_b_id,
        ) = _load_bvp_tables_cached(str(self.data_dir.resolve()))

    @staticmethod
    def _resolve(query: Any, lookup: dict[str, int], table: pd.DataFrame, what: str, minimum: str) -> int:
        if query is None or str(query).strip() == "":
            raise ValueError(f"input '{what}' is required (a name or MLB id)")
        key = _plain(query)
        if key in lookup:
            return lookup[key]
        close = get_close_matches(key, [k for k in lookup if not k.isdigit()], n=3, cutoff=0.6)
        names = [str(table.loc[lookup[k], "name"]) for k in close]
        hint = f" Did you mean {', '.join(names)}?" if names else ""
        raise ValueError(f"no {what} {str(query)!r} in the data ({minimum} in the training seasons).{hint}")

    def _resolve_pitcher_id(self, pitcher_input: Any) -> int:
        self._ensure_data()
        return self._resolve(pitcher_input, self._name_to_p_id, self._pitchers, "pitcher", "needs 150+ pitches")

    def _resolve_batter_id(self, batter_input: Any) -> int:
        self._ensure_data()
        return self._resolve(batter_input, self._name_to_b_id, self._batters, "batter", "needs 40+ PA")

    # count groups of the micro-simulation; each has its own measured league rates in config.toml
    COUNT_GROUPS = ("first", "even", "behind", "two")
    # the pitcher's own zone rate used in each count group
    GROUP_ZONE_COL = {"first": "f_zone_pct", "even": "zone_pct", "behind": "behind_zone_pct", "two": "ahead_zone_pct"}

    @staticmethod
    def count_group(balls: int, strikes: int) -> str:
        if balls == 0 and strikes == 0:
            return "first"
        if strikes == 2:
            return "two"
        if balls >= 2:
            return "behind"
        return "even"

    def microsim_factors(self, p_row: pd.Series, b_row: pd.Series) -> dict[str, float]:
        """Matchup multipliers on the league count-group rates (1.0 = league average)."""
        p = self.params
        lg = F.LEAGUE_DEFAULTS
        def log5_ratio(b_val: float, p_val: float, league: float) -> float:
            return float(p.formula("log5", pb=b_val, pp=p_val, pl=league)) / league
        return {
            "zone_swing_first": float(b_row.get("f_swing_pct", p.league_f_swing_pct)) / p.league_f_swing_pct,
            "zone_swing": float(b_row.get("z_swing_pct", p.league_z_swing_pct)) / p.league_z_swing_pct,
            "chase": log5_ratio(float(b_row.get("chase_pct", lg["chase_pct"])),
                                float(p_row.get("chase_pct", lg["chase_pct"])), p.league_chase_pct),
            "whiff": log5_ratio(float(b_row.get("whiff_pct", lg["whiff_pct"])),
                                float(p_row.get("whiff_pct", lg["whiff_pct"])), p.league_whiff_pct),
        }

    def solve_count_microsim(
        self, p_row: pd.Series, b_row: pd.Series
    ) -> tuple[float, float, float, float, float]:
        """Solve an absorbing Markov chain over the ball-strike count (MODEL.md step 5).

        Each pitch: in zone with the pitcher's zone rate for the count group; the batter swings at
        it with the league zone-swing rate for the group times his own aggressiveness, or chases
        with the league chase rate times the matchup chase factor; swings whiff (league rate x
        matchup whiff factor), foul, or put the ball in play; takes are called strikes with the
        league called-strike rate for in-zone / out-of-zone takes in that group, else balls.

        Returns: (P(K), P(BB), P(BIP), expected xwOBA, raw xwOBA per BIP before clipping)
        """
        p = self.params
        lg = F.LEAGUE_DEFAULTS
        f = self.microsim_factors(p_row, b_row)
        clip01 = lambda x: min(max(float(x), 0.0), 1.0)

        per_group: dict[str, dict[str, float]] = {}
        for g in self.COUNT_GROUPS:
            col = self.GROUP_ZONE_COL[g]
            z = clip01(p_row.get(col, lg.get(col, lg["zone_pct"])))
            zs = clip01(p[f"ms_{g}_zone_swing"] * f["zone_swing_first" if g == "first" else "zone_swing"])
            ch = clip01(p[f"ms_{g}_chase"] * f["chase"])
            wh = clip01(p[f"ms_{g}_whiff"] * f["whiff"])
            swing = z * zs + (1.0 - z) * ch
            contact = swing * (1.0 - wh)
            strike = z * (1.0 - zs) * p[f"ms_{g}_cs_zone"] + (1.0 - z) * (1.0 - ch) * p[f"ms_{g}_cs_out"]
            per_group[g] = {
                "whiff": swing * wh,
                "foul": contact * p.ms_foul_share,
                "bip": contact * (1.0 - p.ms_foul_share),
                "called": strike,
                "ball": 1.0 - swing - strike,
            }

        memo: dict[tuple[int, int], np.ndarray] = {}

        def solve(b: int, s: int) -> np.ndarray:
            if (b, s) in memo:
                return memo[(b, s)]
            if b >= 4:
                return np.array([0.0, 1.0, 0.0])  # walk
            if s >= 3:
                return np.array([1.0, 0.0, 0.0])  # strikeout
            t = per_group[self.count_group(b, s)]
            res = t["bip"] * np.array([0.0, 0.0, 1.0]) + t["ball"] * solve(b + 1, s)
            if s < 2:
                res = res + (t["whiff"] + t["called"] + t["foul"]) * solve(b, s + 1)
            else:  # two-strike fouls keep the count
                res = (res + (t["whiff"] + t["called"]) * np.array([1.0, 0.0, 0.0])) / (1.0 - t["foul"])
            memo[(b, s)] = res
            return res

        pk, pbb, pbip = (float(x) for x in solve(0, 0))

        # Expected wOBA on balls in play, from the batter's xwOBA with walks and strikeouts removed
        b_k = float(b_row.get("k_pct", p.league_k_pct))
        b_bb = float(b_row.get("bb_pct", p.league_bb_pct))
        denom = max(0.1, 1.0 - b_k - b_bb)  # floor guards batters with almost no balls in play
        xwoba_bip_raw = (float(b_row.get("xwoba", p.league_xwoba)) - p.woba_bb_weight * b_bb) / denom
        xwoba_bip = float(np.clip(xwoba_bip_raw, p.ms_bip_xwoba_min, p.ms_bip_xwoba_max))

        expected_xwoba = pbb * p.woba_bb_weight + pbip * xwoba_bip + p.ms_xwoba_offset
        return pk, pbb, pbip, float(expected_xwoba), float(xwoba_bip_raw)

    def talent(self, split: float, n_split: float, overall: float, n_all: float, league: float, n0: float) -> float:
        """Shrink a player's overall rate to the league with n0 PA, then his platoon split to that."""
        p = self.params
        overall_r = float(p.formula("regress", x=overall, n=n_all, prior=league, n0=n0))
        return float(p.formula("regress", x=split, n=n_split, prior=overall_r, n0=n0))

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        self._ensure_data()
        p = self.params
        steps: list[str] = []

        # 1. Resolve players
        p_id = self._resolve_pitcher_id(inputs.get("pitcher"))
        b_id = self._resolve_batter_id(inputs.get("batter"))

        p_row = self._pitchers.loc[p_id]
        b_row = self._batters.loc[b_id]

        p_name, p_hand = str(p_row["name"]), str(p_row["throws"])
        b_name, b_hand = str(b_row["name"]), str(b_row["bats"])

        steps.append(
            f"Pitcher: {p_name} ({p_hand}HP, {int(p_row['pitches']):,} pitches, {int(p_row['pa']):,} PA, "
            f"FB velo {p_row['velo_fb']:.1f} mph, K% {p_row['k_pct']:.1%}, BB% {p_row['bb_pct']:.1%}, "
            f"xwOBA allowed {p_row['xwoba']:.3f})"
        )
        steps.append(
            f"Batter: {b_name} ({b_hand}HB, {int(b_row['pa']):,} PA, HardHit% {b_row['hard_hit_pct']:.1%}, "
            f"K% {b_row['k_pct']:.1%}, BB% {b_row['bb_pct']:.1%}, xwOBA {b_row['xwoba']:.3f})"
        )

        # 2. Talent baselines: regressed platoon splits combined with Log5
        effective_b_stand = "R" if b_hand == "R" else ("L" if b_hand == "L" else ("R" if p_hand == "L" else "L"))
        is_platoon_advantage = (p_hand != effective_b_stand)
        b_n_all, p_n_all = float(b_row["pa"]), float(p_row["pa"])
        b_n_split = float(b_row[f"pa_vs_{p_hand}"])
        p_n_split = float(p_row[f"pa_vs_{effective_b_stand}"])

        league_xw = float(p.league_xwoba)
        league_k = float(p.league_k_pct)
        league_bb = float(p.league_bb_pct)

        b_xw = self.talent(float(b_row[f"xwoba_vs_{p_hand}"]), b_n_split, float(b_row["xwoba"]), b_n_all,
                           league_xw, p.regress_xwoba_pa)
        p_xw = self.talent(float(p_row[f"xwoba_vs_{effective_b_stand}"]), p_n_split, float(p_row["xwoba"]), p_n_all,
                           league_xw, p.regress_xwoba_pa)
        b_k = self.talent(float(b_row[f"k_pct_vs_{p_hand}"]), b_n_split, float(b_row["k_pct"]), b_n_all,
                          league_k, p.regress_k_pa)
        p_k = self.talent(float(p_row[f"k_pct_vs_{effective_b_stand}"]), p_n_split, float(p_row["k_pct"]), p_n_all,
                          league_k, p.regress_k_pa)
        # walks have no platoon split in the tables: the overall rate is regressed only
        b_bb = float(p.formula("regress", x=float(b_row["bb_pct"]), n=b_n_all, prior=league_bb, n0=p.regress_bb_pa))
        p_bb = float(p.formula("regress", x=float(p_row["bb_pct"]), n=p_n_all, prior=league_bb, n0=p.regress_bb_pa))

        base_xwoba = float(p.formula("log5", pb=b_xw, pp=p_xw, pl=league_xw))
        base_k = float(p.formula("log5", pb=b_k, pp=p_k, pl=league_k))
        base_bb = float(p.formula("log5", pb=b_bb, pp=p_bb, pl=league_bb))

        steps.append(
            f"Platoon context: {p_hand}HP vs {effective_b_stand}HB "
            f"({'platoon advantage' if is_platoon_advantage else 'same-hand matchup'}); "
            f"batter {b_n_split:.0f} PA vs {p_hand}HP, pitcher {p_n_split:.0f} PA vs {effective_b_stand}HB."
        )
        steps.append(
            f"Regressed rates [{p.expr('regress')}; overall to league, then split to overall; "
            f"n0 = {p.regress_xwoba_pa:g} / {p.regress_k_pa:g} / {p.regress_bb_pa:g} PA for xwOBA / K / BB]: "
            f"batter xwOBA {b_xw:.3f}, K% {b_k:.1%}, BB% {b_bb:.1%}; "
            f"pitcher xwOBA {p_xw:.3f}, K% {p_k:.1%}, BB% {p_bb:.1%}."
        )
        steps.append(
            f"Talent baselines (Log5 with league xwOBA {league_xw:.3f}, K% {league_k:.1%}, BB% {league_bb:.1%}): "
            f"xwOBA = {base_xwoba:.3f}, K% = {base_k:.1%}, BB% = {base_bb:.1%}."
        )

        # 3. Similarity peer matching
        k_p = int(inputs.get("k_pitchers", p.k_pitchers))
        k_b = int(inputs.get("k_batters", p.k_batters))
        if k_p < 1 or k_b < 1:
            raise ValueError("k_pitchers and k_batters must be at least 1")

        sim_pitchers = F.compute_pitcher_similarity(self._pitchers, p_id, top_k=k_p)
        sim_batters = F.compute_batter_similarity(self._batters, b_id, top_k=k_b)

        top_p_peers = ", ".join(
            f"{r['name']} ({r['similarity']:.2f}; FB {r['velo_fb']:.1f}, K% {r['k_pct']:.1%}, xwOBA {r['xwoba']:.3f})"
            for _, r in sim_pitchers.head(3).iterrows())
        top_b_peers = ", ".join(
            f"{r['name']} ({r['similarity']:.2f}; K% {r['k_pct']:.1%}, xwOBA {r['xwoba']:.3f})"
            for _, r in sim_batters.head(3).iterrows())
        steps.append(f"Top similar pitchers ({k_p} total): {top_p_peers}...")
        steps.append(f"Top similar batters ({k_b} total): {top_b_peers}...")

        # 4. Archetype sample pooling
        archetype_matchup = F.pool_archetype_matchups(self._matchups, sim_pitchers, sim_batters)
        pooled_pa = archetype_matchup["pooled_pa"]
        eff_pa = archetype_matchup["effective_pa"]
        arch_xwoba = archetype_matchup["pooled_xwoba"]
        arch_k = archetype_matchup["pooled_k_pct"]
        arch_bb = archetype_matchup["pooled_bb_pct"]

        steps.append(
            f"Archetype pool: {pooled_pa} historical PAs ({eff_pa:.1f} similarity-weighted) between the "
            f"peers: xwOBA = {arch_xwoba:.3f}, K% = {arch_k:.1%}, BB% = {arch_bb:.1%}."
        )

        # 5. Direct BvP history lookup
        direct_rows = self._matchups[
            (self._matchups["pitcher"] == p_id) & (self._matchups["batter"] == b_id)
        ]
        if not direct_rows.empty:
            direct_pa = int(direct_rows.iloc[0]["pa"])
            direct_xwoba = float(direct_rows.iloc[0]["xwoba"])
            direct_k = float(direct_rows.iloc[0]["k_pct"])
            direct_bb = float(direct_rows.iloc[0]["bb_pct"])
            steps.append(
                f"Direct BvP history: {direct_pa} PAs (xwOBA = {direct_xwoba:.3f}, K% = {direct_k:.1%}, "
                f"BB% = {direct_bb:.1%})."
            )
        else:
            direct_pa = 0
            direct_xwoba = base_xwoba
            direct_k = base_k
            direct_bb = base_bb
            steps.append("Direct BvP history: 0 PAs.")

        # 6. Hierarchical shrinkage weights for the archetype blend
        w_direct = float(p.formula("bvp_weight", n_direct=direct_pa))
        w_arch = float(p.formula("archetype_weight", w_direct=w_direct, eff_n=eff_pa))
        w_baseline = max(0.0, 1.0 - w_direct - w_arch)

        def blend(y_direct: float, y_arch: float, y_base: float) -> float:
            return float(p.formula("blend_estimate", w_direct=w_direct, y_direct=y_direct,
                                   w_arch=w_arch, y_arch=y_arch, y_baseline=y_base))

        arch_blend_xwoba = blend(direct_xwoba, arch_xwoba, base_xwoba)
        arch_blend_k = blend(direct_k, arch_k, base_k)
        arch_blend_bb = blend(direct_bb, arch_bb, base_bb)
        steps.append(
            f"Shrinkage blend [{p.expr('blend_estimate')}]: weights direct {w_direct:.2f}, "
            f"archetype {w_arch:.2f}, baseline {w_baseline:.2f} -> xwOBA {arch_blend_xwoba:.3f}, "
            f"K% {arch_blend_k:.1%}, BB% {arch_blend_bb:.1%}."
        )

        # 7. Count-conditioned micro-simulation
        ms_k, ms_bb, ms_bip, ms_xwoba, xwoba_bip_raw = self.solve_count_microsim(p_row, b_row)
        factors = self.microsim_factors(p_row, b_row)
        steps.append(
            f"Count micro-sim: league count-group rates x matchup factors (zone swing "
            f"{factors['zone_swing']:.2f}, 0-0 swing {factors['zone_swing_first']:.2f}, chase "
            f"{factors['chase']:.2f}, whiff {factors['whiff']:.2f}) -> P(K) = {ms_k:.1%}, "
            f"P(BB) = {ms_bb:.1%}, P(BIP) = {ms_bip:.1%}; xwOBA = P(BB) * {p.woba_bb_weight:g} + "
            f"P(BIP) * {min(max(xwoba_bip_raw, p.ms_bip_xwoba_min), p.ms_bip_xwoba_max):.3f} per BIP "
            f"(clip {p.ms_bip_xwoba_min:g}-{p.ms_bip_xwoba_max:g}) + {p.ms_xwoba_offset:g} = {ms_xwoba:.3f}."
        )

        # 8. Final blend of the shrinkage estimate and the micro-simulation
        ms_w = float(p.microsim_weight)
        ms_w_rates = float(p.microsim_weight_rates)
        final_xwoba = float(p.formula("final_microsim_blend", w_ms=ms_w, y_archetype_blend=arch_blend_xwoba,
                                      y_microsim=ms_xwoba))
        final_k = float(p.formula("final_microsim_blend", w_ms=ms_w_rates, y_archetype_blend=arch_blend_k,
                                  y_microsim=ms_k))
        final_bb = float(p.formula("final_microsim_blend", w_ms=ms_w_rates, y_archetype_blend=arch_blend_bb,
                                   y_microsim=ms_bb))
        steps.append(
            f"Final blend [{p.expr('final_microsim_blend')}]: micro-sim weight {ms_w:g} for xwOBA, "
            f"{ms_w_rates:g} for K% and BB%."
        )

        # Plausibility clamps
        final_xwoba = round(float(np.clip(final_xwoba, p.xwoba_min, p.xwoba_max)), 3)
        final_k = round(float(np.clip(final_k, p.k_pct_min, p.k_pct_max)), 3)
        final_bb = round(float(np.clip(final_bb, p.bb_pct_min, p.bb_pct_max)), 3)

        delta_vs_baseline = final_xwoba - base_xwoba
        steps.append(
            f"Final matchup prediction: xwOBA = {final_xwoba:.3f} "
            f"({'+' if delta_vs_baseline >= 0 else ''}{delta_vs_baseline:.3f} vs baseline), "
            f"K% = {final_k:.1%}, BB% = {final_bb:.1%}."
        )

        # 9. Range for the xwOBA observed over n_pa plate appearances
        level = float(p.interval_level)
        n_pa = int(inputs.get("pa", p.interval_pa))
        if n_pa < 1:
            raise ValueError("pa must be at least 1")
        half_w = float(p.formula("interval_half_width", z=z_for_level(level), n_pa=n_pa))
        interval = (round(max(0.0, final_xwoba - half_w), 3), round(final_xwoba + half_w, 3))
        steps.append(
            f"{level:.0%} range of the xwOBA observed over {n_pa} PA "
            f"[{p.expr('interval_half_width')}]: +/- {half_w:.3f} -> {interval[0]:.3f}-{interval[1]:.3f} "
            f"(floored at 0)."
        )

        outcomes = [
            Outcome(
                label="Expected xwOBA",
                estimate=final_xwoba,
                interval=interval,
                fmt="number",
                group="Matchup Projection",
                note=f"per PA; range: observed over {n_pa} PA",
            ),
            Outcome(
                label="Strikeout probability",
                probability=final_k,
                fmt="pct",
                group="Matchup Projection",
                note="per PA",
            ),
            Outcome(
                label="Walk probability",
                probability=final_bb,
                fmt="pct",
                group="Matchup Projection",
                note="per PA",
            ),
        ]

        similar_pitchers_list = []
        for idx, (_, r) in enumerate(sim_pitchers.head(6).iterrows(), 1):
            sim_val = round(float(r["similarity"]), 3)
            p_peer_name = str(r["name"])
            similar_pitchers_list.append({
                "rank": idx,
                "name": p_peer_name,
                "similarity": sim_val,
                "throws": str(r.get("throws", p_hand)),
                "velo_fb": round(float(r["velo_fb"]), 1),
                "k_pct": round(float(r["k_pct"]), 3),
                "xwoba": round(float(r["xwoba"]), 3),
            })
            outcomes.append(
                Outcome(
                    label=f"#{idx} {p_peer_name}",
                    estimate=sim_val,
                    fmt="number",
                    group="Similar pitchers (similarity 0-1)",
                )
            )

        similar_batters_list = []
        for idx, (_, r) in enumerate(sim_batters.head(6).iterrows(), 1):
            sim_val = round(float(r["similarity"]), 3)
            b_peer_name = str(r["name"])
            similar_batters_list.append({
                "rank": idx,
                "name": b_peer_name,
                "similarity": sim_val,
                "bats": str(r.get("bats", b_hand)),
                "hard_hit_pct": round(float(r["hard_hit_pct"]), 3),
                "k_pct": round(float(r["k_pct"]), 3),
                "xwoba": round(float(r["xwoba"]), 3),
            })
            outcomes.append(
                Outcome(
                    label=f"#{idx} {b_peer_name}",
                    estimate=sim_val,
                    fmt="number",
                    group="Similar batters (similarity 0-1)",
                )
            )

        return self.prediction(
            inputs={
                "pitcher": p_name,
                "batter": b_name,
                "pitcher_hand": p_hand,
                "batter_bats": b_hand,
                "pa": n_pa,
            },
            outcomes=outcomes,
            steps=steps,
            interval_level=level,
            extras={
                "base_xwoba": round(base_xwoba, 3),
                "base_k": round(base_k, 3),
                "base_bb": round(base_bb, 3),
                "arch_xwoba": round(arch_xwoba, 3),
                "arch_k": round(arch_k, 3),
                "arch_bb": round(arch_bb, 3),
                "ms_xwoba": round(ms_xwoba, 3),
                "ms_k": round(ms_k, 3),
                "ms_bb": round(ms_bb, 3),
                "ms_bip": round(ms_bip, 3),
                "direct_pa": direct_pa,
                "direct_xwoba": round(direct_xwoba, 3),
                "pooled_pa": pooled_pa,
                "eff_pa": round(eff_pa, 1),
                "w_direct": round(w_direct, 4),
                "w_arch": round(w_arch, 4),
                "w_baseline": round(w_baseline, 4),
                "w_microsim": round(ms_w, 4),
                "w_microsim_rates": round(ms_w_rates, 4),
                "interval_half_width": round(half_w, 4),
                "pitcher_profile": {
                    "name": p_name,
                    "throws": p_hand,
                    "velo_fb": round(float(p_row["velo_fb"]), 1),
                    "k_pct": round(float(p_row["k_pct"]), 3),
                    "bb_pct": round(float(p_row["bb_pct"]), 3),
                    "xwoba": round(float(p_row["xwoba"]), 3),
                    "f_zone_pct": round(float(p_row["f_zone_pct"]), 3),
                    "ahead_zone_pct": round(float(p_row["ahead_zone_pct"]), 3),
                },
                "batter_profile": {
                    "name": b_name,
                    "bats": b_hand,
                    "hard_hit_pct": round(float(b_row["hard_hit_pct"]), 3),
                    "k_pct": round(float(b_row["k_pct"]), 3),
                    "bb_pct": round(float(b_row["bb_pct"]), 3),
                    "xwoba": round(float(b_row["xwoba"]), 3),
                    "f_swing_pct": round(float(b_row["f_swing_pct"]), 3),
                    "chase_2s_pct": round(float(b_row["chase_2s_pct"]), 3),
                },
                "similar_pitchers": similar_pitchers_list,
                "similar_batters": similar_batters_list,
                # unrounded pieces for research.py (keys starting "_" are not serialised)
                "_components": {
                    "base_xwoba": base_xwoba, "base_k": base_k, "base_bb": base_bb,
                    "arch_xwoba": arch_xwoba, "arch_k": arch_k, "arch_bb": arch_bb, "eff_pa": eff_pa,
                    "direct_pa": direct_pa, "direct_xwoba": direct_xwoba, "direct_k": direct_k,
                    "direct_bb": direct_bb, "ms_k": ms_k, "ms_bb": ms_bb, "ms_bip": ms_bip,
                    "ms_xwoba": ms_xwoba, "xwoba_bip_raw": xwoba_bip_raw,
                    "final_xwoba": final_xwoba, "final_k": final_k, "final_bb": final_bb,
                },
            },
        )

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        """A later-season matchup: inputs are the two players (and its PA count, for the range);
        the actual is what happened over those PAs."""
        pa = int(float(row.get("pa", 1) or 1))
        inputs = {"pitcher": row["pitcher"], "batter": row["batter"], "pa": pa}
        actual = {
            "pa": pa,
            "xwoba": float(row["observed_xwoba"]),
            "k": int(float(row.get("k", 0) or 0)),
            "bb": int(float(row.get("bb", 0) or 0)),
        }
        return inputs, actual

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """xwOBA error and range coverage, plus per-PA log loss and Brier score of the
        strikeout / walk / other outcome of each PA (so K% and BB% are scored too)."""
        if not isinstance(actual, dict):  # a bare observed xwOBA
            return super().score(prediction, actual)
        pa, k, bb = actual["pa"], actual["k"], actual["bb"]
        primary = prediction.primary
        error = primary.estimate - actual["xwoba"]
        lo, hi = primary.interval
        pk = prediction.outcome("Strikeout probability").probability
        pbb = prediction.outcome("Walk probability").probability
        probs = (pk, pbb, max(1.0 - pk - pbb, 1e-6))
        counts = (k, bb, pa - k - bb)
        log_loss = -sum(c * math.log(max(q, 1e-12)) for c, q in zip(counts, probs)) / pa
        brier = sum(c * sum((q - (i == j)) ** 2 for i, q in enumerate(probs))
                    for j, c in enumerate(counts)) / pa
        return {
            "abs_error": abs(error),
            "bias": error,
            ("in_80" if abs((prediction.interval_level or 0) - 0.8) < 1e-9 else "in_interval"):
                float(lo <= actual["xwoba"] <= hi),
            "log_loss": log_loss,
            "brier": brier,
        }

"""Next pitch type for a given pitcher, count, batter and at-bat sequence. See MODEL.md."""

from __future__ import annotations

import csv
import json
import math
import unicodedata
from datetime import date, timedelta
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.next_pitch.pitches import (
    GBM_SPECS, INDEX, K, NAMES, RESULT_NAMES, VOCAB, ContextCounts, chain_specs, count_after,
    entropy_bits, load_history, parse_sequence,
)

FEATURE_CONTEXT = ["balls", "strikes", "count", "outs_when_up", "inning", "on_1b", "on_2b", "on_3b", "score_diff",
                   "n_thruorder_pitcher", "ab_idx", "game_pitch_n", "batters_faced", "pitcher_days_since_prev_game",
                   "stand_i", "throws_i"]
RES_CODES = ["B", "C", "S", "F", "X", "H"]
TREE_LEVELS = ("count", "stand", "prev_type", "prev_result", "prev2_type", "outs", "runners", "tto")
BATTER_FEATURES = ["bat_pa", "bat_woba", "bat_k", "bat_bb", "bat_whiff", "bat_chase", "bat_slg",
                   "bat_seen_fb", "bat_seen_br", "bat_seen_os"]


def _plain(name: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).lower().strip()


@lru_cache(maxsize=8)
def _table(path: Path) -> tuple[dict, ...]:
    if not path.exists():
        return ()
    with open(path, newline="") as fh:
        return tuple(csv.DictReader(fh))


def _find(rows: tuple[dict, ...], key: str, query, what: str) -> dict:
    q = str(query).strip()
    for r in rows:
        if r[key] == q:
            return r
    by_name = [r for r in rows if _plain(r["name"]) == _plain(q)]
    if by_name:
        return by_name[0]  # files are sorted busiest first
    names = [r["name"] for r in rows]
    close = get_close_matches(q, names, n=3, cutoff=0.6)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise ValueError(f"no {what} {q!r} in the data.{hint} Run `ballmonitor fetch next_pitch` for the latest data.")


@lru_cache(maxsize=2)
def _booster(path: Path):
    import lightgbm  # optional dependency, only for method = "gbm"

    return lightgbm.Booster(model_file=str(path))


@lru_cache(maxsize=64)
def _build_base_counts(
    history_path: Path,
    as_of: date,
    oldest: date,
    half_life_days: float,
    recency_expr: str,
    chain_tuple: tuple[str, ...],
    use_gbm: bool,
    gbm_hl: float,
) -> tuple[ContextCounts, ContextCounts | None, int, date, date]:
    from ballmonitor.core import formula
    history = load_history(history_path)
    past = [h for h in history if oldest <= h["date"] < as_of]
    if not past:
        return ContextCounts(chain_specs(list(chain_tuple))), None, 0, as_of, as_of

    tree_specs = chain_specs(list(chain_tuple))
    weights = {}
    for d in {h["date"] for h in past}:
        weights[d] = float(
            formula.evaluate(recency_expr, {"age_days": (as_of - d).days, "half_life_days": half_life_days})
        )
    counts = ContextCounts(tree_specs)
    gbm_counts = ContextCounts(GBM_SPECS) if use_gbm else None
    gbm_w = {}
    if gbm_counts:
        for d in weights:
            gbm_w[d] = 0.5 ** ((as_of - d).days / gbm_hl) if gbm_hl > 0 else 1.0
    for h in past:
        counts.add(h, h["type"], weights[h["date"]])
        if gbm_counts:
            gbm_counts.add(h, h["type"], gbm_w[h["date"]])
    return counts, gbm_counts, len(past), past[0]["date"], past[-1]["date"]


def _num(v, default=math.nan) -> float:
    if v is None or v == "":
        return default
    return float(v)


class NextPitchModel(BaseModel):
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        data = self.dir / "data"
        meta = json.loads((data / "meta.json").read_text()) if (data / "meta.json").exists() else {}
        steps: list[str] = []

        pitcher = _find(_table(data / "pitchers.csv"), "pitcher_id", inputs["pitcher"], "pitcher")
        throws = pitcher["throws"]
        history = load_history(data / "pitchers" / f"{pitcher['pitcher_id']}.csv.gz")
        as_of = date.fromisoformat(str(inputs["as_of"])) if inputs.get("as_of") else \
            date.fromisoformat(meta.get("last_date", str(history[-1]["date"]))) + timedelta(days=1)
        oldest = as_of - timedelta(days=p.max_history_days) if p.max_history_days > 0 else date.min
        past = [h for h in history if oldest <= h["date"] < as_of]
        if not past:
            window = f" within max_history_days = {p.max_history_days:g}" if p.max_history_days > 0 else ""
            raise ValueError(f"{pitcher['name']} has no pitches in the data before {as_of}{window}")

        # batter
        batter = None
        if inputs.get("batter"):
            batter = _find(_table(data / "batters.csv"), "batter_id", inputs["batter"], "batter")
        stand = str(inputs.get("stand") or (batter or {}).get("bats") or "R").upper()
        if stand == "S":  # switch hitter bats opposite the pitcher's hand
            stand = "L" if throws == "R" else "R"
        if stand not in ("L", "R"):
            raise ValueError("stand must be L or R (the batter's side)")

        # at-bat so far
        seq = parse_sequence(inputs.get("sequence"))
        if any(r in ("X", "H") for _, r in seq):
            raise ValueError("sequence contains a ball in play (X) or hit by pitch (H), which ends the at-bat; "
                             "list only this at-bat's pitches so far (earlier ones go in earlier_in_game)")
        implied = count_after(seq)
        balls = int(inputs.get("balls", implied[0]))
        strikes = int(inputs.get("strikes", implied[1]))
        if seq and (balls, strikes) != implied:
            raise ValueError(f"sequence implies a {implied[0]}-{implied[1]} count but balls/strikes say {balls}-{strikes}")
        if not (0 <= balls <= 3 and 0 <= strikes <= 2):
            raise ValueError("count must be 0-3 balls and 0-2 strikes")
        game_earlier = parse_sequence(inputs.get("earlier_in_game"))
        outs, tto = int(inputs.get("outs", 0)), int(inputs.get("tto", 1))
        if not 0 <= outs <= 2:
            raise ValueError("outs must be 0, 1 or 2")
        if tto < 1:
            raise ValueError("tto (time through the order) must be 1 or more")
        sit = {
            "balls": balls, "strikes": strikes, "stand": stand, "outs": outs,
            "runners": sum(c in str(inputs.get("bases", "")) for c in "123"), "tto": tto,
            "prev_type": seq[-1][0] if seq else None, "prev_result": seq[-1][1] if seq else None,
            "prev2_type": seq[-2][0] if len(seq) > 1 else None,
            "batter": (batter or {}).get("batter_id"), "game": "today",
            "game_prev_type": (seq or game_earlier or [(None, None)])[-1][0],
        }

        # recency-weighted history counts
        method = p.method
        gbm_meta = meta.get("gbm", {})
        booster_path = data / "gbm_model.txt"
        if method == "gbm" and not (booster_path.exists() and gbm_meta):
            steps.append("method = gbm but data/gbm_model.txt is missing; fell back to the context tree.")
            method = "tree"
        chain = list(p.chain)
        bad = [c for c in chain if c not in TREE_LEVELS]
        if bad or len(set(chain)) != len(chain):
            raise ValueError(f"chain must list distinct levels from {', '.join(TREE_LEVELS)}; got {chain}")
        tree_specs = chain_specs(chain)
        hl = p.half_life_days
        base_counts, base_gbm_counts, n_past, first_date, last_date = _build_base_counts(
            data / "pitchers" / f"{pitcher['pitcher_id']}.csv.gz",
            as_of,
            oldest,
            float(hl),
            p.expr("recency_weight"),
            tuple(chain),
            method == "gbm",
            float(gbm_meta.get("half_life_days", 365.0)) if method == "gbm" else 0.0,
        )
        counts = base_counts.clone()
        gbm_counts = base_gbm_counts.clone() if base_gbm_counts else None
        for situation, t in self._today(seq, game_earlier, sit):
            if situation is not None:
                counts.add(situation, t, 1.0)
                if gbm_counts:
                    gbm_counts.add(situation, t, 1.0)
            elif gbm_counts:
                gbm_counts.tables["game"].setdefault(("today",), [0.0] * K)[INDEX[t]] += 1.0

        n_eff = sum(counts.get("overall", sit))
        steps.append(
            f"History: {n_past:,} pitches by {pitcher['name']} ({throws}HP) from {first_date} to "
            f"{last_date}, weighted by recency [{p.expr('recency_weight')}] with half_life_days = {hl:g} "
            f"→ {n_eff:,.0f} effective pitches.")
        steps.append(f"Situation: {balls}-{strikes} count vs a {stand}HB" + (
            f", at-bat so far: {' '.join(f'{t}({RESULT_NAMES[r]})' for t, r in seq)}" if seq else ", first pitch of the at-bat") + ".")

        prior = meta.get("league_prior", {}).get(throws) or [1.0 / K] * K
        tree_p = self._tree(counts, tree_specs, sit, prior, steps)
        probs = tree_p
        if method == "gbm":
            probs = self._gbm(booster_path, gbm_meta, gbm_counts, sit, inputs, batter, throws, seq, game_earlier,
                              prior, steps)
        if p.temperature != 1.0:
            logits = [math.log(max(x, 1e-12)) / p.temperature for x in probs]
            z = sum(math.exp(v) for v in logits)
            probs = [math.exp(v) / z for v in logits]
            steps.append(f"Applied temperature {p.temperature:g} (>1 flattens, <1 sharpens).")

        outcomes, other = [], 0.0
        for i in sorted(range(K), key=lambda i: -probs[i]):
            if probs[i] >= p.min_display_prob:
                outcomes.append(Outcome(f"{VOCAB[i]} {NAMES[VOCAB[i]]}", probability=probs[i], fmt="pct",
                                        note=f"tree {tree_p[i]:.0%}" if method == "gbm" else ""))
            else:
                other += probs[i]
        if other > 0:
            outcomes.append(Outcome("Other / new pitch", probability=other, fmt="pct",
                                    note=f"below {p.min_display_prob:.1%} each"))
        top = max(range(K), key=lambda i: probs[i])
        steps.append(f"Most likely: {NAMES[VOCAB[top]]} ({probs[top]:.0%}); uncertainty {entropy_bits(probs):.2f} bits "
                     f"(≈{2 ** entropy_bits(probs):.1f} equally likely pitches).")

        shown = {"pitcher": f"{pitcher['name']} ({throws}HP, id {pitcher['pitcher_id']})",
                 "count": f"{balls}-{strikes}", "batter side": stand}
        if batter:
            shown["batter"] = f"{batter['name']} (OPS {batter.get('ops') or 'n/a'}, wOBA {batter.get('woba') or 'n/a'})"
        if seq:
            shown["at-bat so far"] = " ".join(f"{t}:{r}" for t, r in seq)
        shown["history before"] = str(as_of)
        shown["method"] = method
        return self.prediction(
            inputs=shown, outcomes=outcomes, steps=steps,
            extras={"probs": {VOCAB[i]: round(probs[i], 6) for i in range(K)},
                    "tree_probs": {VOCAB[i]: round(tree_p[i], 6) for i in range(K)},
                    "method": method, "pitcher_id": pitcher["pitcher_id"], "history_pitches": len(past)},
        )

    @staticmethod
    def _today(seq, game_earlier, sit):
        """Pitches already thrown today: earlier-in-game ones (types only) and this at-bat's (full context)."""
        for t, _ in game_earlier:
            yield None, t
        b = s = 0
        prev: list[tuple[str, str]] = []
        for t, r in seq:
            situation = {**sit, "balls": b, "strikes": s, "prev_type": prev[-1][0] if prev else None,
                         "prev_result": prev[-1][1] if prev else None,
                         "prev2_type": prev[-2][0] if len(prev) > 1 else None}
            yield situation, t
            prev.append((t, r))
            b, s = count_after(prev)

    def _tree(self, counts, specs, sit, prior, steps) -> list[float]:
        p = self.params
        parent = list(prior)
        steps.append("Context tree [" + p.expr("shrink") + "], root = league mix for the pitcher's hand:")
        for level in specs:
            n = counts.get(level, sit)
            total = sum(n)
            strength = getattr(p, f"strength_{level}")
            if total + strength > 0:  # an empty context with strength 0 has no information: keep the parent
                parent = [p.formula("shrink", n=c, total=total, strength=strength, parent=q)
                          for c, q in zip(n, parent)]
            z = sum(parent)
            parent = [x / z for x in parent]
            label = "overall mix" if level == "overall" else f"+ {level.replace('_', ' ')}"
            top = sorted(range(K), key=lambda i: -parent[i])[:4]
            steps.append(f"{label}: {total:,.1f} weighted pitches, strength {strength:g} → "
                         + ", ".join(f"{VOCAB[i]} {parent[i]:.0%}" for i in top if parent[i] >= 0.005))
        return parent

    def _gbm(self, path, meta, counts, sit, inputs, batter, throws, seq, game_earlier, prior, steps) -> list[float]:
        p = self.params
        # the boosted model's own baseline: the context tree it was trained on (fixed, from meta.json)
        base = list(prior)
        chain = meta["chain_specs"]
        for spec, strength in zip(chain, meta["strengths"]):
            n = counts.get(spec, sit)
            total = sum(n)
            base = [(c + strength * q) / (total + strength) for c, q in zip(n, base)]
        logp = [math.log(max(x, 1e-9)) for x in base]
        f: dict[str, float] = {f"tree_logp_{t}": logp[i] for i, t in enumerate(VOCAB)}
        for spec in GBM_SPECS:
            n = counts.get(spec, sit)
            total = sum(n)
            for i, t in enumerate(VOCAB):
                f[f"{spec}_share_{t}"] = n[i] / total if total > 0 else math.nan
            f[f"{spec}_logn"] = math.log1p(total)
        bases = str(inputs.get("bases", ""))
        prev = seq[-1] if seq else None
        prev2 = seq[-2] if len(seq) > 1 else None
        gprev = (seq or game_earlier or [None])[-1]
        f.update({
            "balls": sit["balls"], "strikes": sit["strikes"], "count": sit["balls"] * 3 + sit["strikes"],
            "outs_when_up": sit["outs"], "inning": _num(inputs.get("inning")),
            "on_1b": float("1" in bases), "on_2b": float("2" in bases), "on_3b": float("3" in bases),
            "score_diff": _num(inputs.get("score_diff")), "n_thruorder_pitcher": sit["tto"], "ab_idx": len(seq),
            "game_pitch_n": _num(inputs.get("pitch_count"), len(game_earlier) + len(seq)),
            "batters_faced": _num(inputs.get("batters_faced")), "pitcher_days_since_prev_game": _num(inputs.get("days_rest")),
            "stand_i": float(sit["stand"] == "L"), "throws_i": float(throws == "L"),
            "prev_t": INDEX[prev[0]] if prev else K, "prev_r": RES_CODES.index(prev[1]) if prev else len(RES_CODES),
            "prev2_t": INDEX[prev2[0]] if prev2 else K, "prev2_r": RES_CODES.index(prev2[1]) if prev2 else len(RES_CODES),
            "game_prev_t": INDEX[gprev[0]] if gprev else K,
            "game_prev_r": RES_CODES.index(gprev[1]) if gprev else len(RES_CODES),
            "prev_x": _num(inputs.get("prev_x")), "prev_z": _num(inputs.get("prev_z")),
            "prev_speed": _num(inputs.get("prev_speed")), "prev_zone": _num(inputs.get("prev_zone")),
        })
        league = meta.get("batter_league", {})
        for col in BATTER_FEATURES:
            stored = (batter or {}).get(col, (batter or {}).get(f"{col}_vs{throws}"))  # mix seen depends on hand
            v = inputs.get(col, stored)
            f[col] = _num(v, league.get(col, math.nan)) if col != "bat_pa" else _num(v, 0.0)
        booster = _booster(path)
        row = [f.get(name, math.nan) for name in booster.feature_name()]
        raw = booster.predict([row], raw_score=True)[0]
        logits = [logp[i] + p.gbm_weight * raw[i] for i in range(K)]
        m = max(logits)
        e = [math.exp(v - m) for v in logits]
        z = sum(e)
        probs = [v / z for v in e]
        moves = sorted(range(K), key=lambda i: -abs(probs[i] - base[i]))[:3]
        steps.append(
            f"Gradient-boosted correction (trained {meta.get('trained', '?')}, {booster.num_trees() // K} rounds), "
            f"scaled by gbm_weight = {p.gbm_weight:g}, using count, sequence, situation and batter stats: "
            + ", ".join(f"{VOCAB[i]} {base[i]:.0%}→{probs[i]:.0%}" for i in moves if abs(probs[i] - base[i]) >= 0.005)
            + ".")
        if batter is None:
            steps.append("No batter given: batter stats set to league average.")
        return probs

    # ── backtest ─────────────────────────────────────────────────────────────

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        # data/backtest.csv columns: see MODEL.md "Backtest data"
        inputs: dict[str, Any] = {k: v for k, v in row.items() if v != "" and k not in ("actual", "pitcher")}
        inputs["pitcher"] = row["pitcher_id"]
        inputs.pop("pitcher_id", None)
        if "batter_id" in inputs:
            inputs["batter"] = inputs.pop("batter_id")
        for k in ("balls", "strikes", "outs", "tto"):
            if k in inputs:
                inputs[k] = int(inputs[k])
        return inputs, row["actual"]

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        probs = prediction.extras["probs"]
        if actual not in probs:
            raise ValueError(f"actual pitch type {actual!r} is not a model pitch type")
        top = max(probs, key=probs.get)
        return {
            "brier": sum((q - (t == actual)) ** 2 for t, q in probs.items()),
            "log_loss": -math.log(max(probs[actual], 1e-12)),
            "top_pick_correct": float(top == actual),
        }

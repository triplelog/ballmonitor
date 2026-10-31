"""Shared, stdlib-only pieces of next_pitch: pitch-type vocabulary, result codes, pitcher
history files and the context counts that both the context tree and the boosted model use.

The context tree (MODEL.md "Method") estimates P(next pitch type) by starting from the
pitcher's overall mix and refining it one context at a time (count, batter side, previous
pitch, ...). Each level is a recency-weighted frequency table shrunk toward the level above:

    p_level(x) = (n_level(x) + strength_level * p_parent(x)) / (N_level + strength_level)

This is the Aaronson-oracle idea (count what followed each recent pattern) with smoothing so
thin contexts fall back to broader ones.
"""

from __future__ import annotations

import csv
import gzip
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

# Statcast pitch_type codes predicted by the model. Rare aliases are folded in; anything else
# (pitchouts, intentional/automatic balls, unknowns) is not a pitch for this model.
VOCAB = ["FF", "SI", "FC", "SL", "ST", "SV", "CU", "KC", "CH", "FS", "FO", "KN", "EP", "SC"]
ALIASES = {"FA": "FF", "CS": "CU"}
NAMES = {
    "FF": "4-seam fastball", "SI": "sinker", "FC": "cutter", "SL": "slider", "ST": "sweeper",
    "SV": "slurve", "CU": "curveball", "KC": "knuckle curve", "CH": "changeup", "FS": "splitter",
    "FO": "forkball", "KN": "knuckleball", "EP": "eephus", "SC": "screwball",
}
INDEX = {t: i for i, t in enumerate(VOCAB)}
K = len(VOCAB)

# Pitch result codes used as sequence context.
RESULTS = {
    "ball": "B", "blocked_ball": "B", "pitchout": "B", "automatic_ball": "B",
    "called_strike": "C", "automatic_strike": "C",
    "swinging_strike": "S", "swinging_strike_blocked": "S", "missed_bunt": "S",
    "foul": "F", "foul_tip": "F", "foul_bunt": "F", "bunt_foul_tip": "F", "foul_pitchout": "F",
    "hit_into_play": "X", "hit_by_pitch": "H",
}
RESULT_NAMES = {"B": "ball", "C": "called strike", "S": "swinging strike", "F": "foul", "X": "in play",
                "H": "hit by pitch"}
RESULT_WORDS = {"ball": "B", "called": "C", "called_strike": "C", "swinging": "S", "whiff": "S",
                "swinging_strike": "S", "foul": "F"}

# Context levels: each maps a pitch situation to one part of a lookup key.
LEVELS = {
    "count": lambda s: (s["balls"], s["strikes"]),
    "stand": lambda s: s["stand"],
    "prev_type": lambda s: s.get("prev_type") or "-",
    "prev_result": lambda s: s.get("prev_result") or "-",
    "prev2_type": lambda s: s.get("prev2_type") or "-",
    "outs": lambda s: s.get("outs", 0),
    "runners": lambda s: "on" if s.get("runners") else "empty",
    "tto": lambda s: min(int(s.get("tto") or 1), 3),
    "batter": lambda s: s.get("batter"),
    "game": lambda s: s.get("game"),
    "game_prev_type": lambda s: s.get("game_prev_type") or "-",
}

# Context tables the boosted model reads (same names as the study's feature columns).
GBM_SPECS = {
    "all": (),
    "count": ("count",),
    "count_stand": ("count", "stand"),
    "count_stand_prev": ("count", "stand", "prev_type"),
    "count_stand_prev_res": ("count", "stand", "prev_type", "prev_result"),
    "count_stand_prev2": ("count", "stand", "prev_type", "prev_result", "prev2_type"),
    "stand": ("stand",),
    "prev_res": ("prev_type", "prev_result"),
    "batter": ("batter",),
    "game": ("game",),
    "first_after": ("count", "stand", "game_prev_type"),
}


def normalize_type(code: str | None) -> str | None:
    """Statcast pitch_type -> model vocabulary code, or None for a non-pitch."""
    code = (code or "").strip().upper()
    code = ALIASES.get(code, code)
    return code if code in INDEX else None


def result_code(text: str | None) -> str:
    text = (text or "").strip()
    if text.upper() in RESULT_NAMES:
        return text.upper()
    return RESULTS.get(text, RESULT_WORDS.get(text.lower(), "B"))


def entropy_bits(probs) -> float:
    return -sum(p * math.log2(p) for p in probs if p > 0)


def chain_specs(chain: list[str]) -> dict[str, tuple]:
    """Context-tree chain ["count", "stand", ...] -> nested specs root first."""
    unknown = [c for c in chain if c not in LEVELS]
    if unknown:
        raise ValueError(f"unknown context level(s) {unknown}; choose from {sorted(LEVELS)}")
    specs = {"overall": ()}
    for i, level in enumerate(chain):
        specs[level] = tuple(chain[: i + 1])
    return specs


class ContextCounts:
    """Weighted pitch-type counts for one pitcher in several contexts (specs)."""

    def __init__(self, specs: dict[str, tuple]):
        self.specs = specs
        self.tables: dict[str, dict] = {name: {} for name in specs}
        self._compiled = [(name, tuple(LEVELS[level] for level in spec)) for name, spec in specs.items()]

    @staticmethod
    def key(spec: tuple, situation: dict) -> tuple:
        return tuple(LEVELS[level](situation) for level in spec)

    def add(self, situation: dict, pitch_type: str, weight: float = 1.0) -> None:
        i = INDEX[pitch_type]
        for name, funcs in self._compiled:
            k = tuple(f(situation) for f in funcs)
            tbl = self.tables[name]
            row = tbl.get(k)
            if row is None:
                tbl[k] = row = [0.0] * K
            row[i] += weight

    def get(self, name: str, situation: dict) -> list[float]:
        funcs = tuple(LEVELS[level] for level in self.specs[name])
        k = tuple(f(situation) for f in funcs)
        return list(self.tables[name].get(k, [0.0] * K))

    def clone(self) -> ContextCounts:
        c = ContextCounts(self.specs)
        c.tables = {name: {k: list(v) for k, v in tbl.items()} for name, tbl in self.tables.items()}
        return c


# ── pitcher history files (data/pitchers/<id>.csv.gz, written by build.py) ────

def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=64)
def load_history(path: Path) -> tuple[dict, ...]:
    """A pitcher's pitches in order, as situation dicts with the previous-pitch context filled in."""
    rows = []
    with gzip.open(path, "rt", newline="") as fh:
        prev_ab, prev_game = None, None
        ab_types: list[tuple[str, str]] = []
        game_prev = None
        for r in csv.DictReader(fh):
            ab = (r["game_pk"], r["ab"])
            if ab != prev_ab:
                ab_types = []
                prev_ab = ab
            if r["game_pk"] != prev_game:
                game_prev = None
                prev_game = r["game_pk"]
            rows.append({
                "date": date.fromisoformat(r["date"]), "game": r["game_pk"], "batter": r["batter"],
                "balls": _int(r["balls"]), "strikes": _int(r["strikes"]), "stand": r["stand"],
                "type": r["pt"], "result": r["res"], "outs": _int(r["outs"]), "runners": _int(r["runners"]),
                "tto": _int(r["tto"], 1),
                "prev_type": ab_types[-1][0] if ab_types else None,
                "prev_result": ab_types[-1][1] if ab_types else None,
                "prev2_type": ab_types[-2][0] if len(ab_types) > 1 else None,
                "game_prev_type": game_prev,
            })
            ab_types.append((r["pt"], r["res"]))
            game_prev = r["pt"]
    return tuple(rows)


def parse_sequence(seq) -> list[tuple[str, str]]:
    """'FF:C SL:F' or ['FF:called_strike', 'SL:foul'] -> [(type, result code), ...]."""
    if not seq:
        return []
    items = seq.replace(",", " ").split() if isinstance(seq, str) else list(seq)
    out = []
    for item in items:
        t, _, r = str(item).partition(":")
        code = normalize_type(t)
        if code is None:
            raise ValueError(f"unknown pitch type {t!r} in sequence; use Statcast codes like {', '.join(VOCAB[:6])}")
        r = r.strip()
        if not r:
            raise ValueError(f"pitch {item!r} in sequence has no result; write TYPE:RESULT, e.g. {t}:B "
                             "(B ball, C called strike, S swinging strike, F foul, X in play, H hit by pitch)")
        if r.upper() not in RESULT_NAMES and r not in RESULTS and r.lower() not in RESULT_WORDS:
            raise ValueError(f"unknown pitch result {r!r} in {item!r}; use B, C, S, F, X or H "
                             "(or a Statcast description such as called_strike)")
        out.append((code, result_code(r)))
    return out


def count_after(sequence: list[tuple[str, str]]) -> tuple[int, int]:
    """Ball-strike count implied by an at-bat's pitches so far (fouls don't add a third strike)."""
    balls = strikes = 0
    for _, r in sequence:
        if r == "B":
            balls += 1
        elif r in ("C", "S") or (r == "F" and strikes < 2):
            strikes += 1
    if balls > 3 or strikes > 2:
        raise ValueError("that sequence would already have ended the at-bat")
    return balls, strikes

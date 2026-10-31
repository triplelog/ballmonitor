"""Bullpen rest, fatigue, usage history and role ledger.

Tracks trailing workload (pitches on each of the last 5 days) and recent usage history
(appearances, saves, holds, ... over the pitcher's last roster-games) for each reliever,
infers bullpen roles from that history, and computes availability, fatigue penalties and
the usage-propensity score term. All thresholds and weights come from config params.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

HANDS = ("R", "L")
ROLES = ("closer", "setup", "middle", "long")
HISTORY_FIELDS = ("games", "apps", "firsts", "saves", "holds", "finishes", "outs")


@dataclass
class RelieverWorkload:
    """Workload, usage history and role of one relief pitcher.

    `pitches_days`: pitches thrown on trailing days, index 0 = yesterday (d-1) ... 4 = d-5.
    History (all optional, over the pitcher's last roster-games before today): `games`
    roster-games, `apps` relief appearances, `firsts` times first out of the pen, `saves`,
    `holds`, `finishes` (games finished), `outs` recorded in relief.
    `role` is "" until given or inferred; `role_source` explains where it came from.
    `active` = on today's active roster (False -> cannot pitch); `new_arrival` = joined the
    active roster today (was not on yesterday's roster).
    """

    name: str
    hand: str  # "R" or "L"
    role: str = ""
    pitches_days: list[int] = field(default_factory=list)
    games: int = 0
    apps: int = 0
    firsts: int = 0
    saves: int = 0
    holds: int = 0
    finishes: int = 0
    outs: int = 0
    active: bool = True
    new_arrival: bool = False
    role_source: str = "given"

    @property
    def yesterday(self) -> int:
        """1 if pitched yesterday, else 0."""
        return 1 if (self.pitches_days and self.pitches_days[0] > 0) else 0

    @property
    def pitches_yesterday(self) -> int:
        return self.pitches_days[0] if self.pitches_days else 0

    @property
    def back_to_back(self) -> int:
        """1 if pitched both yesterday and 2 days ago, else 0."""
        if len(self.pitches_days) >= 2:
            return 1 if (self.pitches_days[0] > 0 and self.pitches_days[1] > 0) else 0
        return 0

    @property
    def three_straight(self) -> int:
        """1 if pitched on 3 consecutive days."""
        if len(self.pitches_days) >= 3:
            return 1 if all(x > 0 for x in self.pitches_days[:3]) else 0
        return 0

    @property
    def pitches_3d(self) -> int:
        return sum(self.pitches_days[:3])

    @property
    def pitches_5d(self) -> int:
        return sum(self.pitches_days[:5])

    def high_workload(self, threshold: int) -> int:
        """1 if threw `threshold`+ pitches yesterday (param `high_workload_pitches`)."""
        return 1 if self.pitches_yesterday >= threshold else 0

    @property
    def days_rest(self) -> int:
        """Days since last appearance (0 if yesterday, 1 if 2 days ago, etc.)."""
        for i, p in enumerate(self.pitches_days):
            if p > 0:
                return i
        return 999  # well rested

    def usage_rate(self, params: Any) -> float:
        """Shrunk appearance rate: (apps + k * r0) / (games + k), k = usage_prior_games,
        r0 = usage_prior_rate. No history -> r0."""
        k, r0 = float(params.usage_prior_games), float(params.usage_prior_rate)
        return (self.apps + k * r0) / (self.games + k) if (self.games + k) > 0 else r0

    def usage_score(self, params: Any) -> float:
        """Score term usage_weight * ln(usage_rate / usage_prior_rate)."""
        r0 = float(params.usage_prior_rate)
        return float(params.usage_weight) * math.log(max(self.usage_rate(params), 1e-6) / r0)


def _flag(value: Any, what: str) -> bool:
    """Parse a boolean input (true/false, 1/0, "yes"/"no")."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    raise ValueError(f"{what} must be true or false, got {value!r}")


def infer_roles(relievers: list[RelieverWorkload], params: Any) -> None:
    """Fill in missing roles from usage history (in place). Given roles are kept.

    closer: most saves in the window (>= closer_min_saves; ties -> more finishes);
    setup:  next `setup_count` by holds (>= setup_min_holds);
    long:   >= role_min_apps appearances averaging >= long_min_outs_per_app outs;
    middle: everyone else (including arms with no history).
    """
    todo = [r for r in relievers if not r.role]
    taken = {r.role for r in relievers if r.role}
    if "closer" not in taken:
        cands = [r for r in todo if r.saves >= params.closer_min_saves]
        if cands:
            c = max(cands, key=lambda r: (r.saves, r.finishes, r.holds))
            c.role, c.role_source = "closer", f"inferred: {c.saves} saves in last {c.games} g"
            todo.remove(c)
    n_setup = int(params.setup_count) - sum(1 for r in relievers if r.role == "setup")
    cands = sorted(
        (r for r in todo if r.holds >= params.setup_min_holds),
        key=lambda r: (r.holds, r.saves), reverse=True,
    )
    for r in cands[: max(0, n_setup)]:
        r.role, r.role_source = "setup", f"inferred: {r.holds} holds in last {r.games} g"
        todo.remove(r)
    for r in todo:
        per_app = r.outs / r.apps if r.apps else 0.0
        if r.apps >= params.role_min_apps and per_app >= params.long_min_outs_per_app:
            r.role, r.role_source = "long", f"inferred: {per_app / 3:.1f} IP per outing"
        else:
            r.role = "middle"
            r.role_source = "inferred: default" if r.games else "no history: default"


class BullpenLedger:
    """Manages the active bullpen and evaluates pitcher availability and fatigue."""

    def __init__(self, relievers: list[RelieverWorkload]):
        self.relievers = {r.name: r for r in relievers}

    @classmethod
    def from_inputs(cls, data: list[dict[str, Any]], params: Any = None) -> BullpenLedger:
        """Create a ledger from TOML/dictionary inputs (raises ValueError on bad input).
        Missing roles (or role = "auto") are inferred from history when `params` is given."""
        if not isinstance(data, list):
            raise ValueError("'relievers' must be a list of tables ([[relievers]])")
        relievers = []
        seen: set[str] = set()
        for i, item in enumerate(data, 1):
            if not isinstance(item, dict):
                raise ValueError(f"reliever #{i} must be a table with name/hand/role/pitches_days")
            name = str(item.get("name", "")).strip()
            if not name:
                raise ValueError(f"reliever #{i} needs a 'name'")
            if name in seen:
                raise ValueError(f"duplicate reliever name '{name}'")
            seen.add(name)
            hand = str(item.get("hand", "R")).upper()
            if hand not in HANDS:
                raise ValueError(f"reliever '{name}': hand must be 'R' or 'L', got {item.get('hand')!r}")
            role = str(item.get("role", "") or "").strip().lower()
            if role == "auto":
                role = ""
            if role and role not in ROLES:
                raise ValueError(
                    f"reliever '{name}': role must be one of {', '.join(ROLES)} or 'auto', got {role!r}"
                )
            pitches = item.get("pitches_days", [])
            if isinstance(pitches, str):
                pitches = [x.strip() for x in pitches.split(",") if x.strip()]
            try:
                pitches = [int(x) for x in pitches]
                hist = {k: int(item.get(k, 0) or 0) for k in HISTORY_FIELDS}
            except (TypeError, ValueError):
                raise ValueError(
                    f"reliever '{name}': pitches_days must be whole pitch counts "
                    f"[yesterday, 2d ago, ...] and history fields whole numbers"
                ) from None
            if any(x < 0 for x in pitches) or any(v < 0 for v in hist.values()):
                raise ValueError(f"reliever '{name}': pitch counts and history cannot be negative")
            if hist["apps"] > hist["games"] and hist["games"]:
                raise ValueError(f"reliever '{name}': apps ({hist['apps']}) > games ({hist['games']})")
            relievers.append(
                RelieverWorkload(
                    name=name, hand=hand, role=role, pitches_days=pitches,
                    active=_flag(item.get("active", True), f"reliever '{name}': active"),
                    new_arrival=_flag(item.get("new_arrival", False), f"reliever '{name}': new_arrival"),
                    **hist,
                )
            )
        if params is not None:
            infer_roles(relievers, params)
        else:
            for r in relievers:
                r.role = r.role or "middle"
        return cls(relievers)

    def is_available(self, reliever: RelieverWorkload, params: Any) -> bool:
        """Hard constraint: is this reliever realistically available to pitch today?"""
        return not self.unavailable_reasons(reliever, params)

    def unavailable_reasons(self, reliever: RelieverWorkload, params: Any) -> list[str]:
        """Why a reliever is unavailable today (empty list = available)."""
        reasons = []
        if not reliever.active:
            reasons.append("not on the active roster")
        streak = next((i for i, x in enumerate(reliever.pitches_days) if x == 0), len(reliever.pitches_days))
        if streak >= params.max_consecutive_days:
            reasons.append(f"pitched {streak} days in a row")
        if reliever.pitches_yesterday >= params.max_pitches_yesterday:
            reasons.append(f"high pitch count yesterday ({reliever.pitches_yesterday})")
        if reliever.pitches_3d >= params.max_pitches_3d:
            reasons.append(f"heavy 3-day load ({reliever.pitches_3d} pitches)")
        return reasons

    def compute_fatigue_penalty(
        self,
        reliever: RelieverWorkload,
        params: Any,
        *,
        off_day_tomorrow: bool = False,
    ) -> float:
        """Score penalty for recent workload: config formula `fatigue_penalty`,
        times `off_day_tomorrow_discount` when tomorrow is an off-day."""
        penalty = float(
            params.formula(
                "fatigue_penalty",
                yesterday=reliever.yesterday,
                back_to_back=reliever.back_to_back,
                three_straight=reliever.three_straight,
                pitches_3d=reliever.pitches_3d,
                high_workload=reliever.high_workload(int(params.high_workload_pitches)),
            )
        )
        if off_day_tomorrow:
            penalty *= params.off_day_tomorrow_discount
        return penalty

    def describe_status(
        self, reliever: RelieverWorkload, params: Any, *, off_day_tomorrow: bool = False
    ) -> str:
        """Human-readable rest status for reports and output steps."""
        reasons = self.unavailable_reasons(reliever, params)
        if reasons:
            return f"Unavailable ({', '.join(reasons)})"

        penalty = self.compute_fatigue_penalty(reliever, params, off_day_tomorrow=off_day_tomorrow)
        if penalty == 0:
            if reliever.days_rest >= 2:
                rest = "no outings in last 5 days" if reliever.days_rest == 999 else f"{reliever.days_rest} days rest"
                return f"Well rested ({rest})"
            return "Available (rested)"
        if penalty < 2.0:
            return f"Available (light fatigue: -{penalty:.1f} pts, {reliever.pitches_3d}p in 3d)"
        return f"Limited (heavy fatigue: -{penalty:.1f} pts, {reliever.pitches_3d}p in 3d)"

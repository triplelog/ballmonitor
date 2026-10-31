"""
Data models and representations for teams, bowls, games, and simulation outcomes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Team:
    id: str
    name: str
    conf: str
    rating: float
    apr: int
    brand: int
    city: str
    state: str
    lat: float
    lon: float
    wins: int
    losses: int
    conf_wins: int
    conf_losses: int
    legacy_pac12: bool = False
    acc_bowl_eligible: bool = False
    last_bowl: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Team:
        return cls(
            id=data["id"],
            name=data["name"],
            conf=data["conf"],
            rating=float(data.get("rating", 0.0)),
            apr=int(data.get("apr", 980)),
            brand=int(data.get("brand", 5)),
            city=data.get("city", ""),
            state=data.get("state", ""),
            lat=float(data.get("lat", 0.0)),
            lon=float(data.get("lon", 0.0)),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            conf_wins=int(data.get("conf_wins", 0)),
            conf_losses=int(data.get("conf_losses", 0)),
            legacy_pac12=bool(data.get("legacy_pac12", False)),
            acc_bowl_eligible=bool(data.get("acc_bowl_eligible", False)),
            last_bowl=data.get("last_bowl")
        )

@dataclass
class Bowl:
    id: str
    name: str
    city: str
    state: str
    lat: float
    lon: float
    is_cfp: bool
    cfp_round: str | None = None
    payout: int = 1000000
    prestige: int = 5
    # Two tie-in slots: {"confs": [...], "order": n}. A conf entry is a conference name,
    # "Pac-12 legacy" (the 12 pre-2024 Pac-12 schools) or any eligible team if empty.
    slots: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bowl:
        return cls(
            id=data["id"],
            name=data["name"],
            city=data.get("city", ""),
            state=data.get("state", ""),
            lat=float(data.get("lat", 0.0)),
            lon=float(data.get("lon", 0.0)),
            is_cfp=bool(data.get("is_cfp", False)),
            cfp_round=data.get("cfp_round"),
            payout=int(data.get("payout", 1000000)),
            prestige=int(data.get("prestige", 5)),
            slots=list(data.get("slots", [])),
        )

    def distance_to(self, team: Team) -> float:
        """Great-circle distance between bowl site and team campus in miles (Haversine formula)."""
        r = 3958.8  # Earth radius in miles
        phi1 = math.radians(self.lat)
        phi2 = math.radians(team.lat)
        delta_phi = math.radians(team.lat - self.lat)
        delta_lambda = math.radians(team.lon - self.lon)

        a = (math.sin(delta_phi / 2.0) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c

@dataclass
class Game:
    home: str
    away: str
    neutral: bool = False
    conf: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Game:
        return cls(
            home=data["home"],
            away=data["away"],
            neutral=bool(data.get("neutral", False)),
            conf=bool(data.get("conf", True))
        )

    @property
    def opponents_are_fbs(self) -> bool:
        return not (self.home.startswith("fcs_") or self.away.startswith("fcs_"))

@dataclass
class TeamSimState:
    team: Team
    wins: int
    losses: int
    conf_wins: int
    conf_losses: int
    is_conf_champ: bool = False
    conf_runner_up: bool = False
    resume_score: float = 0.0
    cfp_seed: int | None = None
    cfp_bye: bool = False
    assigned_bowl: str | None = None

    @property
    def id(self) -> str:
        return self.team.id

    @property
    def name(self) -> str:
        return self.team.name

    @property
    def conf(self) -> str:
        return self.team.conf

    @property
    def rating(self) -> float:
        return self.team.rating

    @property
    def total_games(self) -> int:
        return self.wins + self.losses

    @property
    def win_pct(self) -> float:
        return self.wins / self.total_games if self.total_games > 0 else 0.0

    @property
    def conf_win_pct(self) -> float:
        cg = self.conf_wins + self.conf_losses
        return self.conf_wins / cg if cg > 0 else 0.0

    @property
    def is_eligible(self) -> bool:
        return self.wins >= 6

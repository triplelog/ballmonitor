"""
cfbRec - Offer-Based College Football Recruiting Rankings
"""

from .models import Recruit, TeamRating, RankingResult, RankingMethod
from .data_loader import DataLoader
from .elo_engine import EloEngine
from .geocoding import CityLocator, haversine_miles, get_campus_coords
from .position_model import (
    PositionWeight,
    TeamPositionalRating,
    PositionalRankingResult,
    PositionalRankingEngine,
    DEFAULT_POSITION_WEIGHTS,
)
from .forecasting import (
    CommitmentPredictor,
    ForecastedTeamRating,
    ForecastResult,
    ScenarioComparison,
    ScenarioDelta,
    SigningDayForecaster,
)

__all__ = [
    "Recruit",
    "TeamRating",
    "RankingResult",
    "RankingMethod",
    "DataLoader",
    "EloEngine",
    "CityLocator",
    "haversine_miles",
    "get_campus_coords",
    "PositionWeight",
    "TeamPositionalRating",
    "PositionalRankingResult",
    "PositionalRankingEngine",
    "DEFAULT_POSITION_WEIGHTS",
    "CommitmentPredictor",
    "ForecastedTeamRating",
    "ForecastResult",
    "ScenarioComparison",
    "ScenarioDelta",
    "SigningDayForecaster",
]

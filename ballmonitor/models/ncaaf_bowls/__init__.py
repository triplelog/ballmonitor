"""
College Football Bowl Simulator & Picking Order Model.
"""

from .analysis import BrandAnalysis, DistanceAnalysis, HistoricalAnalyzer, RepeatAnalysis
from .backtest import Backtester, BacktestScorecard
from .cfp import CFPGameResult, CFPResult, CFPSelector
from .config import SimConfig
from .engine import BowlAppearanceDetail, BowlEngine, BowlSummary, SimulationResults, TeamSummary
from .domain import Bowl, Game, Team, TeamSimState
from .ratings import RatingManager
from .scenarios import Scenario
from .selection import BowlMatchup, BowlSelector
from .simulator import SeasonSimulator

__all__ = [
    "SimConfig",
    "BowlEngine",
    "SimulationResults",
    "TeamSummary",
    "BowlSummary",
    "BowlAppearanceDetail",
    "Team",
    "Bowl",
    "Game",
    "TeamSimState",
    "RatingManager",
    "Scenario",
    "Backtester",
    "BacktestScorecard",
    "HistoricalAnalyzer",
    "RepeatAnalysis",
    "BrandAnalysis",
    "DistanceAnalysis",
    "SeasonSimulator",
    "CFPSelector",
    "CFPResult",
    "CFPGameResult",
    "BowlSelector",
    "BowlMatchup",
]

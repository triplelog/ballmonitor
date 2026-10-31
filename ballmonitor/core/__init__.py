"""Shared framework: config + params, the Prediction output type, rendering, backtesting."""

from ballmonitor.core.config import ModelConfig, load_config
from ballmonitor.core.model import BaseModel
from ballmonitor.core.params import ConfigError, Params, ParamSpec
from ballmonitor.core.prediction import Outcome, Prediction, Table

__all__ = [
    "BaseModel",
    "ConfigError",
    "ModelConfig",
    "Outcome",
    "ParamSpec",
    "Params",
    "Prediction",
    "Table",
    "load_config",
]

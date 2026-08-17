"""MiniQbot-Lite 策略系统"""

from .base import BaseStrategy
from .trend_strategy import TrendStrategy
from .rotation_strategy import RotationStrategy
from .etf_rotation_strategy import ETFRotationStrategy
from .indicators import compute_ma, compute_rsi, detect_golden_cross, detect_death_cross

__all__ = [
    "BaseStrategy",
    "TrendStrategy",
    "RotationStrategy",
    "ETFRotationStrategy",
    "compute_ma",
    "compute_rsi",
    "detect_golden_cross",
    "detect_death_cross",
]

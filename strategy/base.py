"""
策略基类模块
参考 vn.py Strategy 接口设计
V0.2
"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseStrategy(ABC):
    """所有策略的抽象基类

    统一接口:
        on_market_data()  — 接收市场数据更新
        generate_signal() — 生成交易信号
        buy()             — 买入信号
        sell()            — 卖出信号
    """

    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}
        self.signals: list[dict] = []  # 信号历史

    @abstractmethod
    def on_market_data(self, kline_df: pd.DataFrame) -> None:
        """处理市场数据更新

        Args:
            kline_df: 日K线 DataFrame
        """
        ...

    @abstractmethod
    def generate_signal(self) -> Optional[dict]:
        """生成交易信号

        Returns:
            dict 或 None:
            {
                "action": "BUY" | "SELL" | "HOLD",
                "strategy": self.name,
                "symbol": str,
                "price": float,
                "reason": str,
                "timestamp": str,
            }
        """
        ...

    def buy(self, symbol: str, price: float, reason: str = "") -> dict:
        """生成买入信号"""
        signal = {
            "action": "BUY",
            "strategy": self.name,
            "symbol": symbol,
            "price": price,
            "reason": reason,
        }
        self.signals.append(signal)
        return signal

    def sell(self, symbol: str, price: float, reason: str = "") -> dict:
        """生成卖出信号"""
        signal = {
            "action": "SELL",
            "strategy": self.name,
            "symbol": symbol,
            "price": price,
            "reason": reason,
        }
        self.signals.append(signal)
        return signal

    def reset(self):
        """重置策略状态"""
        self.signals.clear()

    def __repr__(self):
        return f"<Strategy {self.name}>"

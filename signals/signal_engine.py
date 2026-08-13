"""
信号引擎模块
管理多策略的信号生成、合并和冲突解决
V0.2
"""

from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from strategy import BaseStrategy, TrendStrategy, RotationStrategy


class Signal:
    """信号数据类"""

    def __init__(self, data: dict):
        self.action = data.get("action", "HOLD")
        self.strategy = data.get("strategy", "")
        self.symbol = data.get("symbol", "")
        self.price = data.get("price", 0.0)
        self.reason = data.get("reason", "")
        self.timestamp = data.get("timestamp", datetime.now().isoformat())
        self.candidates = data.get("candidates", [])

    def __repr__(self):
        if self.action == "ROTATION_LIST":
            return f"[{self.strategy}] 轮动榜单: {len(self.candidates)}只候选"
        return f"[{self.strategy}] {self.action} {self.symbol} @ ¥{self.price:.2f} — {self.reason}"

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "price": self.price,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class SignalEngine:
    """信号引擎

    职责:
        1. 注册/管理多个策略实例
        2. 向所有策略推送市场数据
        3. 收集并合并信号
        4. 解决冲突（同股票多信号时按策略优先级）
    """

    def __init__(self):
        self._strategies: list[BaseStrategy] = []
        self._priority: dict[str, int] = {}  # 策略名 -> 优先级（越小越高）

    def register(self, strategy: BaseStrategy, priority: int = 10):
        """注册一个策略

        Args:
            strategy: BaseStrategy 实例
            priority: 优先级，数字越小越优先
        """
        self._strategies.append(strategy)
        self._priority[strategy.name] = priority
        logger.info(f"📌 注册策略: {strategy.name} (优先级={priority})")

    def register_defaults(self):
        """注册默认策略"""
        self.register(TrendStrategy(), priority=1)
        self.register(RotationStrategy(), priority=2)
        logger.info(f"✅ 已注册 {len(self._strategies)} 个默认策略")

    def feed_data(self, symbol: str, kline_df: pd.DataFrame):
        """向所有策略推送K线数据"""
        for strategy in self._strategies:
            if hasattr(strategy, "on_market_data"):
                strategy.on_market_data(kline_df)

    def generate_all(self) -> list[Signal]:
        """让所有策略生成信号

        Returns:
            信号列表（按策略优先级排序）
        """
        signals = []
        for strategy in self._strategies:
            try:
                result = strategy.generate_signal()
                if result is not None:
                    signals.append(Signal(result))
            except Exception as e:
                logger.error(f"策略 {strategy.name} 信号生成失败: {e}")

        # 按优先级排序
        signals.sort(key=lambda s: self._priority.get(s.strategy, 99))
        return signals

    def get_trend_signal(self, symbol: str, kline_df: pd.DataFrame) -> Optional[Signal]:
        """快捷方法: 对单只股票运行趋势策略

        Args:
            symbol: 股票代码
            kline_df: 日K线数据

        Returns:
            BUY/SELL/None
        """
        # 找趋势策略
        trend = None
        for s in self._strategies:
            if isinstance(s, TrendStrategy):
                trend = s
                break

        if trend is None:
            trend = TrendStrategy()
            self.register(trend, priority=1)

        trend.reset()
        trend.on_market_data(kline_df)
        result = trend.generate_signal()

        if result:
            result["symbol"] = symbol
            return Signal(result)
        return None

    def get_rotation_candidates(self) -> pd.DataFrame:
        """快捷方法: 获取轮动候选列表"""
        rotation = None
        for s in self._strategies:
            if isinstance(s, RotationStrategy):
                rotation = s
                break

        if rotation is None:
            rotation = RotationStrategy()
            self.register(rotation, priority=2)

        return rotation.get_candidates()

    def list_strategies(self) -> list[dict]:
        """列出所有已注册策略"""
        return [
            {
                "name": s.name,
                "type": s.__class__.__name__,
                "priority": self._priority.get(s.name, 99),
                "params": s.params,
            }
            for s in self._strategies
        ]

    def reset_all(self):
        """重置所有策略"""
        for s in self._strategies:
            s.reset()
        logger.info("🔄 所有策略已重置")

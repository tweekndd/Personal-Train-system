"""
策略A: 低风险趋势策略
参考 PRD — 20日均线金叉 + RSI 40-70 + 量能确认
V0.2
"""

from typing import Optional

import pandas as pd
from loguru import logger

from strategy.base import BaseStrategy
from strategy.indicators import (
    compute_ma,
    compute_rsi,
    detect_golden_cross,
    detect_death_cross,
    compute_volume_ratio,
)
from config import TREND_STRATEGY as CONFIG_PARAMS


class TrendStrategy(BaseStrategy):
    """低风险趋势策略

    买入条件（同时满足）:
        1. 价格站上20日均线
        2. 5日均线上穿20日均线（金叉）
        3. 成交量增加（量比 > 1.2）
        4. RSI 处于 40-70

    卖出条件（满足任一）:
        a. 盈利 +5%
        b. 亏损 -5%
        c. 趋势破坏（死叉或跌破20MA）
    """

    def __init__(self, params: dict = None):
        default_params = dict(CONFIG_PARAMS)  # 从 config.py 读取，修改 config.py 即生效
        if params:
            default_params.update(params)
        super().__init__("低风险趋势策略", default_params)

        # 状态
        self._kline: pd.DataFrame = pd.DataFrame()
        self._signal: Optional[dict] = None
        self._entry_price: Optional[float] = None  # 持仓成本价

    def on_market_data(self, kline_df: pd.DataFrame) -> None:
        """处理K线数据，计算所有技术指标"""
        if kline_df.empty:
            return

        self._kline = kline_df.copy()
        close = self._kline["close"]

        # 计算指标
        p = self.params
        self._kline["ma_short"] = compute_ma(close, p["ma_short"])
        self._kline["ma_long"] = compute_ma(close, p["ma_long"])
        self._kline["rsi"] = compute_rsi(close, p["rsi_window"])
        self._kline["golden_cross"] = detect_golden_cross(
            self._kline["ma_short"], self._kline["ma_long"]
        )
        self._kline["death_cross"] = detect_death_cross(
            self._kline["ma_short"], self._kline["ma_long"]
        )
        if "volume" in self._kline.columns:
            self._kline["volume_ratio"] = compute_volume_ratio(
                self._kline["volume"], p["ma_short"]
            )

        self._signal = None

    def generate_signal(self) -> Optional[dict]:
        """生成买卖信号

        Returns:
            BUY / SELL / HOLD 信号
        """
        if self._kline.empty or len(self._kline) < 30:
            return None

        latest = self._kline.iloc[-1]
        prev = self._kline.iloc[-2] if len(self._kline) > 1 else latest
        symbol = latest.get("symbol", "未知")
        price = float(latest["close"])
        p = self.params

        # === 买入检查 ===
        buy_conditions = self._check_buy(latest, prev)
        if buy_conditions["all_met"]:
            signal = self.buy(symbol, price, buy_conditions["reason"])
            logger.info(f"📗 {self.name} BUY {symbol} @ ¥{price:.2f} — {buy_conditions['reason']}")
            self._entry_price = price
            self._signal = signal
            return signal

        # === 卖出检查（有持仓时）===
        if self._entry_price is not None:
            sell_reason = self._check_sell(latest, price)
            if sell_reason:
                signal = self.sell(symbol, price, sell_reason)
                logger.info(f"📕 {self.name} SELL {symbol} @ ¥{price:.2f} — {sell_reason}")
                self._entry_price = None
                self._signal = signal
                return signal

        return None

    def _check_buy(self, latest: pd.Series, prev: pd.Series) -> dict:
        """检查买入条件"""
        p = self.params
        reasons = []
        all_met = True

        # 1. 价格站上20日均线
        price_above_ma = latest["close"] > latest["ma_long"]
        if price_above_ma:
            reasons.append("价格站上20MA")
        else:
            all_met = False

        # 2. 金叉 (5MA上穿20MA)
        if latest.get("golden_cross", False):
            reasons.append("5MA金叉20MA")
        else:
            all_met = False

        # 3. RSI 在 40-70
        rsi = latest.get("rsi", 50)
        rsi_ok = p["rsi_low"] <= rsi <= p["rsi_high"]
        if rsi_ok:
            reasons.append(f"RSI={rsi:.1f}")
        else:
            all_met = False

        # 4. 成交量放大
        vol_ratio = latest.get("volume_ratio", 1.0)
        vol_ok = vol_ratio >= p["volume_ratio_min"]
        if vol_ok:
            reasons.append(f"量比={vol_ratio:.2f}")
        else:
            all_met = False

        return {
            "all_met": all_met,
            "reason": " | ".join(reasons),
        }

    def _check_sell(self, latest: pd.Series, current_price: float) -> Optional[str]:
        """检查卖出条件"""
        p = self.params
        if self._entry_price is None or self._entry_price == 0:
            return None

        profit_pct = (current_price - self._entry_price) / self._entry_price

        # a. 止盈 +5%
        if profit_pct >= p["take_profit"]:
            return f"止盈 +{profit_pct*100:.1f}%"

        # b. 止损 -5%
        if profit_pct <= -p["stop_loss"]:
            return f"止损 {profit_pct*100:.1f}%"

        # c. 趋势破坏（死叉 或 跌破20MA）
        if latest.get("death_cross", False):
            return "死叉信号"

        if latest["close"] < latest["ma_long"]:
            return "跌破20MA"

        return None

    def set_entry_price(self, price: float):
        """设置持仓成本价（供外部回测用）"""
        self._entry_price = price

    def reset(self):
        super().reset()
        self._entry_price = None
        self._signal = None

"""
市场环境分析模块
判断当前市场状态：趋势/震荡/熊市
V0.5
"""

import pandas as pd
import numpy as np
from loguru import logger

from data import DataFetcher


class MarketAnalyzer:
    """市场环境分析器

    基于大盘指数判断市场状态:
        - 📈 趋势市场 (Trending)
        - 📊 震荡市场 (Consolidating)
        - 📉 熊市/下跌市场 (Bear)
    """

    # 常用大盘指数代码
    INDEX_MAP = {
        "上证指数": "000001",
        "深证成指": "399001",
        "创业板指": "399006",
        "科创50": "000688",
    }

    def __init__(self):
        self.fetcher = DataFetcher()

    # ── 指数分析 ──────────────────────────────────────────────

    def analyze_index(self, symbol: str = "000001", name: str = "上证指数") -> dict:
        """分析单个指数

        Returns:
            {
                "index": "上证指数",
                "trend": "trending" | "consolidating" | "bear",
                "ma_trend": str,
                "volatility": float,
                "rsi": float,
                "position_advice": str,
            }
        """
        df = self.fetcher.get_index_kline(symbol)
        if df.empty:
            logger.warning(f"无法获取 {name} 数据")
            return {"index": name, "error": "无数据"}

        close = df["close"].values
        if len(close) < 50:
            return {"index": name, "error": "数据不足"}

        # 计算均线
        ma20 = pd.Series(close).rolling(20).mean().values
        ma60 = pd.Series(close).rolling(60).mean().values
        latest = close[-1]
        ma20_val = ma20[-1]
        ma60_val = ma60[-1] if not np.isnan(ma60[-1]) else ma20_val

        # 均线趋势
        if latest > ma20_val > ma60_val:
            ma_trend = "多头排列 (价格 > MA20 > MA60) 📈"
        elif latest < ma20_val < ma60_val:
            ma_trend = "空头排列 (价格 < MA20 < MA60) 📉"
        else:
            ma_trend = "均线交织 (震荡) 📊"

        # 波动率 (20日)
        returns = pd.Series(close).pct_change().dropna()
        volatility = returns.tail(20).std() * np.sqrt(252)

        # RSI
        from strategy.indicators import compute_rsi
        rsi_series = compute_rsi(pd.Series(close))
        rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

        # 趋势判断
        recent = close[-20:]
        trend_strength = (recent[-1] - recent[0]) / recent[0]
        volatility_20d = pd.Series(recent).pct_change().std()

        if abs(trend_strength) < 0.05 and volatility_20d < 0.02:
            trend = "consolidating"
            trend_label = "震荡市场 📊"
            advice = "高抛低吸，控制仓位"
        elif trend_strength > 0:
            trend = "trending"
            trend_label = "上涨趋势 📈"
            advice = "顺势而为，持股为主"
        else:
            trend = "bear"
            trend_label = "下跌趋势 📉"
            advice = "防御为主，降低仓位，关注债券ETF"

        return {
            "index": name,
            "code": symbol,
            "current": round(latest, 2),
            "ma20": round(ma20_val, 2),
            "ma60": round(ma60_val, 2),
            "ma_trend": ma_trend,
            "trend": trend,
            "trend_label": trend_label,
            "volatility": round(volatility * 100, 2),
            "rsi": round(rsi, 1),
            "trend_strength": round(trend_strength * 100, 2),
            "position_advice": advice,
        }

    def full_analysis(self) -> list[dict]:
        """全市场分析：扫描主要指数"""
        results = []
        for name, code in self.INDEX_MAP.items():
            result = self.analyze_index(code, name)
            results.append(result)
        return results

    def summary(self) -> str:
        """格式化输出市场分析报告"""
        results = self.full_analysis()

        lines = [
            f"\n{'='*50}",
            f"  🌍 市场环境分析",
            f"  {'='*50}",
        ]

        for r in results:
            if "error" in r:
                lines.append(f"  ⚠️  {r['index']}: {r['error']}")
                continue
            lines.append(f"  {r['trend_label']} {r['index']} ({r['code']})")
            lines.append(f"     现价: {r['current']} | "
                         f"MA20: {r['ma20']} | MA60: {r['ma60']}")
            lines.append(f"     RSI: {r['rsi']} | "
                         f"波动率: {r['volatility']}% | "
                         f"趋势强度: {r['trend_strength']:+.2f}%")
            lines.append(f"     💡 {r['position_advice']}")

        valid = [r for r in results if "error" not in r]
        if not valid:
            lines.append(f"  {'='*50}")
            lines.append(f"  ⚠️  无法获取任何指数数据，本次不生成综合建议")
            lines.append(f"     请检查网络或稍后重试 `python main.py analyze market`")
            lines.append(f"  {'='*50}")
            return "\n".join(lines)

        # 综合建议
        lines.append(f"  {'='*50}")
        bear_count = sum(1 for r in valid if r.get("trend") == "bear")
        bull_count = sum(1 for r in valid if r.get("trend") == "trending")

        if bear_count >= 2:
            advice = "🛡️ 市场偏弱，建议降低股票仓位，增加债券ETF配置"
        elif bull_count >= 2:
            advice = "🚀 市场偏强，可适当提高仓位，顺势操作"
        else:
            advice = "⚖️ 市场分化，精选个股，控制仓位在半仓以下"

        lines.append(f"  💡 综合建议: {advice}")
        lines.append(f"  {'='*50}")

        return "\n".join(lines)

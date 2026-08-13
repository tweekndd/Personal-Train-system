"""
交易复盘模块
分析交易记录，生成复盘报告
V0.5
"""

from datetime import datetime

import pandas as pd
import numpy as np

from backtest import BacktestEngine, PerformanceReport
from data import DataFetcher
from strategy import TrendStrategy


class TradeReview:
    """交易复盘分析

    对已完成交易进行复盘:
        - 每笔交易的"为什么买/为什么卖"
        - 策略是否有效
        - 改进建议
    """

    def __init__(self):
        self.fetcher = DataFetcher()

    # ── 单股复盘 ──────────────────────────────────────────────

    def review_stock(self, symbol: str) -> dict:
        """对单只股票进行复盘分析

        Args:
            symbol: 股票代码

        Returns:
            {
                "symbol": str,
                "name": str,
                "backtest": PerformanceReport,
                "analysis": str,
            }
        """
        # 取近1年K线
        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(days=365)
        df = self.fetcher.get_daily_kline(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))

        if df.empty:
            return {"symbol": symbol, "error": "无K线数据"}

        # 运行回测
        engine = BacktestEngine(1000)
        strategy = TrendStrategy()
        engine.run(symbol, df, strategy, verbose=False)
        report = PerformanceReport.from_engine(engine)

        # 分析K线形态
        kline_analysis = self._analyze_kline(df)

        return {
            "symbol": symbol,
            "trading_days": len(df),
            "date_range": f"{df.iloc[0]['date']} ~ {df.iloc[-1]['date']}",
            "current_price": float(df.iloc[-1]["close"]),
            "kline_analysis": kline_analysis,
            "backtest_report": report,
            "trades": engine.trade_log(),
            "trade_count": report.total_trades,
        }

    def _analyze_kline(self, df: pd.DataFrame) -> dict:
        """K线形态分析"""
        close = df["close"].values
        if len(close) < 60:
            return {"trend": "数据不足"}

        from strategy.indicators import compute_ma, compute_rsi
        ma20 = compute_ma(df["close"], 20).values
        ma60 = compute_ma(df["close"], 60).values
        rsi_series = compute_rsi(df["close"])
        rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

        # 趋势判断
        recent_return = (close[-1] - close[-60]) / close[-60] * 100
        volatility = pd.Series(close).pct_change().std() * np.sqrt(252) * 100

        if close[-1] > ma20[-1] and ma20[-1] > ma60[-1] and not np.isnan(ma60[-1]):
            trend = "上升趋势 📈"
            suggestion = "趋势向好，可关注回调买入机会"
        elif close[-1] < ma20[-1] and ma20[-1] < ma60[-1] and not np.isnan(ma60[-1]):
            trend = "下降趋势 📉"
            suggestion = "处于下行通道，暂不建议入场"
        else:
            trend = "震荡整理 📊"
            suggestion = "均线交织，等待方向明确"

        return {
            "trend": trend,
            "rsi": round(rsi, 1),
            "60日涨跌幅": f"{recent_return:+.2f}%",
            "年化波动率": f"{volatility:.2f}%",
            "suggestion": suggestion,
        }

    # ── 复盘报告 ──────────────────────────────────────────────

    def report(self, symbol: str) -> str:
        """生成可读的复盘报告"""
        review = self.review_stock(symbol)
        if "error" in review:
            return f"\n❌ {symbol}: {review['error']}\n"

        lines = [
            f"\n{'='*50}",
            f"  📋 交易复盘报告 — {symbol}",
            f"  {'='*50}",
            f"  📅 回测周期: {review['date_range']} ({review['trading_days']}天)",
            f"  💰 当前价格: ¥{review['current_price']:.2f}",
            f"\n  📊 K线分析:",
        ]

        ka = review["kline_analysis"]
        lines.append(f"     {ka['trend']}")
        lines.append(f"     RSI(14): {ka['rsi']}")
        lines.append(f"     60日涨跌幅: {ka['60日涨跌幅']}")
        lines.append(f"     年化波动率: {ka['年化波动率']}")
        lines.append(f"     💡 {ka['suggestion']}")

        report = review["backtest_report"]
        lines.extend(["", report.summary()])

        # AI 分析结论
        lines.extend(["", f"  🤖 AI 分析结论:"])

        total_return = report.total_return
        win_rate = report.win_rate
        max_dd = report.max_drawdown
        total_trades = report.total_trades

        if total_trades == 0:
            conclusion = "回测期内无交易发生：策略信号未触发，或100股整手金额超出单笔/单只资金上限（当前可交易价格约为 ¥1~5 区间）"
        elif total_return > 0 and win_rate > 0.5:
            conclusion = "该策略在回测期内表现良好，建议继续执行"
        elif total_return > 0 and win_rate <= 0.5:
            conclusion = "虽然总体盈利但胜率不高，建议优化止盈止损参数"
        elif total_return <= 0 and max_dd > 0.1:
            conclusion = "当前策略在此标的上表现不佳，建议暂时观望或改用轮动策略"
        else:
            conclusion = "策略表现中性，需更多数据验证"

        lines.append(f"     {conclusion}")
        lines.append(f"  {'='*50}")

        return "\n".join(lines)

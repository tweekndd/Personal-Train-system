"""
策略优化顾问模块
基于历史交易数据给出参数优化建议
V0.5
"""

from loguru import logger

from backtest import BacktestEngine, PerformanceReport
from data import DataFetcher
from strategy import TrendStrategy


class StrategyAdvisor:
    """策略优化顾问

    功能:
        - 参数扫描: 测试不同参数组合的表现
        - 优化建议: 基于回测结果推荐最佳参数
    """

    def __init__(self):
        self.fetcher = DataFetcher()

    # ── 参数扫描 ──────────────────────────────────────────────

    def scan_parameters(self, symbol: str, days: int = 240) -> list[dict]:
        """扫描趋势策略的参数组合

        Args:
            symbol: 股票代码
            days: 回测天数（默认 1 年，足够策略触发）

        Returns:
            [{take_profit, stop_loss, rsi_low, total_return, max_drawdown, win_rate, sharpe}]
        """
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=days)
        df = self.fetcher.get_daily_kline(
            symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df.empty:
            logger.warning(f"无法获取 {symbol} 数据")
            return []

        results = []
        param_sets = []

        for tp in [0.03, 0.05, 0.08, 0.10]:
            for sl in [0.03, 0.05, 0.08]:
                for rsi_low in [30, 40]:
                    param_sets.append({
                        "take_profit": tp,
                        "stop_loss": sl,
                        "rsi_low": rsi_low,
                    })

        logger.info(f"🔬 参数扫描: {len(param_sets)} 组参数")

        for params in param_sets:
            strategy = TrendStrategy(params)
            engine = BacktestEngine(1000)
            engine.run(symbol, df, strategy, verbose=False)
            report = PerformanceReport.from_engine(engine)

            results.append({
                "take_profit": f"{params['take_profit']*100:.0f}%",
                "stop_loss": f"{params['stop_loss']*100:.0f}%",
                "rsi_low": params["rsi_low"],
                "total_return": round(report.total_return * 100, 2),
                "max_drawdown": round(report.max_drawdown * 100, 2),
                "win_rate": round(report.win_rate * 100, 1),
                "trades": report.total_trades,
                "sharpe": round(report.sharpe_ratio, 2),
            })

        return results

    def best_parameters(self, symbol: str) -> dict:
        """寻找最佳参数组合

        评分规则: 总收益率 * 0.4 + 夏普 * 0.3 + 胜率 * 0.2 - 最大回撤 * 0.1
        Returns:
            {"best": dict, "top_5": list[dict], "suggestion": str}
        """
        results = self.scan_parameters(symbol)
        if not results:
            return {"error": "无法获取数据"}

        # 计算综合评分
        max_return = max(abs(r["total_return"]) for r in results) or 1
        max_sharpe = max(abs(r["sharpe"]) for r in results) or 1
        max_win = max(abs(r["win_rate"]) for r in results) or 1
        max_dd = max(abs(r["max_drawdown"]) for r in results) or 1

        for r in results:
            score = (
                (r["total_return"] / max_return) * 0.4
                + (r["sharpe"] / max_sharpe) * 0.3
                + (r["win_rate"] / max_win) * 0.2
                - (r["max_drawdown"] / max_dd) * 0.1
            )
            r["score"] = round(score, 3)

        sorted_results = sorted(results, key=lambda r: r["score"], reverse=True)
        best = sorted_results[0]

        # 全部参数组合都无交易时给出明确提示，避免推荐无意义参数
        all_zero = all(r["trades"] == 0 for r in results)
        if all_zero:
            suggestion = (
                f"⚠️ 所有参数组合均无交易产生。可能原因：策略信号未触发，"
                f"或100股整手金额超出单笔/单只资金上限（当前可交易价格约为 ¥1~5 区间）。"
                f"建议先回测确认可成交，再调整参数。"
            )
        else:
            # 生成建议
            suggestion = (
                f"推荐参数: 止盈 {best['take_profit']}, "
                f"止损 {best['stop_loss']}, "
                f"RSI买入下限 {best['rsi_low']}\n"
                f"预期收益: {best['total_return']:+.2f}% | "
                f"夏普: {best['sharpe']} | "
                f"胜率: {best['win_rate']}%"
            )

        return {
            "symbol": symbol,
            "best": best,
            "top_5": sorted_results[:5],
            "suggestion": suggestion,
        }

    def report(self, symbol: str) -> str:
        """生成可读的优化建议报告"""
        result = self.best_parameters(symbol)
        if "error" in result:
            return f"\n❌ {symbol}: {result['error']}\n"

        lines = [
            f"\n{'='*50}",
            f"  🔧 策略参数优化 — {symbol}",
            f"  {'='*50}",
            f"\n  🏆 最佳参数组合:\n",
            f"     止盈:      {result['best']['take_profit']}",
            f"     止损:      {result['best']['stop_loss']}",
            f"     RSI下限:   {result['best']['rsi_low']}",
            f"     预期收益:  {result['best']['total_return']:+.2f}%",
            f"     最大回撤:  {result['best']['max_drawdown']:.2f}%",
            f"     胜率:      {result['best']['win_rate']}%",
            f"     夏普比率:  {result['best']['sharpe']}",
        ]

        lines.extend(["", f"  📊 Top 5 参数组合:", f"  {'='*40}"])
        lines.append(f"  {'止盈':>6} {'止损':>6} {'RSI':>5} {'收益':>8} {'回撤':>8} {'胜率':>6} {'夏普':>6}")
        for r in result["top_5"]:
            lines.append(
                f"  {r['take_profit']:>6} {r['stop_loss']:>6} "
                f"{r['rsi_low']:>5} {r['total_return']:>+7.2f}% "
                f"{r['max_drawdown']:>7.2f}% {r['win_rate']:>5.1f}% "
                f"{r['sharpe']:>5.2f}"
            )

        lines.extend(["", f"  💡 建议: {result['suggestion']}", f"  {'='*50}"])
        return "\n".join(lines)

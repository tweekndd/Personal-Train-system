"""
Walk-forward 参数优化器
避免过拟合：将数据切分为训练段和验证段
V0.6
"""

import numpy as np
from loguru import logger

from backtest import BacktestEngine, PerformanceReport
from data import DataFetcher
from strategy import TrendStrategy


class WalkForwardOptimizer:
    """Walk-forward 参数优化

    把时间序列切成多段，前段训练、后段验证，
    避免全量数据优化导致的过拟合。
    """

    def __init__(self, n_splits: int = 3):
        self.n_splits = n_splits  # 切分段数

    def optimize(self, symbol: str) -> dict:
        """执行 Walk-forward 优化

        Returns:
            {
                "symbol": str,
                "best_params": dict,
                "validation_results": list,
                "suggestion": str,
            }
        """
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=365)
        df = DataFetcher().get_daily_kline(
            symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df.empty or len(df) < 120:
            return {"symbol": symbol, "error": "数据不足"}

        df = df.sort_values("date").reset_index(drop=True)

        # 参数候选集
        param_grid = []
        for tp in [0.03, 0.05, 0.08]:
            for sl in [0.03, 0.05, 0.08]:
                for rsi_low in [30, 40]:
                    param_grid.append({"take_profit": tp, "stop_loss": sl, "rsi_low": rsi_low})

        # 时间分割点（等分）
        total = len(df)
        split_points = [int(total * (i + 1) / self.n_splits) for i in range(self.n_splits)]

        all_results = []
        for fold in range(self.n_splits - 1):
            # 训练集: 0 ~ split_points[fold]
            train_end = split_points[fold]
            train_df = df.iloc[:train_end]
            # 验证集: split_points[fold] ~ split_points[fold + 1]
            val_start = train_end
            val_end = split_points[fold + 1] if fold + 1 < len(split_points) else total
            val_df = df.iloc[val_start:val_end]

            if len(val_df) < 30:
                continue

            logger.info(f"🔬 Fold {fold+1}: 训练 {train_end}条 → 验证 {len(val_df)}条")

            # 在训练集上找最佳参数
            best_score = -999
            best_params = param_grid[0]

            for params in param_grid:
                strategy = TrendStrategy(params)
                engine = BacktestEngine(1000)
                engine.run(symbol, train_df, strategy, verbose=False)
                report = PerformanceReport.from_engine(engine)
                # 评分：夏普 * 0.5 + 收益/回撤 * 0.5
                score = report.sharpe_ratio * 0.5 + (report.total_return / (report.max_drawdown + 0.01)) * 0.5
                if score > best_score:
                    best_score = score
                    best_params = params

            # 在验证集上验证
            val_strategy = TrendStrategy(best_params)
            val_engine = BacktestEngine(1000)
            val_engine.run(symbol, val_df, val_strategy, verbose=False)
            val_report = PerformanceReport.from_engine(val_engine)

            all_results.append({
                "fold": fold + 1,
                "train_range": f"0~{train_end}",
                "val_range": f"{val_start}~{val_end}",
                "best_params": best_params,
                "val_return": round(val_report.total_return * 100, 2),
                "val_sharpe": round(val_report.sharpe_ratio, 2),
                "val_max_dd": round(val_report.max_drawdown * 100, 2),
            })

        if not all_results:
            return {"symbol": symbol, "error": "分折失败"}

        # 统计各参数出现频率
        from collections import Counter
        param_counts = Counter(
            (r["best_params"]["take_profit"], r["best_params"]["stop_loss"], r["best_params"]["rsi_low"])
            for r in all_results
        )
        most_common = param_counts.most_common(1)[0][0]
        best_params = {"take_profit": most_common[0], "stop_loss": most_common[1], "rsi_low": most_common[2]}

        # 验证集平均表现
        avg_return = np.mean([r["val_return"] for r in all_results])
        avg_sharpe = np.mean([r["val_sharpe"] for r in all_results])

        suggestion = (
            f"推荐参数: 止盈 {best_params['take_profit']*100:.0f}%, "
            f"止损 {best_params['stop_loss']*100:.0f}%, "
            f"RSI下限 {best_params['rsi_low']}\n"
            f"验证集平均收益: {avg_return:+.2f}% | 平均夏普: {avg_sharpe:.2f}"
        )

        return {
            "symbol": symbol,
            "best_params": best_params,
            "validation_results": all_results,
            "avg_validation_return": round(avg_return, 2),
            "avg_validation_sharpe": round(avg_sharpe, 2),
            "suggestion": suggestion,
        }

    def report(self, symbol: str) -> str:
        """生成可读报告"""
        result = self.optimize(symbol)
        if "error" in result:
            return f"\n❌ {symbol}: {result['error']}\n"

        lines = [
            f"\n{'='*50}",
            f"  🔬 Walk-forward 参数优化 — {symbol}",
            f"  {'='*50}",
            f"  分割数: {self.n_splits} 折",
            f"\n  📊 各折结果:\n",
        ]

        for r in result["validation_results"]:
            p = r["best_params"]
            lines.append(
                f"  Fold {r['fold']}: 训练{r['train_range']} → 验证{r['val_range']}\n"
                f"    参数: 止盈{p['take_profit']*100:.0f}% 止损{p['stop_loss']*100:.0f}% RSI下限{p['rsi_low']}\n"
                f"    验证收益: {r['val_return']:+.2f}%  夏普: {r['val_sharpe']}  回撤: {r['val_max_dd']:.1f}%"
            )

        lines.extend([
            "",
            f"  🏆 综合最优参数:",
            f"    止盈: {result['best_params']['take_profit']*100:.0f}%",
            f"    止损: {result['best_params']['stop_loss']*100:.0f}%",
            f"    RSI下限: {result['best_params']['rsi_low']}",
            f"    验证集平均收益: {result['avg_validation_return']:+.2f}%",
            f"    验证集平均夏普: {result['avg_validation_sharpe']:.2f}",
            f"\n  💡 建议: {result['suggestion']}",
            f"  {'='*50}",
        ])

        return "\n".join(lines)

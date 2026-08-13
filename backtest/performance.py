"""
绩效统计模块
计算回测绩效指标
V0.3
"""

import math
from dataclasses import dataclass

import pandas as pd
import numpy as np


@dataclass
class PerformanceReport:
    """回测绩效报告

    指标:
        - 总收益率
        - 年化收益率
        - 最大回撤
        - 胜率
        - 平均盈利 / 平均亏损
        - 盈亏比
        - 总交易次数
        - 夏普比率
    """
    symbol: str = ""
    initial_capital: float = 1000.0
    final_equity: float = 1000.0
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_loss_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    trading_days: int = 0
    total_commission: float = 0.0
    total_tax: float = 0.0

    @classmethod
    def from_engine(cls, engine) -> "PerformanceReport":
        """从回测引擎生成绩效报告"""
        equity_df = engine.equity_df()
        trades = engine.trades
        symbol = getattr(engine, "symbol", None) or (trades[0].symbol if trades else "")

        if equity_df.empty:
            return cls(symbol=symbol)

        # 基础数据
        initial = engine.initial_capital
        final = equity_df.iloc[-1]["total"]
        trading_days = len(equity_df)
        total_return = (final - initial) / initial

        # 年化收益率
        annual_return = 0.0
        if trading_days > 0:
            years = trading_days / 252  # A股年约252个交易日
            if years > 0:
                annual_return = (final / initial) ** (1 / years) - 1

        # 最大回撤
        max_dd = cls._calc_max_drawdown(equity_df["total"].values)

        # 交易统计（FIFO 配对买入卖出，支持多次买卖轮次）
        buy_queue: list = []
        win_count = 0
        loss_count = 0
        wins = []
        losses = []

        for t in trades:
            if t.action == "BUY":
                buy_queue.append(t)
            elif t.action == "SELL" and buy_queue:
                buy = buy_queue.pop(0)  # 先进先出配对
                gross_profit = t.amount - buy.amount
                total_cost = t.commission + t.tax + t.slippage + buy.commission + buy.slippage
                net_pnl = gross_profit - total_cost
                if net_pnl > 0:
                    win_count += 1
                    wins.append(net_pnl)
                else:
                    loss_count += 1
                    losses.append(net_pnl)

        total_trades = win_count + loss_count
        win_rate = win_count / total_trades if total_trades > 0 else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # 夏普比率
        daily_returns = equity_df["total"].pct_change().dropna()
        sharpe = cls._calc_sharpe(daily_returns)

        # 交易成本
        total_commission = sum(t.commission for t in trades)
        total_tax = sum(t.tax for t in trades)

        return cls(
            symbol=symbol,
            initial_capital=initial,
            final_equity=final,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_dd,
            total_trades=total_trades,
            win_trades=win_count,
            loss_trades=loss_count,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_loss_ratio=pl_ratio,
            sharpe_ratio=sharpe,
            trading_days=trading_days,
            total_commission=total_commission,
            total_tax=total_tax,
        )

    # ── 指标计算 ──────────────────────────────────────────────

    @staticmethod
    def _calc_max_drawdown(equity: np.ndarray) -> float:
        """计算最大回撤"""
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        return float(abs(drawdown.min())) if len(drawdown) > 0 else 0.0

    @staticmethod
    def _calc_sharpe(daily_returns: pd.Series, risk_free: float = 0.02) -> float:
        """计算夏普比率（年化）"""
        if daily_returns.empty or daily_returns.std() == 0:
            return 0.0
        excess = daily_returns.mean() * 252 - risk_free
        vol = daily_returns.std() * math.sqrt(252)
        return excess / vol if vol > 0 else 0.0

    # ── 格式化输出 ────────────────────────────────────────────

    def summary(self) -> str:
        """生成可读的绩效摘要"""
        lines = [
            f"\n{'='*50}",
            f"  📊 回测绩效报告 — {self.symbol}",
            f"  {'='*50}",
            f"  ⏱ 回测周期:       {self.trading_days} 个交易日",
            f"  {'='*50}",
            f"  💰 初始资金:       ¥{self.initial_capital:.2f}",
            f"  💰 最终资产:       ¥{self.final_equity:.2f}",
            f"  📈 总收益率:       {self.total_return*100:+.2f}%",
            f"  📈 年化收益率:     {self.annual_return*100:+.2f}%",
            f"  📉 最大回撤:       {self.max_drawdown*100:.2f}%",
            f"  {'='*50}",
            f"  🎯 总交易次数:     {self.total_trades}",
            f"  🏆 胜率:           {self.win_rate*100:.1f}%",
            f"  ✅ 盈利次数:       {self.win_trades}",
            f"  ❌ 亏损次数:       {self.loss_trades}",
            f"  💵 平均盈利:       ¥{self.avg_win:+.2f}",
            f"  💸 平均亏损:       ¥{self.avg_loss:+.2f}",
            f"  ⚖️  盈亏比:         {self.profit_loss_ratio:.2f}",
            f"  📊 夏普比率:       {self.sharpe_ratio:.2f}",
            f"  {'='*50}",
            f"  💳 总手续费:       ¥{self.total_commission:.2f}",
            f"  🏷️  总印花税:       ¥{self.total_tax:.2f}",
            f"  {'='*50}",
        ]
        if self.total_trades == 0:
            lines.insert(
                2,
                "  ⚠️  无交易发生：策略信号未触发，或100股整手金额超出单笔/单只资金上限",
            )
        return "\n".join(lines)

    def brief(self) -> str:
        """一行摘要"""
        arrow = "📈" if self.total_return >= 0 else "📉"
        return (
            f"{arrow} {self.symbol} | "
            f"收益 {self.total_return*100:+.2f}% | "
            f"年化 {self.annual_return*100:+.2f}% | "
            f"回撤 {self.max_drawdown*100:.1f}% | "
            f"胜率 {self.win_rate*100:.0f}% | "
            f"交易 {self.total_trades}次 | "
            f"夏普 {self.sharpe_ratio:.2f}"
        )

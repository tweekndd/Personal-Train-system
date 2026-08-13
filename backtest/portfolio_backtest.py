"""
组合回测引擎
V0.8 — 多标的同时回测 + 沪深300 基准对比

特点:
  1. 同时跟踪 N 只股票，组合层限制最大持仓数
  2. 每只股票复用低风险趋势策略的信号逻辑
  3. 支持与基准指数（沪深300）对比
  4. 接口对齐 BacktestEngine，可直接复用 PerformanceReport
"""

from dataclasses import dataclass, field

import pandas as pd
from loguru import logger

from config import (
    INITIAL_CAPITAL,
    MAX_POSITIONS,
    MAX_PER_POSITION,
    MAX_TRADE_AMOUNT,
    MIN_TRADE_AMOUNT,
    TREND_STRATEGY,
)
from strategy.indicators import (
    compute_ma,
    compute_rsi,
    detect_golden_cross,
    detect_death_cross,
    compute_volume_ratio,
)


@dataclass
class Trade:
    """一笔交易记录"""
    action: str          # BUY / SELL
    symbol: str
    date: str
    price: float
    shares: int
    amount: float
    commission: float
    tax: float
    slippage: float
    total_cost: float
    reason: str = ""


@dataclass
class Position:
    """组合内的单只持仓"""
    symbol: str
    shares: int = 0
    avg_cost: float = 0.0
    total_invested: float = 0.0
    buy_date: str = ""

    def value(self, current_price: float) -> float:
        return self.shares * current_price


class PortfolioBacktest:
    """组合回测引擎

    用法:
        bt = PortfolioBacktest(initial_capital=1000, max_positions=2)
        bt.run({symbol: kline_df, ...}, benchmark_df=hs300_df)
        report = PerformanceReport.from_engine(bt)
    """

    def __init__(self, initial_capital: float = INITIAL_CAPITAL,
                 max_positions: int = MAX_POSITIONS,
                 max_per_position: float = MAX_PER_POSITION,
                 max_trade_amount: float = MAX_TRADE_AMOUNT,
                 min_trade_amount: float = MIN_TRADE_AMOUNT,
                 params: dict = None):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.max_per_position = max_per_position
        self.max_trade_amount = max_trade_amount
        self.min_trade_amount = min_trade_amount
        self.params = dict(TREND_STRATEGY)
        if params:
            self.params.update(params)

        # 状态
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.symbols: list[str] = []
        self.symbol = ""  # PerformanceReport 兼容字段
        self.benchmark_return: float = 0.0
        self.benchmark_curve: list[dict] = []
        self.benchmark_symbol = "沪深300"

        self._precomputed: dict[str, dict] = {}   # symbol -> 预计算指标
        self._calendar: list[str] = []            # 交易日历
        self._bars: dict[str, pd.DataFrame] = {}  # symbol -> df (日期索引)

    def reset(self):
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self.benchmark_return = 0.0
        self.benchmark_curve = []
        self._precomputed = {}
        self._calendar = []
        self._bars = {}

    # ── 交易成本（与 BacktestEngine 保持一致）──────────────

    @property
    def commission_rate(self) -> float:
        return 0.00025

    @property
    def stamp_tax_rate(self) -> float:
        return 0.001

    @property
    def slippage_rate(self) -> float:
        return 0.001

    @property
    def min_commission(self) -> float:
        return 5.0

    # ── 预处理 ──────────────────────────────────────────────

    def _prepare(self, kline_map: dict[str, pd.DataFrame]):
        """预计算每只股票整段指标，并将日期对齐到统一交易日历"""
        self._bars = {}
        self._precomputed = {}
        dates = set()
        for symbol, df in kline_map.items():
            if df is None or df.empty:
                continue
            df = df.sort_values("date").reset_index(drop=True).copy()
            df["date"] = df["date"].astype(str)
            self._bars[symbol] = df
            dates.update(df["date"].tolist())
            self._precompute(symbol, df)
        self._calendar = sorted(dates)
        self.symbols = list(self._bars.keys())
        self.symbol = "组合" + ("(" + ",".join(self.symbols[:3]) + "…)" if len(self.symbols) > 3 else "")

    def _precompute(self, symbol: str, df: pd.DataFrame):
        """预计算整段指标，等价于逐日截断重算（rolling 只用历史）"""
        p = self.params
        close = df["close"]
        ma_short = compute_ma(close, p["ma_short"])
        ma_long = compute_ma(close, p["ma_long"])
        rsi = compute_rsi(close, p["rsi_window"])
        golden = detect_golden_cross(ma_short, ma_long)
        death = detect_death_cross(ma_short, ma_long)
        vol_ratio = compute_volume_ratio(df["volume"], p["ma_short"]) if "volume" in df.columns else pd.Series(1.0, index=df.index)

        idx = {d: i for i, d in enumerate(df["date"].astype(str).tolist())}
        self._precomputed[symbol] = {
            "date_index": idx,
            "ma_short": ma_short.values,
            "ma_long": ma_long.values,
            "rsi": rsi.values,
            "golden_cross": golden.values,
            "death_cross": death.values,
            "volume_ratio": vol_ratio.values,
            "close": df["close"].values,
            "open": df["open"].values if "open" in df.columns else None,
            "volume": df["volume"].values if "volume" in df.columns else None,
        }

    # ── 核心回测 ────────────────────────────────────────────

    def run(self, kline_map: dict[str, pd.DataFrame],
            benchmark_df: pd.DataFrame = None) -> "PortfolioBacktest":
        """运行组合回测

        Args:
            kline_map: {symbol: DataFrame(date, open, high, low, close, volume)}
            benchmark_df: 基准指数K线（沪深300），用于对比

        Returns:
            self
        """
        self.reset()
        if not kline_map:
            logger.warning("组合回测: 无K线数据")
            return self

        self._prepare(kline_map)
        if not self._calendar:
            logger.warning("组合回测: 交易日历为空")
            return self

        logger.info(f"🚀 组合回测 | {len(self.symbols)} 只股票 | "
                    f"{self._calendar[0]} ~ {self._calendar[-1]} | "
                    f"初始资金 ¥{self.initial_capital:.2f} | "
                    f"最大持仓 {self.max_positions}")

        n = len(self._calendar)
        for di, day in enumerate(self._calendar):
            # 1) 先处理卖出（组合先腾仓位再开新仓，且不用当日价格买卖冲突）
            for sym in self.symbols:
                if sym in self.positions and self.positions[sym].shares > 0:
                    self._maybe_sell(sym, day)

            # 2) 再处理买入
            if self._position_count() < self.max_positions:
                for sym in self.symbols:
                    if self._position_count() >= self.max_positions:
                        break
                    if sym in self.positions and self.positions[sym].shares > 0:
                        continue
                    self._maybe_buy(sym, day)

            # 3) 记录净值
            self._record_equity(day)

            if di % 40 == 0:
                logger.debug(f"  进度 {di+1}/{n} ({day})")

        # 最后一天强制平仓
        for sym in self.symbols:
            pos = self.positions.get(sym)
            if pos and pos.shares > 0:
                bars = self._bars[sym]
                last = bars.iloc[-1]
                self._execute_sell(sym, str(last["date"]), float(last["close"]), "回测结束平仓")

        # 基准对比
        if benchmark_df is not None and not benchmark_df.empty:
            self._compute_benchmark(benchmark_df)

        buys = len([t for t in self.trades if t.action == "BUY"])
        logger.info(f"✅ 组合回测完成 | 买入 {buys} 笔 | "
                    f"最终资产 ¥{self.total_equity:.2f} "
                    f"({self.total_return_pct:+.2f}%)")
        return self

    # ── 信号判断（与 TrendStrategy 逻辑一致）───────────────

    def _signal_at(self, symbol: str, date: str) -> dict:
        """返回该日信号 {"action": BUY/SELL/None, "reason": str}"""
        pre = self._precomputed.get(symbol)
        if pre is None:
            return {"action": None, "reason": ""}
        i = pre["date_index"].get(date)
        if i is None or i < 29:  # 至少30条数据（与 TrendStrategy 一致）
            return {"action": None, "reason": "数据不足"}

        p = self.params
        close = pre["close"][i]
        ma_long = pre["ma_long"][i]
        rsi = pre["rsi"][i]

        # ---- 买入检查 ----
        buy_ok = (
            close > ma_long
            and bool(pre["golden_cross"][i])
            and p["rsi_low"] <= rsi <= p["rsi_high"]
            and pre["volume_ratio"][i] >= p["volume_ratio_min"]
        )
        if buy_ok:
            return {"action": "BUY", "reason": "价格站上20MA | 5MA金叉20MA | 量价确认"}

        # ---- 卖出检查（持仓时）----
        pos = self.positions.get(symbol)
        if pos and pos.shares > 0 and pos.avg_cost > 0:
            profit_pct = (close - pos.avg_cost) / pos.avg_cost
            if profit_pct >= p["take_profit"]:
                return {"action": "SELL", "reason": f"止盈 {profit_pct*100:+.1f}%"}
            if profit_pct <= -p["stop_loss"]:
                return {"action": "SELL", "reason": f"止损 {profit_pct*100:.1f}%"}
            if bool(pre["death_cross"][i]):
                return {"action": "SELL", "reason": "死叉信号"}
            if close < ma_long:
                return {"action": "SELL", "reason": "跌破20MA"}

        return {"action": None, "reason": ""}

    def _maybe_buy(self, symbol: str, date: str):
        sig = self._signal_at(symbol, date)
        if sig["action"] != "BUY":
            return
        bars = self._bars[symbol]
        price = float(bars.loc[bars["date"] == date, "close"].iloc[0])
        self._execute_buy(symbol, date, price, sig["reason"])

    def _maybe_sell(self, symbol: str, date: str):
        sig = self._signal_at(symbol, date)
        if sig["action"] != "SELL":
            return
        bars = self._bars[symbol]
        price = float(bars.loc[bars["date"] == date, "close"].iloc[0])
        self._execute_sell(symbol, date, price, sig["reason"])

    # ── 交易执行 ────────────────────────────────────────────

    def _trade_costs(self, amount: float) -> tuple[float, float]:
        commission = max(amount * self.commission_rate, self.min_commission)
        slippage = amount * self.slippage_rate
        return commission, slippage

    def _position_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.shares > 0)

    def _execute_buy(self, symbol: str, date: str, price: float, reason: str = ""):
        if self._position_count() >= self.max_positions:
            return
        pos = self.positions.get(symbol)
        if pos and pos.shares > 0:
            return  # 禁止连续补仓

        target = min(self.max_trade_amount, self.cash,
                     self.max_per_position - (pos.total_invested if pos else 0))
        if target < self.min_trade_amount:
            return

        max_shares = int(target / (price * 100)) * 100
        if max_shares < 100:
            return

        amount = max_shares * price
        commission, slippage = self._trade_costs(amount)
        total_cost = amount + commission + slippage

        while total_cost > self.cash and max_shares >= 100:
            max_shares -= 100
            amount = max_shares * price
            commission, slippage = self._trade_costs(amount)
            total_cost = amount + commission + slippage
        if max_shares < 100:
            return

        self.cash -= total_cost
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        pos = self.positions[symbol]
        pos.total_invested += amount
        pos.shares += max_shares
        pos.avg_cost = pos.total_invested / pos.shares
        pos.buy_date = date

        self.trades.append(Trade(
            action="BUY", symbol=symbol, date=date, price=price,
            shares=max_shares, amount=amount, commission=commission,
            tax=0, slippage=slippage, total_cost=total_cost, reason=reason,
        ))

    def _execute_sell(self, symbol: str, date: str, price: float, reason: str = ""):
        pos = self.positions.get(symbol)
        if not pos or pos.shares == 0:
            return
        if pos.buy_date == date:
            return  # T+1

        shares = pos.shares
        amount = shares * price
        commission, slippage = self._trade_costs(amount)
        tax = amount * self.stamp_tax_rate
        total_cost = commission + tax + slippage

        self.cash += (amount - total_cost)
        pnl = amount - pos.total_invested - total_cost

        self.trades.append(Trade(
            action="SELL", symbol=symbol, date=date, price=price,
            shares=shares, amount=amount, commission=commission,
            tax=tax, slippage=slippage, total_cost=total_cost, reason=reason,
        ))

        pos.shares = 0
        pos.avg_cost = 0
        pos.total_invested = 0

    # ── 净值曲线 ────────────────────────────────────────────

    def _record_equity(self, date: str):
        stock_value = 0.0
        for sym in self.symbols:
            pos = self.positions.get(sym)
            if not pos or pos.shares == 0:
                continue
            bars = self._bars[sym]
            row = bars.loc[bars["date"] == date, "close"]
            if not row.empty:
                stock_value += pos.shares * float(row.iloc[0])
        total = self.cash + stock_value
        self.equity_curve.append({"date": date, "total": round(total, 2)})

    @property
    def total_equity(self) -> float:
        return self.equity_curve[-1]["total"] if self.equity_curve else self.initial_capital

    @property
    def total_return_pct(self) -> float:
        return (self.total_equity - self.initial_capital) / self.initial_capital * 100

    def equity_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.equity_curve)

    def trade_log(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([{
            "日期": t.date, "操作": t.action, "股票": t.symbol,
            "价格": t.price, "数量": t.shares, "金额": round(t.amount, 2),
            "手续费": round(t.commission, 2), "印花税": round(t.tax, 2),
            "滑点": round(t.slippage, 2), "原因": t.reason,
        } for t in self.trades])

    # ── 基准对比 ────────────────────────────────────────────

    def _compute_benchmark(self, benchmark_df: pd.DataFrame):
        """按回测区间对齐沪深300，计算买入持有收益"""
        df = benchmark_df.copy()
        df["date"] = df["date"].astype(str)
        start, end = self._calendar[0], self._calendar[-1]
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        if df.empty:
            return
        df = df.sort_values("date")
        first = float(df.iloc[0]["close"])
        last = float(df.iloc[-1]["close"])
        if first <= 0:
            return
        self.benchmark_symbol = "沪深300"
        self.benchmark_return = (last - first) / first
        self.benchmark_curve = [
            {"date": d, "total": round(last_ * 1000 / first, 2)}
            for d, last_ in zip(df["date"].tolist(), df["close"].tolist())
        ]

    # ── 报告 ────────────────────────────────────────────────

    def report(self) -> str:
        """组合回测报告（含基准对比）"""
        from .performance import PerformanceReport
        perf = PerformanceReport.from_engine(self)

        lines = [
            f"\n{'='*56}",
            f"  🧺 组合回测报告 — {self.symbol}",
            f"  {'='*56}",
            f"  ⏱ 回测区间: {self._calendar[0] if self._calendar else '-'} ~ "
            f"{self._calendar[-1] if self._calendar else '-'}",
            f"  📚 标的池:   {len(self.symbols)} 只 | 最大持仓 {self.max_positions} 只",
            f"  {'='*56}",
            f"  💰 初始资金:       ¥{self.initial_capital:.2f}",
            f"  💰 最终资产:       ¥{self.total_equity:.2f}",
            f"  📈 组合收益:       {perf.total_return*100:+.2f}%",
            f"  📉 组合最大回撤:   {perf.max_drawdown*100:.2f}%",
        ]

        if self.benchmark_curve:
            excess = perf.total_return - self.benchmark_return
            beat = "🎉 跑赢" if excess > 0 else "😔 跑输"
            lines += [
                f"  {'='*56}",
                f"  📊 基准({self.benchmark_symbol})收益:  {self.benchmark_return*100:+.2f}%",
                f"  ⚖️  超额收益:       {excess*100:+.2f}% ({beat})",
            ]

        lines += [
            f"  {'='*56}",
            f"  🎯 成交次数:       {len(self.trades)} 笔 (买 {sum(1 for t in self.trades if t.action == 'BUY')} / 卖 {sum(1 for t in self.trades if t.action == 'SELL')})",
            f"  🏆 胜率(配对):     {perf.win_rate*100:.1f}%",
            f"  📊 夏普比率:       {perf.sharpe_ratio:.2f}",
            f"  {'='*56}",
        ]

        if perf.total_trades == 0:
            lines.insert(3, "  ⚠️  无交易发生：信号未触发，或100股整手金额超出资金上限")

        return "\n".join(lines)

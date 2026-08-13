"""
回测引擎模块
模拟真实交易：买入/卖出、手续费、印花税、滑点
V0.3
"""

from dataclasses import dataclass

import pandas as pd
from loguru import logger

from config import INITIAL_CAPITAL, MAX_PER_POSITION, MAX_TRADE_AMOUNT, MIN_TRADE_AMOUNT
from strategy import TrendStrategy


@dataclass
class Trade:
    """一笔交易记录"""
    action: str          # BUY / SELL
    symbol: str
    date: str
    price: float
    shares: int
    amount: float        # 成交金额
    commission: float    # 手续费
    tax: float           # 印花税
    slippage: float      # 滑点成本
    total_cost: float    # 总成本
    reason: str = ""


@dataclass
class Position:
    """持仓记录"""
    symbol: str
    shares: int = 0
    avg_cost: float = 0.0
    total_invested: float = 0.0
    buy_date: str = ""  # 最后买入日期（用于 T+1 检查）
    
    def value(self, current_price: float) -> float:
        return self.shares * current_price


class BacktestEngine:
    """回测引擎

    功能:
        1. 加载历史K线数据
        2. 按策略信号模拟买卖
        3. 计算交易成本
        4. 输出交易日志和绩效
    """

    def __init__(self, initial_capital: float = INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self.reset()

    def reset(self):
        """重置回测状态"""
        self.cash = self.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []  # 每日资产净值
        self.symbol: str = ""  # 本次回测标的

    # ── 配置参数 ──────────────────────────────────────────────

    @property
    def commission_rate(self) -> float:
        """手续费率 (万2.5)"""
        return 0.00025

    @property
    def stamp_tax_rate(self) -> float:
        """印花税率 (千1，仅卖出)"""
        return 0.001

    @property
    def slippage_rate(self) -> float:
        """滑点 (0.1%)"""
        return 0.001

    @property
    def min_commission(self) -> float:
        """最低手续费 5元"""
        return 5.0

    # ── 核心回测 ──────────────────────────────────────────────

    def run(
        self,
        symbol: str,
        kline_df: pd.DataFrame,
        strategy: TrendStrategy = None,
        verbose: bool = True,
    ) -> "BacktestEngine":
        """运行回测

        Args:
            symbol: 股票代码
            kline_df: 日K线数据 (包含 date, close, open, high, low, volume)
            strategy: 策略实例 (默认 TrendStrategy)
            verbose: 是否打印详细日志

        Returns:
            self (链式调用)
        """
        self.reset()
        if strategy is None:
            strategy = TrendStrategy()

        self.symbol = symbol
        df = kline_df.sort_values("date").reset_index(drop=True)
        if df.empty:
            logger.warning("回测数据为空")
            return self

        logger.info(f"🚀 开始回测 {symbol} | {len(df)} 个交易日 | 初始资金 ¥{self.initial_capital:.2f}")

        strategy.reset()

        for i in range(len(df)):
            row = df.iloc[i]
            current_date = str(row["date"])
            current_price = float(row["close"])

            # 给策略喂数据（需要足够的数据点计算指标）
            if i >= 19:  # 至少需要20条数据算均线
                subset = df.iloc[: i + 1].copy()
                strategy.on_market_data(subset)

                # 如果有持仓，先设持仓价
                pos = self.positions.get(symbol)
                if pos and pos.shares > 0:
                    strategy.set_entry_price(pos.avg_cost)

                signal = strategy.generate_signal()

                if signal:
                    action = signal.get("action")

                    if action == "BUY" and self.cash >= current_price * 100:
                        pos = self.positions.get(symbol, Position(symbol))
                        if pos.shares == 0:  # 禁止连续补仓
                            self._execute_buy(symbol, current_date, current_price, signal.get("reason", ""))

                    elif action == "SELL" and self.positions.get(symbol, Position(symbol)).shares > 0:
                        self._execute_sell(symbol, current_date, current_price, signal.get("reason", ""))

            # 记录每日资产净值
            self._record_equity(current_date, current_price, symbol)

        # 最后一天强制平仓
        if self.positions.get(symbol, Position(symbol)).shares > 0:
            last_row = df.iloc[-1]
            self._execute_sell(symbol, str(last_row["date"]), float(last_row["close"]), "回测结束平仓")

        total_trades = len([t for t in self.trades if t.action == "BUY"])
        logger.info(f"✅ 回测完成 | 交易 {total_trades} 次 | 最终资产 ¥{self.total_equity:.2f}")

        return self

    # ── 交易执行 ──────────────────────────────────────────────

    def _trade_costs(self, amount: float) -> tuple[float, float]:
        """计算手续费 + 滑点"""
        commission = max(amount * self.commission_rate, self.min_commission)
        slippage = amount * self.slippage_rate
        return commission, slippage

    def _execute_buy(self, symbol: str, date: str, price: float, reason: str = ""):
        """执行买入（遵守资金规则：单笔 100~300 元、单只 ≤500 元、禁止补仓）"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        pos = self.positions[symbol]
        if pos.shares > 0:
            return  # 禁止连续补仓

        # 目标金额 = min(单笔上限, 剩余现金, 单只剩余额度)
        target = min(MAX_TRADE_AMOUNT, self.cash, MAX_PER_POSITION - pos.total_invested)
        if target < MIN_TRADE_AMOUNT:
            return  # 达不到单笔最低金额

        # 100股整数倍
        max_shares = int(target / (price * 100)) * 100
        if max_shares < 100:
            return

        amount = max_shares * price
        commission, slippage = self._trade_costs(amount)
        total_cost = amount + commission + slippage

        # 若含成本超出现金，逐手回退（100股为一手）
        while total_cost > self.cash and max_shares >= 100:
            max_shares -= 100
            amount = max_shares * price
            commission, slippage = self._trade_costs(amount)
            total_cost = amount + commission + slippage
        if max_shares < 100:
            return

        self.cash -= total_cost

        # 更新持仓
        pos.total_invested += amount
        pos.shares += max_shares
        pos.avg_cost = pos.total_invested / pos.shares
        pos.buy_date = date  # 记录最后买入日期

        trade = Trade(
            action="BUY", symbol=symbol, date=date,
            price=price, shares=max_shares, amount=amount,
            commission=commission, tax=0, slippage=slippage,
            total_cost=total_cost, reason=reason,
        )
        self.trades.append(trade)

    def _execute_sell(self, symbol: str, date: str, price: float, reason: str = ""):
        """执行卖出（含 T+1 检查）"""
        pos = self.positions.get(symbol)
        if not pos or pos.shares == 0:
            return

        # T+1 检查：当天买入不能卖出
        if pos.buy_date and pos.buy_date == date:
            logger.warning(f"⏭️ T+1: {symbol} 当日买入不能卖出 ({date})")
            return

        shares = pos.shares
        amount = shares * price
        commission, slippage = self._trade_costs(amount)
        tax = amount * self.stamp_tax_rate    # 印花税仅卖出
        total_cost = commission + tax + slippage

        self.cash += (amount - total_cost)

        # 记录盈亏
        pnl = amount - pos.total_invested - total_cost

        trade = Trade(
            action="SELL", symbol=symbol, date=date,
            price=price, shares=shares, amount=amount,
            commission=commission, tax=tax, slippage=slippage,
            total_cost=total_cost, reason=reason,
        )
        self.trades.append(trade)

        # 清空持仓
        pos.shares = 0
        pos.avg_cost = 0
        pos.total_invested = 0

    # ── 净值曲线 ──────────────────────────────────────────────

    def _record_equity(self, date: str, price: float, symbol: str):
        """记录每日资产净值"""
        pos = self.positions.get(symbol, Position(symbol))
        stock_value = pos.value(price)
        total = self.cash + stock_value

        self.equity_curve.append({
            "date": date,
            "cash": round(self.cash, 2),
            "stock_value": round(stock_value, 2),
            "total": round(total, 2),
        })

    @property
    def total_equity(self) -> float:
        """当前总资产"""
        return self.equity_curve[-1]["total"] if self.equity_curve else self.initial_capital

    # ── 交易日志 ──────────────────────────────────────────────

    def trade_log(self) -> pd.DataFrame:
        """获取交易日志"""
        if not self.trades:
            return pd.DataFrame()
        records = []
        for t in self.trades:
            records.append({
                "日期": t.date,
                "操作": t.action,
                "价格": t.price,
                "数量": t.shares,
                "金额": round(t.amount, 2),
                "手续费": round(t.commission, 2),
                "印花税": round(t.tax, 2),
                "滑点": round(t.slippage, 2),
                "原因": t.reason,
            })
        return pd.DataFrame(records)

    def equity_df(self) -> pd.DataFrame:
        """获取净值曲线"""
        return pd.DataFrame(self.equity_curve)

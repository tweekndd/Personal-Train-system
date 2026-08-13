"""
虚拟账户模块
模拟1000元资金账户，管理现金、持仓和盈亏
V0.4
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import os

from loguru import logger


@dataclass
class Position:
    """持仓记录"""
    symbol: str
    shares: int = 0
    avg_cost: float = 0.0
    total_invested: float = 0.0
    buy_date: str = ""  # 最后买入日期（T+1 检查用）

    def market_value(self, price: float) -> float:
        return self.shares * price

    def pnl(self, price: float) -> float:
        """浮动盈亏"""
        return self.market_value(price) - self.total_invested

    def pnl_pct(self, price: float) -> float:
        if self.total_invested == 0:
            return 0.0
        return self.pnl(price) / self.total_invested

    def is_empty(self) -> bool:
        return self.shares == 0


class VirtualAccount:
    """虚拟账户

    模拟真实交易账户:
        - 初始资金 1000元
        - 最大同时持仓 2只
        - 单只最大资金 500元
        - 单次交易 100-300元
        - 禁止满仓单股、连续补仓、追涨
    """

    def __init__(self, initial_capital: float = 1000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self._trade_count = 0
        self._daily_pnl = 0.0
        self._trade_date = ""  # 当前交易日（用于每日重置统计）
        self._state_path = ""  # 持久化路径，由 PaperTrader 设置

    def set_state_path(self, path: str):
        """设置持久化路径"""
        self._state_path = path

    def save(self):
        """保存账户状态到 JSON"""
        if not self._state_path:
            return
        import json
        data = {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "positions": {sym: {"shares": p.shares, "avg_cost": p.avg_cost,
                                "total_invested": p.total_invested, "buy_date": p.buy_date}
                          for sym, p in self.positions.items() if not p.is_empty()},
        }
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        with open(self._state_path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self) -> bool:
        """从 JSON 恢复账户状态"""
        if not self._state_path or not os.path.exists(self._state_path):
            return False
        import json
        with open(self._state_path) as f:
            data = json.load(f)
        self.initial_capital = data.get("initial_capital", self.initial_capital)
        self.cash = data.get("cash", self.initial_capital)
        self.positions.clear()
        for sym, pd in data.get("positions", {}).items():
            self.positions[sym] = Position(
                symbol=sym, shares=pd["shares"],
                avg_cost=pd["avg_cost"],
                total_invested=pd["total_invested"],
                buy_date=pd.get("buy_date", ""),
            )
        return True

    def reset(self):
        """重置账户（新回合）"""
        self.cash = self.initial_capital
        self.positions.clear()
        self._trade_count = 0
        self._daily_pnl = 0.0

    # ── 查询 ──────────────────────────────────────────────────

    def total_equity(self, prices: dict[str, float]) -> float:
        """总资产 = 现金 + 持仓市值"""
        stock_value = sum(
            pos.market_value(prices.get(pos.symbol, 0))
            for pos in self.positions.values()
        )
        return self.cash + stock_value

    def total_pnl(self, prices: dict[str, float]) -> float:
        """总盈亏"""
        return self.total_equity(prices) - self.initial_capital

    def total_pnl_pct(self, prices: dict[str, float]) -> float:
        if self.initial_capital == 0:
            return 0.0
        return self.total_pnl(prices) / self.initial_capital

    def position_count(self) -> int:
        """当前持仓数"""
        return sum(1 for p in self.positions.values() if not p.is_empty())

    def is_position_limit(self, max_positions: int = 2) -> bool:
        """是否已达最大持仓限制"""
        return self.position_count() >= max_positions

    # ── 执行 ──────────────────────────────────────────────────

    def _rollover_day(self):
        """跨日后重置当日交易统计（单日交易笔数 / 当日盈亏）"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._trade_date:
            self._trade_date = today
            self._trade_count = 0
            self._daily_pnl = 0.0

    def can_buy(self, price: float, max_per_trade: float = 500.0, min_per_trade: float = 100.0) -> bool:
        """检查是否满足买入条件"""
        self._rollover_day()
        if self.cash < price * 100:       # 至少买100股
            return False
        if self._trade_count >= 3:         # 单日最多3笔
            return False
        trade_amount = price * 100
        if trade_amount > max_per_trade:   # 不超过单次上限（100股整手）
            return False
        if trade_amount < min_per_trade:   # 不低于单次下限
            return False
        return True

    def buy(self, symbol: str, price: float, shares: int,
            commission: float, slippage: float) -> Optional[dict]:
        """执行买入

        Returns:
            dict: 成交记录 或 None (无法买入)
        """
        self._rollover_day()
        amount = price * shares
        total_cost = amount + commission + slippage

        if total_cost > self.cash:
            logger.warning(f"⛔ 买入失败: 资金不足 (需¥{total_cost:.2f}, 仅¥{self.cash:.2f})")
            return None

        # 更新现金
        self.cash -= total_cost

        # 更新持仓
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]
        new_shares = pos.shares + shares
        pos.total_invested += amount
        pos.avg_cost = pos.total_invested / new_shares if new_shares > 0 else 0
        pos.shares = new_shares
        pos.buy_date = datetime.now().strftime("%Y-%m-%d")  # T+1
        self._trade_count += 1

        trade = {
            "action": "BUY",
            "symbol": symbol,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "price": price,
            "shares": shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "slippage": round(slippage, 2),
            "total_cost": round(total_cost, 2),
            "cash_after": round(self.cash, 2),
        }
        return trade

    def sell(self, symbol: str, price: float, shares: int,
             commission: float, tax: float, slippage: float) -> Optional[dict]:
        """执行卖出

        Returns:
            dict: 成交记录 或 None
        """
        pos = self.positions.get(symbol)
        if not pos or pos.is_empty():
            return None

        # T+1 检查：当日买入不可卖出
        today = datetime.now().strftime("%Y-%m-%d")
        if pos.buy_date and pos.buy_date == today:
            logger.warning(f"⏭️ T+1: {symbol} 当日买入不能卖出 ({today})")
            return None

        self._rollover_day()
        # 只能卖持仓数量
        shares = min(shares, pos.shares)
        amount = price * shares
        total_cost = commission + tax + slippage
        net_received = amount - total_cost

        # 计算盈亏
        sell_value = amount
        buy_cost = (pos.total_invested / pos.shares) * shares if pos.shares > 0 else 0
        trade_pnl = sell_value - buy_cost - total_cost

        # 更新现金
        self.cash += net_received

        # 更新持仓
        pos.shares -= shares
        if pos.shares <= 0:
            pos.shares = 0
            pos.avg_cost = 0.0
            pos.total_invested = 0.0
        else:
            pos.total_invested -= buy_cost

        self._trade_count += 1
        self._daily_pnl += trade_pnl

        trade = {
            "action": "SELL",
            "symbol": symbol,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "price": price,
            "shares": shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "tax": round(tax, 2),
            "slippage": round(slippage, 2),
            "net_received": round(net_received, 2),
            "pnl": round(trade_pnl, 2),
            "cash_after": round(self.cash, 2),
            "pnl_pct": round(trade_pnl / buy_cost * 100, 2) if buy_cost > 0 else 0,
        }
        return trade

    # ── 快照 ──────────────────────────────────────────────────

    def snapshot(self, prices: dict[str, float]) -> dict:
        """生成账户快照"""
        total = self.total_equity(prices)
        positions_detail = []
        for sym, pos in self.positions.items():
            if pos.is_empty():
                continue
            cur_price = prices.get(sym, 0)
            positions_detail.append({
                "symbol": sym,
                "shares": pos.shares,
                "avg_cost": round(pos.avg_cost, 3),
                "current_price": cur_price,
                "market_value": round(pos.market_value(cur_price), 2),
                "pnl": round(pos.pnl(cur_price), 2),
                "pnl_pct": round(pos.pnl_pct(cur_price) * 100, 1),
            })

        return {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "stock_value": round(total - self.cash, 2),
            "total_equity": round(total, 2),
            "total_pnl": round(self.total_pnl(prices), 2),
            "total_pnl_pct": round(self.total_pnl_pct(prices) * 100, 2),
            "position_count": self.position_count(),
            "max_positions": 2,
            "positions": positions_detail,
        }

    def summary(self, prices: dict[str, float]) -> str:
        """格式化账户摘要"""
        snap = self.snapshot(prices)
        pnl_arrow = "📈" if snap["total_pnl"] >= 0 else "📉"

        lines = [
            f"\n{'='*50}",
            f"  💼 虚拟账户",
            f"  {'='*50}",
            f"  💰 初始资金:    ¥{snap['initial_capital']:.2f}",
            f"  💰 当前现金:    ¥{snap['cash']:.2f}",
            f"  📊 持仓市值:    ¥{snap['stock_value']:.2f}",
            f"  {pnl_arrow} 总资产:      ¥{snap['total_equity']:.2f}",
            f"  {pnl_arrow} 总盈亏:      ¥{snap['total_pnl']:+.2f} ({snap['total_pnl_pct']:+.2f}%)",
            f"  📦 持仓数:      {snap['position_count']}/{snap['max_positions']}",
        ]

        if snap["positions"]:
            lines.append(f"  {'='*50}")
            lines.append(f"  持仓明细:")
            for p in snap["positions"]:
                arrow = "📈" if p["pnl"] >= 0 else "📉"
                lines.append(
                    f"    {p['symbol']} | {p['shares']}股 "
                    f"| 成本¥{p['avg_cost']:.3f} | 现价¥{p['current_price']:.2f} "
                    f"| 市值¥{p['market_value']:.2f} "
                    f"| {arrow}{p['pnl_pct']:+.1f}%"
                )

        lines.append(f"  {'='*50}")
        return "\n".join(lines)

    def __repr__(self):
        return f"<VirtualAccount ¥{self.cash:.2f} cash, {self.position_count()} positions>"

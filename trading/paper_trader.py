"""
模拟交易引擎
策略驱动虚拟执行，每日扫描+交易
V0.4
"""

from datetime import datetime
from typing import Optional
import json
import os

from loguru import logger

from config import INITIAL_CAPITAL, MAX_TRADE_AMOUNT, MIN_TRADE_AMOUNT
from data import DataFetcher
from strategy import TrendStrategy
from .virtual_account import VirtualAccount
from .journal import TradeJournal
from .risk_manager import RiskManager


class PaperTrader:
    """模拟交易引擎

    工作流程:
        1. 每日运行策略生成信号
        2. 根据信号执行虚拟买卖
        3. 记录每笔交易到日志
        4. 输出账户状态
    """

    def __init__(self, initial_capital: float = INITIAL_CAPITAL):
        self.account = VirtualAccount(initial_capital)
        self.journal = TradeJournal()
        self.fetcher = DataFetcher()
        self.risk = RiskManager()
        self.equity_history: list[dict] = []  # [{date, equity}] 最近120点
        # 持久化：状态文件放在项目根目录
        state_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")
        self.state_path = os.path.join(state_dir, "paper_account.json")
        self.account.set_state_path(self.state_path)
        self._load_state()  # 恢复上次状态（账户 + 交易日志 + 风控）

    # ── 持久化 ────────────────────────────────────────────────

    def _save_state(self):
        """持久化账户 + 交易日志到单个状态文件"""
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        data = {
            "initial_capital": self.account.initial_capital,
            "cash": self.account.cash,
            "positions": {
                sym: {"shares": p.shares, "avg_cost": p.avg_cost,
                      "total_invested": p.total_invested, "buy_date": p.buy_date}
                for sym, p in self.account.positions.items() if not p.is_empty()
            },
            "journal": self.journal.to_records(),
            "risk": self.risk.to_dict(),
            "equity_history": self.equity_history[-120:],
        }
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_state(self) -> bool:
        """从状态文件恢复账户和交易日志

        兼容旧格式（仅账户、无 journal 字段）的状态文件。
        """
        if not os.path.exists(self.state_path):
            return False
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            self.account.load()
            self.journal.load_records(data.get("journal", []))
            self.risk.load_dict(data.get("risk", {}))
            self.equity_history = list(data.get("equity_history", []))[-120:]
            logger.info(f"✅ 已恢复模拟交易状态: 现金 ¥{self.account.cash:.2f}, "
                        f"持仓 {self.account.position_count()} 只")
            return True
        except Exception as e:
            logger.warning(f"⚠️ 状态文件损坏，以全新账户启动: {e}")
            return False

    # ── 交易成本 ──────────────────────────────────────────────

    @property
    def commission_rate(self) -> float:
        return 0.00025

    @property
    def min_commission(self) -> float:
        return 5.0

    @property
    def stamp_tax_rate(self) -> float:
        return 0.001

    @property
    def slippage_rate(self) -> float:
        return 0.001

    # ── 单股分析执行 ──────────────────────────────────────────

    def analyze_and_trade(self, symbol: str) -> dict:
        """对一只股票运行策略并执行交易

        Returns:
            {
                "symbol": str,
                "signal": dict or None,
                "trade": dict or None,
                "reason": str,
            }
        """
        result = {"symbol": symbol, "signal": None, "trade": None, "reason": ""}

        # 1. 获取K线
        df = self.fetcher.get_daily_kline(symbol)
        if df.empty:
            result["reason"] = "无K线数据"
            return result

        # 2. 运行趋势策略
        strategy = TrendStrategy()
        strategy.on_market_data(df)
        # 若已持仓，注入成本价让策略能生成卖出信号（止盈/止损/跌破均线）
        pos = self.account.positions.get(symbol)
        if pos and not pos.is_empty():
            strategy.set_entry_price(pos.avg_cost)
        signal = strategy.generate_signal()

        if signal is None:
            result["reason"] = "无信号"
            return result

        result["signal"] = signal
        action = signal.get("action")
        price = signal.get("price", 0)
        reason = signal.get("reason", "")

        # 3. 执行交易
        if action == "BUY":
            trade = self._try_buy(symbol, price, reason)
            result["trade"] = trade
            result["reason"] = f"买入 {reason}"

        elif action == "SELL":
            trade = self._try_sell(symbol, price, reason)
            result["trade"] = trade
            result["reason"] = f"卖出 {reason}"

        return result

    def _try_buy(self, symbol: str, price: float, reason: str) -> Optional[dict]:
        """尝试买入"""
        # 禁止补仓：已持有该股票就不再买入
        existing = self.account.positions.get(symbol)
        if existing and not existing.is_empty():
            logger.info(f"⏭️ {symbol}: 已持仓，禁止连续补仓")
            return None

        # 组合级风控：回撤暂停 / 连亏冷却
        allowed, block_reason = self.risk.can_buy()
        if not allowed:
            logger.info(f"⏭️ {symbol}: 风控拦截 — {block_reason}")
            return None

        # 检查持仓限制
        if self.account.is_position_limit():
            logger.info(f"⏭️ {symbol}: 已达最大持仓数，跳过买入")
            return None

        # 市场环境仓位缩放：下跌市/震荡市降低单笔金额
        scale = self.risk.position_scale()
        max_amount = MAX_TRADE_AMOUNT * scale
        min_amount = MIN_TRADE_AMOUNT

        # 买入规则前置检查（现金/单日次数/单笔金额范围）
        if not self.account.can_buy(price, max_per_trade=max_amount,
                                    min_per_trade=min_amount):
            logger.info(f"⏭️ {symbol}: 未满足买入规则（现金不足 / 单日交易次数已满 / 单笔金额超限）")
            return None

        # 计算可买数量 (100股整数倍，金额在 MIN~MAX*scale 之间)
        affordable_shares = int(self.account.cash / (price * 100)) * 100
        amount = affordable_shares * price

        if amount > max_amount:
            # 按上限买
            shares = int(max_amount / (price * 100)) * 100
        else:
            shares = affordable_shares

        if shares < 100:
            logger.info(f"⏭️ {symbol}: 资金不足买100股")
            return None

        amount = shares * price
        commission = max(amount * self.commission_rate, self.min_commission)
        slippage = amount * self.slippage_rate

        trade = self.account.buy(symbol, price, shares, commission, slippage)
        if trade:
            trade["reason"] = reason
            # 记录日志
            entry = self.journal.record(
                action="BUY", symbol=symbol,
                price=price, shares=shares, amount=amount,
                reason=reason, commission=commission, slippage=slippage,
            )
            logger.info(f"📗 模拟买入 {symbol} {shares}股 @ ¥{price:.2f} | {reason}")
            self._save_state()
        return trade

    def _try_sell(self, symbol: str, price: float, reason: str) -> Optional[dict]:
        """尝试卖出"""
        pos = self.account.positions.get(symbol)
        if not pos or pos.is_empty():
            return None

        shares = pos.shares
        amount = shares * price
        commission = max(amount * self.commission_rate, self.min_commission)
        tax = amount * self.stamp_tax_rate
        slippage = amount * self.slippage_rate

        trade = self.account.sell(symbol, price, shares, commission, tax, slippage)
        if trade:
            trade["reason"] = reason
            entry = self.journal.record(
                action="SELL", symbol=symbol,
                price=price, shares=shares, amount=amount,
                reason=reason, commission=commission,
                tax=tax, slippage=slippage, pnl=trade["pnl"],
            )
            logger.info(f"📕 模拟卖出 {symbol} {shares}股 @ ¥{price:.2f} "
                        f"| PnL ¥{trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%) | {reason}")
            # 记录盈亏 → 更新连续亏损冷却
            self.risk.record_trade_result(trade["pnl"])
            self._save_state()
        return trade

    # ── 批量扫描 ──────────────────────────────────────────────

    def scan_and_trade(self, symbols: list[str]) -> list[dict]:
        """扫描多只股票并执行交易"""
        results = []
        for sym in symbols:
            result = self.analyze_and_trade(sym)
            results.append(result)
        return results

    # ── 持仓检查 ──────────────────────────────────────────────

    def check_positions(self) -> int:
        """检查当前持仓是否需要卖出

        Returns:
            int: 实际卖出的笔数
        """
        sold = 0
        for sym, pos in list(self.account.positions.items()):
            if pos.is_empty():
                continue
            # 获取最新价格（K线最新收盘价）
            df = self.fetcher.get_daily_kline(sym)
            if df.empty:
                continue

            latest_price = float(df.iloc[-1]["close"])

            # 上穿20MA? 跌破20MA? 用策略判断
            strategy = TrendStrategy()
            strategy.on_market_data(df)
            strategy.set_entry_price(pos.avg_cost)
            signal = strategy.generate_signal()

            if signal and signal.get("action") == "SELL":
                if self._try_sell(sym, latest_price, signal.get("reason", "持仓止盈/止损")):
                    sold += 1
        return sold

    # ── 完整日交易 ────────────────────────────────────────────

    def daily_run(self, scan_symbols: list[str] = None) -> dict:
        """每日完整运行

        1. 检查现有持仓是否需要卖出
        2. 扫描候选股，执行买入
        3. 输出账户摘要

        Returns:
            {
                "snapshot": 账户快照 dict,
                "buys": 今日买入笔数,
                "sells": 今日卖出笔数,
                "results": 各标的执行结果列表,
            }
        """
        logger.info(f"\n{'='*50}")
        logger.info(f"📋 模拟交易 日运行 — {datetime.now().strftime('%Y-%m-%d')}")
        logger.info(f"{'='*50}")

        # Step 1: 检查持仓
        sells = self.check_positions()

        # Step 2: 扫描新标的
        results: list[dict] = []
        if scan_symbols:
            results = self.scan_and_trade(scan_symbols)

        # Step 3: 获取价格快照
        prices = self._get_current_prices(scan_symbols or [])
        snap = self.account.snapshot(prices)

        # Step 4: 更新风控净值（追踪峰值回撤 / 冷却）+ 记录净值点
        self.risk.update_equity(snap["total_equity"])
        self.record_equity_point(snap["total_equity"])
        self._save_state()

        logger.info(f"📊 日终资产: ¥{snap['total_equity']:.2f} | "
                     f"PnL: ¥{snap['total_pnl']:+.2f} ({snap['total_pnl_pct']:+.2f}%)")
        rsnap = self.risk.snapshot()
        logger.info(f"🛡️ 风控: 市场={rsnap['regime']} "
                     f"| 仓位缩放={rsnap['position_scale']} "
                     f"| 回撤={rsnap['drawdown']}% "
                     f"| 可开仓={rsnap['can_buy']}")
        return {
            "snapshot": snap,
            "buys": sum(1 for r in results if r.get("trade")),
            "sells": sells,
            "results": results,
            "risk": rsnap,
        }

    def record_equity_point(self, equity: float, date: str = None):
        """记录一个净值点（供 Web 仪表盘绘制净值曲线，按天去重）"""
        today = date or datetime.now().strftime("%Y-%m-%d")
        if self.equity_history and self.equity_history[-1].get("date") == today:
            self.equity_history[-1]["equity"] = round(equity, 2)
        else:
            self.equity_history.append({"date": today, "equity": round(equity, 2)})
        # 只保留最近120个点
        self.equity_history = self.equity_history[-120:]

    def _get_current_prices(self, symbols: list[str]) -> dict[str, float]:
        """获取当前价格快照"""
        prices = {}
        for sym in symbols:
            df = self.fetcher.get_daily_kline(sym)
            if not df.empty:
                prices[sym] = float(df.iloc[-1]["close"])
        # 从持仓中补充
        for sym, pos in self.account.positions.items():
            if sym not in prices:
                df = self.fetcher.get_daily_kline(sym)
                if not df.empty:
                    prices[sym] = float(df.iloc[-1]["close"])
        return prices

    def reset(self):
        """重置模拟交易（清零账户和日志，并持久化，避免重启后恢复旧持仓）"""
        self.account.reset()
        self.journal.clear()
        self.risk.reset()
        self.equity_history = []
        self._save_state()
        logger.info("🔄 模拟交易已重置")

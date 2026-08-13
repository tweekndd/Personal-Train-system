"""
组合级风控模块
V0.8 — 在单只止盈/止损之上增加组合层控制

控制项:
  1. 市场环境仓位缩放（上涨满仓 / 震荡七五成 / 下跌半仓）
  2. 组合回撤暂停买入（从净值峰值回撤超阈值停止开新仓）
  3. 连续亏损冷却（连续亏损达到阈值后暂停买入 N 天）
"""

from datetime import datetime, timedelta

from loguru import logger

from config import RISK_MANAGEMENT


class RiskManager:
    """组合级风控

    状态持久化在 paper_account.json 的 "risk" 字段中。
    """

    def __init__(self, params: dict = None):
        self.params = dict(RISK_MANAGEMENT)
        if params:
            self.params.update(params)

        # 市场环境（由外部 MarketAnalyzer 设置）
        self.regime: str = "unknown"

        # 组合状态
        self.peak_equity: float = 0.0
        self.last_equity: float = 0.0
        self.consecutive_losses: int = 0
        self.halted_since: str = ""     # 回撤暂停开始的日期
        self.last_trade_date: str = ""  # 最近一次卖出日期
        self.cooldown_until: str = ""   # 冷却结束日期 (YYYY-MM-DD)
        self.last_run_date: str = ""    # 最近一次运行日期

    # ── 状态序列化 ────────────────────────────────────────────

    def to_dict(self) -> dict:
        """导出为可持久化 dict"""
        return {
            "regime": self.regime,
            "peak_equity": round(self.peak_equity, 2),
            "last_equity": round(self.last_equity, 2),
            "consecutive_losses": self.consecutive_losses,
            "halted_since": self.halted_since,
            "last_trade_date": self.last_trade_date,
            "cooldown_until": self.cooldown_until,
            "last_run_date": self.last_run_date,
        }

    def load_dict(self, data: dict):
        """从持久化 dict 恢复状态"""
        if not data:
            return
        self.regime = data.get("regime", "unknown")
        self.peak_equity = float(data.get("peak_equity", 0.0))
        self.last_equity = float(data.get("last_equity", 0.0))
        self.consecutive_losses = int(data.get("consecutive_losses", 0))
        self.halted_since = data.get("halted_since", "")
        self.last_trade_date = data.get("last_trade_date", "")
        self.cooldown_until = data.get("cooldown_until", "")
        self.last_run_date = data.get("last_run_date", "")

    # ── 对外接口 ──────────────────────────────────────────────

    def set_regime(self, regime: str):
        """设置市场环境（trending/consolidating/bear/unknown）"""
        if regime in self.params["regime_position_scale"]:
            self.regime = regime
        else:
            self.regime = "unknown"

    def position_scale(self) -> float:
        """根据市场环境返回仓位缩放因子 (0~1)"""
        return self.params["regime_position_scale"].get(self.regime, 1.0)

    def update_equity(self, equity: float, run_date: str = None):
        """每次运行后更新净值，追踪峰值并判断是否触发回撤暂停"""
        self.last_equity = round(equity, 2)
        self.last_run_date = run_date or datetime.now().strftime("%Y-%m-%d")
        if equity > self.peak_equity:
            self.peak_equity = round(equity, 2)

        drawdown = self._drawdown()
        limit = self.params["max_drawdown_halt"]

        # 回撤超限 → 触发/维持暂停
        if drawdown >= limit and not self.halted_since:
            self.halted_since = self.last_run_date
            logger.warning(f"🛑 组合回撤 {drawdown*100:.1f}% 超限 "
                           f"({limit*100:.1f}%)，暂停买入")

        # 已暂停：连续 halt_release_days 天回撤收窄到阈值内才解除
        if self.halted_since:
            release_days = self.params["halt_release_days"]
            if drawdown < limit:
                self._recovering_days = getattr(self, "_recovering_days", 0) + 1
                if self._recovering_days >= release_days:
                    logger.info(f"🛡️ 组合回撤 {drawdown*100:.1f}% 已收窄，解除买入暂停")
                    self.halted_since = ""
                    self._recovering_days = 0
            else:
                self._recovering_days = 0

    def _drawdown(self) -> float:
        """当前回撤比例（0~1）"""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.last_equity) / self.peak_equity)

    def record_trade_result(self, pnl: float, trade_date: str = None):
        """记录一笔已平仓交易的结果（用于连续亏损冷却）"""
        today = trade_date or datetime.now().strftime("%Y-%m-%d")
        self.last_trade_date = today
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        limit = self.params["consecutive_loss_limit"]
        if self.consecutive_losses >= limit:
            start = datetime.strptime(today, "%Y-%m-%d")
            cooldown_end = start + timedelta(days=self.params["cooldown_days"])
            self.cooldown_until = cooldown_end.strftime("%Y-%m-%d")
            logger.warning(f"🧊 连续 {self.consecutive_losses} 笔亏损，触发买入冷却 "
                           f"至 {self.cooldown_until}")
        else:
            # 重新评估冷却是否已结束（cooldown_until 当天即可恢复）
            if self.cooldown_until and today >= self.cooldown_until:
                self.cooldown_until = ""

    def can_buy(self, today: str = None) -> tuple[bool, str]:
        """是否允许开新仓

        Returns:
            (允许?, 原因/说明)
        """
        today = today or datetime.now().strftime("%Y-%m-%d")

        # 1. 回撤暂停
        if self.halted_since:
            return False, f"组合回撤 {self._drawdown()*100:.1f}% 超限，暂停买入 (自 {self.halted_since})"

        # 2. 连续亏损冷却
        if self.cooldown_until and today < self.cooldown_until:
            return False, f"连续亏损冷却中 (至 {self.cooldown_until})"

        # 3. 市场环境过弱
        if self.regime == "bear":
            return True, "市场偏弱，半仓防守"

        return True, ""

    def reset(self):
        """重置风控状态"""
        self.regime = "unknown"
        self.peak_equity = 0.0
        self.last_equity = 0.0
        self.consecutive_losses = 0
        self.halted_since = ""
        self.cooldown_until = ""
        self.last_trade_date = ""
        self.last_run_date = ""

    def snapshot(self) -> dict:
        """风控状态快照（供报告/Web仪表盘展示）"""
        allowed, reason = self.can_buy()
        scale = self.position_scale()
        regime_label = {
            "trending": "上涨趋势 📈",
            "consolidating": "震荡市 📊",
            "bear": "下跌市 📉",
            "unknown": "未知",
        }.get(self.regime, self.regime)
        return {
            "regime": self.regime,
            "regime_label": regime_label,
            "position_scale": scale,
            "peak_equity": self.peak_equity,
            "last_equity": self.last_equity,
            "drawdown": round(self._drawdown() * 100, 2),
            "max_drawdown_halt": round(self.params["max_drawdown_halt"] * 100, 1),
            "consecutive_losses": self.consecutive_losses,
            "consecutive_loss_limit": self.params["consecutive_loss_limit"],
            "cooldown_until": self.cooldown_until,
            "halted_since": self.halted_since,
            "can_buy": allowed,
            "can_buy_reason": reason,
        }

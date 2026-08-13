"""
交易日志模块
记录每笔交易的完整决策过程
V0.4
"""

from datetime import datetime

import pandas as pd


class TradeJournal:
    """交易日志

    记录每笔交易的:
        - 时间、操作、股票
        - 价格、数量、金额
        - 手续费、印花税、滑点
        - 交易原因（策略决策过程）
        - 盈亏（卖出时）
    """

    def __init__(self):
        self._entries: list[dict] = []

    def record(
        self,
        action: str,
        symbol: str,
        price: float,
        shares: int,
        amount: float,
        reason: str = "",
        commission: float = 0.0,
        tax: float = 0.0,
        slippage: float = 0.0,
        pnl: float = 0.0,
    ) -> dict:
        """记录一笔交易"""
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "symbol": symbol,
            "price": price,
            "shares": shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "tax": round(tax, 2),
            "slippage": round(slippage, 2),
            "pnl": round(pnl, 2),
            "reason": reason,
        }
        self._entries.append(entry)
        return entry

    def to_dataframe(self) -> pd.DataFrame:
        """导出为 DataFrame"""
        if not self._entries:
            return pd.DataFrame()
        return pd.DataFrame(self._entries)

    def to_records(self) -> list[dict]:
        """导出为可序列化的记录列表（持久化用）"""
        return [dict(e) for e in self._entries]

    def load_records(self, records: list[dict]) -> None:
        """从记录列表恢复（持久化恢复用）"""
        self._entries = [dict(e) for e in (records or [])]

    def recent(self, n: int = 5) -> pd.DataFrame:
        """最近N笔交易"""
        df = self.to_dataframe()
        if df.empty:
            return df
        return df.tail(n)

    def summary(self) -> dict:
        """交易统计"""
        df = self.to_dataframe()
        if df.empty:
            return {"total_trades": 0}

        buys = df[df["action"] == "BUY"]
        sells = df[df["action"] == "SELL"]

        total_pnl = df["pnl"].sum() if "pnl" in df.columns else 0
        total_commission = df["commission"].sum()
        total_tax = df["tax"].sum() if "tax" in df.columns else 0

        return {
            "total_trades": len(df),
            "buys": len(buys),
            "sells": len(sells),
            "total_pnl": round(total_pnl, 2),
            "total_commission": round(total_commission, 2),
            "total_tax": round(total_tax, 2),
        }

    def print(self, n: int = None):
        """打印交易日志"""
        df = self.to_dataframe()
        if df.empty:
            print("\n📋 暂无交易记录\n")
            return

        if n:
            df = df.tail(n)

        cols = ["time", "action", "symbol", "price", "shares", "amount",
                "pnl", "reason"]
        display_cols = [c for c in cols if c in df.columns]

        print(f"\n📋 交易记录 ({len(df)} 笔):")
        print(f"  {'='*60}")
        for _, row in df.iterrows():
            act = row.get("action", "")
            sym = row.get("symbol", "")
            price = row.get("price", 0)
            shares = row.get("shares", 0)
            pnl = row.get("pnl", 0)
            reason = row.get("reason", "")
            if act == "BUY":
                print(f"  📗 {sym} 买入 {shares}股 @ ¥{price:.2f} | {reason}")
            else:
                arrow = "📈" if pnl >= 0 else "📉"
                print(f"  📕 {sym} 卖出 {shares}股 @ ¥{price:.2f} | {arrow}PnL ¥{pnl:+.2f} | {reason}")
        print(f"  {'='*60}")

    def clear(self):
        """清空日志"""
        self._entries.clear()

    def __len__(self):
        return len(self._entries)

"""
每日自动调度
V0.8 — 一键完成: 增量数据同步 → 市场环境 → 风控参数 → 持仓检查 → 扫描交易 → 报告

用法:
  python main.py daily                 # 标准日运行
  python main.py daily --sync          # 运行前先增量同步K线
  python main.py daily -b 创业板 -t 10 # 指定板块 + 扫描数量
"""

from datetime import datetime
from pathlib import Path
import threading

import pandas as pd
from loguru import logger

from config import SCHEDULER
from data import DataFetcher
from database import DatabaseManager
from screen import StockScreener
from trading import PaperTrader
from analysis import MarketAnalyzer


def _call_with_timeout(fn, timeout: int = 30, *args, **kwargs):
    """在超时时间内调用 fn，超时则放弃等待（网络不稳时防止卡死）

    使用守护线程：超时后线程被抛弃，且不阻止进程退出。
    """
    result: dict = {}

    def target():
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            result["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        logger.warning(f"⚠️ {fn.__name__} 超过 {timeout}s 未返回，跳过该步骤")
        return None
    if "error" in result:
        logger.warning(f"⚠️ {fn.__name__} 失败: {result['error']}")
        return None
    return result.get("value")


class DailyScheduler:
    """每日自动运行调度器"""

    def __init__(self):
        self.report_dir = SCHEDULER["report_dir"]
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def run(self, top: int = 10, board: str = None,
            do_sync: bool = False, symbol: str = None) -> dict:
        """执行完整日流程

        Returns:
            {
                "date", "market_regime", "sync", "buys", "sells",
                "snapshot", "risk", "report_path",
            }
        """
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"\n{'='*56}")
        logger.info(f"🔄 每日自动运行 — {today}")
        logger.info(f"{'='*56}")

        db = DatabaseManager()
        fetcher = DataFetcher()
        trader = PaperTrader()

        # ── Step 1: 增量数据同步（可选）─────────────────────
        sync_result = {"total": 0, "synced": 0, "failed": [], "saved": 0}
        if do_sync:
            sync_result = self._sync_universe(fetcher, db, symbol=symbol)

        # ── Step 2: 市场环境判断 ─────────────────────────────
        regime = self._detect_regime()
        trader.risk.set_regime(regime)
        logger.info(f"🌍 市场环境: {regime} "
                    f"→ 仓位缩放 {trader.risk.position_scale()}")

        # ── Step 3: 构建扫描候选池 ──────────────────────────
        scan_symbols = None
        if not symbol:
            scan_symbols = self._build_universe(top=top, board=board,
                                                db=db, trader=trader)
            if not scan_symbols:
                logger.warning("没有可用候选股票，跳过买入扫描")

        # ── Step 4: 日运行（持仓卖出 + 扫描买入）────────────
        result = trader.daily_run(scan_symbols)

        # ── Step 5: 生成每日报告 ─────────────────────────────
        report_path = self._write_report(today, regime, sync_result, result)

        return {
            "date": today,
            "market_regime": regime,
            "sync": sync_result,
            "buys": result["buys"],
            "sells": result["sells"],
            "snapshot": result["snapshot"],
            "risk": result["risk"],
            "report_path": str(report_path),
        }

    # ── 步骤实现 ────────────────────────────────────────────

    def _sync_universe(self, fetcher: DataFetcher, db: DatabaseManager,
                       symbol: str = None) -> dict:
        """构建增量同步工作集并执行

        工作集 = 已有K线的股票（刷新） + 指定 symbol
        受 sync_universe_limit 限制，避免网络不稳时时间过长
        """
        limit = SCHEDULER["sync_universe_limit"]
        lookback = SCHEDULER["sync_lookback_days"]

        universe = db.get_symbols_with_klines(min_bars=20)[:limit]
        if symbol and symbol not in universe:
            universe.append(symbol)

        if not universe:
            logger.info("  [sync] 数据库暂无K线，跳过同步")
            return {"total": 0, "synced": 0, "failed": [], "saved": 0}

        logger.info(f"  [sync] 增量同步 {len(universe)} 只股票 "
                    f"(上限 {limit}，回看 {lookback} 天)...")
        return fetcher.sync_klines(universe, lookback_days=lookback)

    def _detect_regime(self) -> str:
        """判断市场环境，失败时回退 unknown"""
        try:
            analyzer = MarketAnalyzer()
            results = _call_with_timeout(analyzer.full_analysis, timeout=25)
            if not results:
                return "unknown"
            valid = [r for r in results if "error" not in r]
            if not valid:
                logger.warning("  无法获取指数数据，市场环境=unknown")
                return "unknown"
            bear = sum(1 for r in valid if r.get("trend") == "bear")
            bull = sum(1 for r in valid if r.get("trend") == "trending")
            if bear >= 2:
                return "bear"
            if bull >= 2:
                return "trending"
            return "consolidating"
        except Exception as e:
            logger.warning(f"  市场环境判断失败: {e} → unknown")
            return "unknown"

    def _build_universe(self, top: int, board: str, db: DatabaseManager,
                        trader: PaperTrader) -> list[str]:
        """候选池: 优先行情扫描，其次DB已有K线的活跃股"""
        # 1) 行情快照扫描（30s超时，网络不稳时快速回退）
        df = _call_with_timeout(StockScreener().scan_all, timeout=30, board=board)
        if df is not None and not df.empty:
            code_col = StockScreener._find_column(df, ["代码", "code", "symbol"])
            codes = [str(c) for c in df.head(top)[code_col].tolist()]
            if codes:
                return codes
        else:
            logger.warning("  行情扫描失败或超时，回退DB已有K线标的")

        # 2) 回退: DB中已有K线数据的股票
        symbols = db.get_symbols_with_klines(min_bars=20)[:top]
        if symbols:
            logger.info(f"  使用DB已有K线标的作为候选: {symbols}")
        return symbols

    # ── 报告 ────────────────────────────────────────────────

    def _write_report(self, today: str, regime: str, sync_result: dict,
                      result: dict) -> Path:
        """生成每日文本报告"""
        snap = result["snapshot"]
        risk = result["risk"]
        lines = [
            f"MiniQbot-Lite 每日运行报告 — {today}",
            f"{'='*56}",
            f"🌍 市场环境:     {risk['regime_label']} (仓位缩放 {risk['position_scale']})",
            f"🔄 数据同步:     {sync_result['synced']}/{sync_result['total']} 只, "
            f"入库 {sync_result['saved']} 条"
            + (f", 失败 {sync_result['failed']}" if sync_result["failed"] else ""),
            f"{'='*56}",
            f"💼 账户: 现金 ¥{snap['cash']:.2f} | 持仓 ¥{snap['stock_value']:.2f} "
            f"| 总资产 ¥{snap['total_equity']:.2f}",
            f"📈 总盈亏: ¥{snap['total_pnl']:+.2f} ({snap['total_pnl_pct']:+.2f}%)",
            f"📦 持仓: {snap['position_count']}/{snap['max_positions']} 只",
            f"{'='*56}",
            f"🛡️ 风控: 回撤 {risk['drawdown']}% (上限 {risk['max_drawdown_halt']}%) "
            f"| 连亏 {risk['consecutive_losses']}/{risk['consecutive_loss_limit']} "
            f"| 可开仓: {risk['can_buy']}",
            f"📋 今日执行: 买入 {result['buys']} 笔 / 卖出 {result['sells']} 笔",
            f"{'='*56}",
        ]

        if snap["positions"]:
            lines.append("持仓明细:")
            for p in snap["positions"]:
                lines.append(
                    f"  {p['symbol']} {p['shares']}股 | 成本¥{p['avg_cost']:.3f} "
                    f"| 现价¥{p['current_price']:.2f} | 盈亏 {p['pnl_pct']:+.1f}%"
                )
            lines.append(f"{'='*56}")

        path = self.report_dir / f"daily_{today}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"📄 每日报告已生成: {path}")
        return path

    def report(self, date: str = None) -> str:
        """读取某天的报告文本"""
        day = date or datetime.now().strftime("%Y-%m-%d")
        path = self.report_dir / f"daily_{day}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"暂无 {day} 的每日报告 (reports/daily_{day}.txt)"

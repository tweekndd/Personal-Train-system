"""MiniQbot-Lite V0.8 — 增量同步 / 组合风控 / 组合回测 / 调度 单元测试

运行: cd /opt/personal && venv/bin/pytest tests/test_v08.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
import numpy as np


# ── Test: 组合级风控 RiskManager ─────────────────────────────

class TestRiskManager:
    def _make(self, **over):
        from trading.risk_manager import RiskManager
        return RiskManager(params=over)

    def test_position_scale_by_regime(self):
        rm = self._make()
        assert rm.position_scale() == 1.0  # unknown → 满仓
        rm.set_regime("trending")
        assert rm.position_scale() == 1.0
        rm.set_regime("consolidating")
        assert rm.position_scale() == 0.75
        rm.set_regime("bear")
        assert rm.position_scale() == 0.5
        rm.set_regime("boom")  # 非法 regime
        assert rm.regime == "unknown"

    def test_drawdown_halt_and_release(self):
        rm = self._make(max_drawdown_halt=0.10, halt_release_days=2)
        rm.update_equity(1000.0, "2026-01-01")
        assert not rm.halted_since
        # 回撤 10% → 触发暂停
        rm.update_equity(900.0, "2026-01-02")
        assert rm.halted_since == "2026-01-02"
        assert rm.can_buy() == (False, rm.can_buy()[1])
        # 回撤收窄到 5%，需连续 2 天达标才解除
        rm.update_equity(950.0, "2026-01-03")
        assert rm.halted_since, "第1天收窄不应立即解除"
        rm.update_equity(960.0, "2026-01-04")
        assert not rm.halted_since, "连续2天收窄应解除暂停"
        assert rm.can_buy()[0] is True

    def test_consecutive_loss_cooldown(self):
        rm = self._make(consecutive_loss_limit=2, cooldown_days=3)
        rm.record_trade_result(-1.5, "2026-01-05")
        assert rm.consecutive_losses == 1
        assert not rm.cooldown_until
        rm.record_trade_result(-2.0, "2026-01-06")
        assert rm.consecutive_losses == 2
        assert rm.cooldown_until == "2026-01-09"
        # 冷却期内禁买；cooldown_until 当天恢复
        assert rm.can_buy("2026-01-07")[0] is False
        assert rm.can_buy("2026-01-08")[0] is False
        assert rm.can_buy("2026-01-09")[0] is True

    def test_win_resets_loss_streak(self):
        rm = self._make(consecutive_loss_limit=2, cooldown_days=3)
        rm.record_trade_result(-1.0, "2026-01-06")
        rm.record_trade_result(-1.0, "2026-01-07")
        assert rm.cooldown_until  # 冷却触发
        rm.record_trade_result(3.0, "2026-01-08")
        assert rm.consecutive_losses == 0, "盈利应清零连续亏损计数"
        # 冷却为时间约束：到期日当天自动恢复
        assert rm.can_buy("2026-01-08")[0] is False
        assert rm.can_buy("2026-01-10")[0] is True

    def test_serialization_roundtrip(self):
        rm = self._make()
        rm.set_regime("bear")
        rm.update_equity(950.0, "2026-01-02")
        rm.record_trade_result(-1.0, "2026-01-02")
        restored = self._make()
        restored.load_dict(rm.to_dict())
        assert restored.regime == "bear"
        assert restored.peak_equity == pytest.approx(950.0)
        assert restored.consecutive_losses == 1
        assert restored.last_run_date == "2026-01-02"

    def test_snapshot_contains_keys(self):
        rm = self._make()
        rm.set_regime("bear")
        rm.update_equity(1000.0, "2026-01-01")
        snap = rm.snapshot()
        for key in ("regime", "regime_label", "position_scale", "drawdown",
                    "consecutive_losses", "can_buy", "can_buy_reason"):
            assert key in snap
        assert snap["position_scale"] == 0.5


# ── Test: 组合回测 PortfolioBacktest ─────────────────────────

def _u_shape_kline(symbol, n=120, start=4.5, dip=3.9, end=4.4, vol_spike=True):
    """U 型行情：先跌后涨 + 金叉日放量 → 触发买入并止盈"""
    close = np.concatenate([np.linspace(start, dip, n // 2),
                            np.linspace(dip, end, n - n // 2)])
    volume = np.full(n, 1_000_000.0)
    if vol_spike:
        volume[68:76] = 2_500_000.0
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close, "close": close,
        "high": close * 1.01, "low": close * 0.99,
        "volume": volume,
    })


class TestPortfolioBacktest:
    def test_multi_symbol_trades_and_take_profit(self):
        from backtest.portfolio_backtest import PortfolioBacktest
        from backtest.performance import PerformanceReport
        bt = PortfolioBacktest(initial_capital=1000.0, max_positions=2)
        bt.run({"A": _u_shape_kline("A"), "B": _u_shape_kline("B")})
        assert len(bt.symbols) == 2
        buys = [t for t in bt.trades if t.action == "BUY"]
        sells = [t for t in bt.trades if t.action == "SELL"]
        assert len(buys) == 2, f"两只票都应触发买入, 实际 {len(buys)}"
        assert len(sells) >= 1, "上涨后应触发止盈卖出"
        perf = PerformanceReport.from_engine(bt)
        assert perf.total_trades == len(sells), "已完成交易数应按平仓笔数统计"
        assert perf.symbol == bt.symbol

    def test_max_positions_enforced(self):
        from backtest.portfolio_backtest import PortfolioBacktest
        bt = PortfolioBacktest(initial_capital=1000.0, max_positions=1)
        bt.run({"A": _u_shape_kline("A"), "B": _u_shape_kline("B")})
        buys = [t for t in bt.trades if t.action == "BUY"]
        assert len(buys) == 1, "最大持仓1只时只能买入1只"

    def test_expensive_symbol_no_trades(self):
        """¥9 股票 100股=¥900 超出单笔预算 ¥500 → 不成交"""
        from backtest.portfolio_backtest import PortfolioBacktest
        close = np.concatenate([np.linspace(9.0, 8.0, 60), np.linspace(8.0, 9.5, 60)])
        volume = np.full(120, 1_000_000.0)
        volume[68:76] = 2_500_000.0
        dates = pd.date_range("2026-01-01", periods=120, freq="D")
        df = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "open": close,
                           "close": close, "high": close * 1.01, "low": close * 0.99,
                           "volume": volume})
        bt = PortfolioBacktest(initial_capital=1000.0)
        bt.run({"X": df})
        assert len([t for t in bt.trades if t.action == "BUY"]) == 0

    def test_benchmark_compare(self):
        from backtest.portfolio_backtest import PortfolioBacktest
        bt = PortfolioBacktest(initial_capital=1000.0)
        bt.run({"A": _u_shape_kline("A")},
               benchmark_df=_u_shape_kline("IDX", start=3000, dip=2800, end=3100, vol_spike=False))
        assert bt.benchmark_symbol == "沪深300"
        assert bt.benchmark_return != 0.0
        assert len(bt.benchmark_curve) > 0

    def test_empty_kline_map(self):
        from backtest.portfolio_backtest import PortfolioBacktest
        bt = PortfolioBacktest()
        bt.run({})
        assert bt.symbols == []


# ── Test: Web argv 构造 ──────────────────────────────────────

class TestWebArgv:
    def test_sync_flag_appended(self):
        from web.app import _build_argv, RunRequest
        argv = _build_argv({"tokens": ["daily", "-t", "{top}", "{sync}"], "needs_symbol": False},
                           RunRequest(command="daily", top=5, sync=True))
        assert "--sync" in argv
        assert "daily" in argv

    def test_sync_flag_dropped_when_off(self):
        from web.app import _build_argv, RunRequest
        argv = _build_argv({"tokens": ["daily", "-t", "{top}", "{sync}"], "needs_symbol": False},
                           RunRequest(command="daily", top=5, sync=False))
        assert "--sync" not in argv
        assert "" not in argv, "空占位符应被丢弃"

    def test_board_dropped_when_empty(self):
        from web.app import _build_argv, RunRequest
        argv = _build_argv({"tokens": ["scan", "-t", "{top}", "-b", "{board}"], "needs_symbol": False},
                           RunRequest(command="scan", top=10, board=""))
        assert "-b" not in argv


# ── Test: 调度器超时辅助 ─────────────────────────────────────

class TestSchedulerHelpers:
    def test_call_with_timeout_returns_result(self):
        from scheduler import _call_with_timeout
        result = _call_with_timeout(lambda: 42, timeout=5)
        assert result == 42

    def test_call_with_timeout_on_slow_fn(self):
        from scheduler import _call_with_timeout
        import time
        result = _call_with_timeout(lambda: time.sleep(30), timeout=1)
        assert result is None, "超时函数应返回 None 而不是阻塞"

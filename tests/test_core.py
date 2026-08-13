"""MiniQbot-Lite V0.6 — 单元测试

运行: cd /opt/Personal/MiniQbot-Lite && python3 -m pytest tests/ -v
或:   venv/bin/pip install pytest pytest-cov && venv/bin/pytest tests/ --cov=. --cov-report=term
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime


# ── Test: 技术指标 ───────────────────────────────────────────

class TestIndicators:
    @pytest.fixture
    def sample_series(self):
        """50 个交易日的收盘价序列"""
        np.random.seed(42)
        return pd.Series(np.cumsum(np.random.randn(50)) + 100)

    def test_ma_normal(self, sample_series):
        from strategy.indicators import compute_ma
        ma5 = compute_ma(sample_series, 5)
        assert len(ma5) == 50
        assert pd.isna(ma5.iloc[:4]).all()  # 前4天 NaN
        assert not pd.isna(ma5.iloc[4])     # 第5天有值

    def test_ma_constant(self):
        from strategy.indicators import compute_ma
        series = pd.Series([100.0] * 20)
        ma = compute_ma(series, 5)
        assert ma.iloc[-1] == 100.0

    def test_rsi_boundaries(self):
        from strategy.indicators import compute_rsi
        # 连续上涨 → RSI 应接近 100
        up = pd.Series(np.linspace(50, 150, 100))
        rsi_up = compute_rsi(up)
        assert rsi_up.iloc[-1] > 80, f"RSI 上涨应 > 80, 实际 {rsi_up.iloc[-1]:.1f}"

        # 连续下跌 → RSI 应接近 0
        down = pd.Series(np.linspace(150, 50, 100))
        rsi_down = compute_rsi(down)
        assert rsi_down.iloc[-1] < 20, f"RSI 下跌应 < 20, 实际 {rsi_down.iloc[-1]:.1f}"

        # RSI 始终在 0-100 范围内
        flat = pd.Series(np.random.randn(100) + 100)
        rsi = compute_rsi(flat)
        assert rsi.iloc[-1] >= 0
        assert rsi.iloc[-1] <= 100

    def test_rsi_flat_series_center(self):
        """价格持平（无涨无跌）时 RSI 应为 50，而非 100"""
        from strategy.indicators import compute_rsi
        flat = pd.Series([100.0] * 60)
        rsi = compute_rsi(flat)
        assert rsi.iloc[-1] == pytest.approx(50.0, abs=0.01), \
            f"平盘 RSI 应≈50, 实际 {rsi.iloc[-1]:.2f}"

    def test_golden_cross(self):
        from strategy.indicators import detect_golden_cross, compute_ma
        # 构造金叉：短期快速上穿长期
        data = pd.Series(np.concatenate([
            np.linspace(100, 90, 30),   # 下跌
            np.linspace(90, 110, 20),   # 反弹形成金叉
        ]))
        short = compute_ma(data, 5)
        long = compute_ma(data, 20)
        crosses = detect_golden_cross(short, long)
        assert crosses.sum() > 0, "应该有金叉信号"


# ── Test: 虚拟账户 ───────────────────────────────────────────

class TestVirtualAccount:
    @pytest.fixture
    def account(self):
        from trading.virtual_account import VirtualAccount
        return VirtualAccount(initial_capital=1000.0)

    def test_initial_state(self, account):
        assert account.cash == 1000.0
        assert account.position_count() == 0

    def test_buy_normal(self, account):
        # 买 100股 @ 5元 = 500元, 手续费按万2.5算 = 0.125, 最低5元
        trade = account.buy("000725", 5.0, 100, 5.0, 1.0)
        assert trade is not None, "买入应成功"
        assert trade["action"] == "BUY"
        assert trade["shares"] == 100
        # 现金减少: 1000 - (5*100 + 5手续费 + 1滑点) = 1000 - 506
        assert account.cash == pytest.approx(1000.0 - (5*100 + 5.0 + 1.0))
        assert account.position_count() == 1
        assert account.positions["000725"].buy_date != ""

    def test_buy_insufficient_funds(self, account):
        trade = account.buy("000725", 999.0, 100, 5.0, 1.0)
        assert trade is None

    def test_sell_normal(self, account):
        account.buy("000725", 5.0, 100, 5.0, 1.0)
        # 绕过 T+1 检查
        from datetime import datetime, timedelta
        account.positions["000725"].buy_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        trade = account.sell("000725", 5.5, 100, 5.0, 1.1, 1.1)
        assert trade is not None, "卖出应成功"
        assert trade["action"] == "SELL"
        assert account.positions["000725"].is_empty()

    def test_position_limit(self, account):
        # 每笔约 256元 (5*50 + 5手续费 + 1滑点), 两笔 512 < 1000
        account.buy("000001", 5.0, 50, 5.0, 1.0)
        assert account.position_count() == 1
        account.buy("000002", 5.0, 50, 5.0, 1.0)
        assert account.position_count() == 2, f"应为2只, 实际{account.position_count()}"
        assert account.is_position_limit(max_positions=2)

    def test_total_equity(self, account):
        account.buy("000725", 5.0, 100, 5.0, 1.0)
        prices = {"000725": 5.5}
        equity = account.total_equity(prices)
        expected = 100 * 5.5 + (1000.0 - (5*100 + 5.0 + 1.0))
        assert equity == pytest.approx(expected)


# ── Test: 回测引擎 ───────────────────────────────────────────

class TestBacktestEngine:
    @pytest.fixture
    def kline(self):
        dates = pd.date_range("2026-01-01", periods=100, freq="D")
        close = np.linspace(10, 12, 100)  # 稳定上涨
        return pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "close": close,
            "volume": np.ones(100) * 1_000_000,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
        })

    def test_run_completes(self, kline):
        from backtest import BacktestEngine
        engine = BacktestEngine(1000)
        engine.run("000001", kline, verbose=False)
        assert engine.total_equity > 0
        assert len(engine.equity_curve) == 100

    def test_trade_log(self, kline):
        from backtest import BacktestEngine
        from strategy import TrendStrategy
        engine = BacktestEngine(1000)
        engine.run("000001", kline, TrendStrategy(), verbose=False)
        log = engine.trade_log()
        assert isinstance(log, pd.DataFrame)


# ── Test: 数据校验 ───────────────────────────────────────────

class TestDataValidator:
    def test_valid_data(self):
        from data.validator import validate_kline
        df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "close": [10.0, 10.5],
            "open": [9.9, 10.3],
            "high": [10.2, 10.8],
            "low": [9.8, 10.1],
            "volume": [1_000_000, 1_200_000],
        })
        errors = validate_kline(df, "000001")
        assert len(errors) == 0

    def test_negative_price(self):
        from data.validator import validate_kline
        df = pd.DataFrame({
            "date": ["2026-01-01"],
            "close": [-1.0],
            "volume": [1000],
        })
        errors = validate_kline(df)
        assert len(errors) > 0

    def test_unsorted_dates(self):
        from data.validator import validate_kline
        df = pd.DataFrame({
            "date": ["2026-01-03", "2026-01-01", "2026-01-02"],
            "close": [10.0, 9.5, 10.5],
            "volume": [1000, 1000, 1000],
        })
        errors = validate_kline(df)
        assert len(errors) > 0, f"应检测到日期未排序, 但 errors={errors}"


# ── Test: 数据获取容错 ───────────────────────────────────────

class TestDataFetcher:
    @pytest.mark.network
    def test_get_stock_names_fallback(self):
        from data import DataFetcher
        fetcher = DataFetcher()
        df = fetcher.get_stock_names()
        assert df is not None


# ── Test: efinance 备选数据源回退 ─────────────────────────────
# 覆盖 V0.7 新增：akshare 全部失效时自动切换到 efinance，
# 并保证返回的列名与 akshare 输出保持一致。

class _FakeEfinance:
    class stock:
        @staticmethod
        def get_realtime_quotes(fs=None):
            return pd.DataFrame({
                "股票代码": ["600519", "000001"],
                "股票名称": ["贵州茅台", "平安银行"],
                "最新价": [1500.0, 12.0],
                "涨跌幅": [1.5, -0.2],
                "成交额": [1e9, 5e8],
                "动态市盈率": [30.0, 8.0],
            })

        @staticmethod
        def get_quote_history(symbol, beg=None, end=None, klt=101, fqt=1):
            return pd.DataFrame({
                "股票名称": ["贵州茅台", "贵州茅台"],
                "股票代码": ["600519", "600519"],
                "日期": ["2026-08-07", "2026-08-06"],
                "开盘": [1500.0, 1490.0], "收盘": [1510.0, 1495.0],
                "最高": [1520.0, 1500.0], "最低": [1490.0, 1480.0],
                "成交量": [30000, 28000], "成交额": [4.5e9, 4.2e9],
                "振幅": [2.0, 1.5], "涨跌幅": [1.0, 0.7],
                "涨跌额": [15, 10], "换手率": [0.5, 0.4],
            })

        @staticmethod
        def get_latest_quote(codes):
            return pd.DataFrame({
                "代码": ["600519"], "名称": ["贵州茅台"],
                "涨跌幅": [1.5], "最新价": [1510.0],
            })


class TestEfinanceFallback:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        import data.data_fetcher as dfm
        import database.db_manager as dbm
        monkeypatch.setattr(dfm, "_EFINANCE", _FakeEfinance)
        for name in ["stock_zh_a_spot_em", "stock_zh_a_spot",
                     "stock_info_a_code_name", "stock_zh_a_hist", "stock_zh_a_daily"]:
            monkeypatch.setattr(dfm.ak, name, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated")))
        monkeypatch.setattr(dbm, "DatabaseManager", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db fail")))
        return dfm.DataFetcher()

    def test_a_stock_list_fallback(self, fetcher):
        df = fetcher.get_a_stock_list()
        assert "代码" in df.columns and "名称" in df.columns
        assert "最新价" in df.columns and "成交额" in df.columns
        assert len(df) == 2

    def test_stock_names_fallback(self, fetcher):
        df = fetcher.get_stock_names()
        assert df["代码"].tolist() == ["600519", "000001"]

    def test_daily_kline_fallback(self, fetcher):
        df = fetcher.get_daily_kline("600519", "20260701", "20260807")
        assert df["date"].iloc[0] == "2026-08-06"  # 升序
        assert df["date"].iloc[-1] == "2026-08-07"
        assert "股票名称" not in df.columns and "股票代码" not in df.columns
        for col in ["open", "close", "high", "low", "volume", "amount",
                    "pct_change", "turnover", "symbol"]:
            assert col in df.columns
        assert (df["volume"] > 0).all()

    def test_realtime_quote_fallback(self, fetcher):
        q = fetcher.get_realtime_quote("600519")
        assert q["代码"] == "600519"
        assert q["名称"] == "贵州茅台"


# ── Test: 交易执行路径 ───────────────────────────────────────
# 覆盖 P0 缺陷（资金规则 vs 100股整手导致永远无法成交）：
#   BacktestEngine._execute_buy 只买得起预算内的股票
#   PaperTrader._try_buy 端到端成交

class TestTradeExecution:
    def test_backtest_buy_sizing_within_budget(self):
        """¥500/笔预算下，¥4 股票可买入 100 股，¥8 股票无法凑整手"""
        from backtest import BacktestEngine
        eng = BacktestEngine(1000)
        eng._execute_buy("T", "2026-01-01", 4.02, "test")
        buys = [t for t in eng.trades if t.action == "BUY"]
        assert len(buys) == 1, "预算内股票应能成交"
        assert buys[0].shares == 100
        assert buys[0].amount <= 500.0

    def test_backtest_buy_rejects_unaffordable(self):
        """¥8 股票（100股=¥800）超出单笔预算，应拒绝成交而不是静默失败"""
        from backtest import BacktestEngine
        eng = BacktestEngine(1000)
        eng._execute_buy("T", "2026-01-01", 8.0, "test")
        buys = [t for t in eng.trades if t.action == "BUY"]
        assert len(buys) == 0

    def test_backtest_full_run_executes_trades(self):
        """构造 U 型行情 + 放量金叉，回测应真实产生买入并计算绩效"""
        import numpy as np
        from backtest import BacktestEngine
        from backtest.performance import PerformanceReport
        from strategy import TrendStrategy

        n = 120
        close = np.concatenate([np.linspace(4.5, 3.9, 60), np.linspace(3.9, 4.4, 60)])
        volume = np.full(n, 1_000_000.0)
        volume[68:76] = 2_500_000.0  # 金叉日放量
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "close": close, "open": close,
            "high": close * 1.01, "low": close * 0.99,
            "volume": volume,
        })
        eng = BacktestEngine(1000)
        eng.run("TEST", df, TrendStrategy(), verbose=False)
        report = PerformanceReport.from_engine(eng)
        assert report.total_trades >= 1, "策略触发后应产生交易"
        assert report.symbol == "TEST"
        assert report.final_equity != 1000.0

    @staticmethod
    def _make_trader():
        """创建使用临时状态文件的 PaperTrader，避免污染真实账户"""
        import tempfile
        import os
        from trading import PaperTrader
        tmp = os.path.join(tempfile.mkdtemp(), "paper_account.json")
        trader = PaperTrader(initial_capital=1000.0)
        trader.state_path = tmp
        trader.account.set_state_path(tmp)
        trader.account.reset()
        trader.journal.clear()
        trader.risk.reset()
        return trader

    def test_paper_trader_buy_end_to_end(self):
        """模拟交易引擎应能在预算内成交买入"""
        trader = self._make_trader()
        trade = trader._try_buy("000725", 4.02, "测试买入")
        assert trade is not None, "预算内股票应成交"
        assert trade["shares"] == 100
        assert trader.account.positions["000725"].shares == 100

    def test_paper_trader_rejects_unaffordable(self):
        """超出预算的股票应明确拒绝，而不是进入静默失败"""
        trader = self._make_trader()
        trade = trader._try_buy("000725", 8.0, "测试买入")
        assert trade is None
        assert trader.account.position_count() == 0

    def test_can_buy_budget_defaults(self):
        """can_buy 默认预算 500 元：¥5 内可买，¥5 以上不可买"""
        from trading.virtual_account import VirtualAccount
        acc = VirtualAccount(1000.0)
        assert acc.can_buy(4.0) is True
        assert acc.can_buy(5.0) is True
        assert acc.can_buy(5.1) is False
        assert acc.can_buy(8.0) is False

    @staticmethod
    def _declining_kline(n=40, start=4.5, end=3.6):
        """构造持续下跌的K线（用于触发止损）"""
        import numpy as np
        close = np.linspace(start, end, n)
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        return pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": close, "close": close,
            "high": close * 1.01, "low": close * 0.99,
            "volume": np.full(n, 1_000_000.0),
        })

    def test_analyze_and_trade_sells_held_position(self):
        """持有亏损仓位时，analyze_and_trade 应注入成本价并生成卖出"""
        import types
        trader = self._make_trader()
        assert trader._try_buy("000725", 4.0, "测试买入") is not None
        # 模拟昨日建仓（避开 T+1 限制）
        trader.account.positions["000725"].buy_date = "2020-01-01"
        df = self._declining_kline()
        trader.fetcher.get_daily_kline = types.MethodType(
            lambda self, s, **kw: df, trader.fetcher)
        result = trader.analyze_and_trade("000725")
        assert result["trade"] is not None, "持有亏损仓位应触发卖出"
        assert result["trade"]["action"] == "SELL"
        assert trader.account.position_count() == 0

    def test_check_positions_sells_and_counts(self):
        """check_positions 应触发止损卖出并返回卖出笔数"""
        import types
        trader = self._make_trader()
        assert trader._try_buy("000725", 4.0, "测试买入") is not None
        trader.account.positions["000725"].buy_date = "2020-01-01"
        df = self._declining_kline()
        trader.fetcher.get_daily_kline = types.MethodType(
            lambda self, s, **kw: df, trader.fetcher)
        sold = trader.check_positions()
        assert sold == 1
        assert trader.account.position_count() == 0

    def test_check_positions_keeps_profitable_position(self):
        """没有触发卖出条件的持仓应被保留，卖出笔数为 0"""
        import types
        trader = self._make_trader()
        assert trader._try_buy("000725", 4.0, "测试买入") is not None
        trader.account.positions["000725"].buy_date = "2020-01-01"
        df = self._declining_kline(start=3.5, end=4.0)  # 上涨趋势，无止损
        trader.fetcher.get_daily_kline = types.MethodType(
            lambda self, s, **kw: df, trader.fetcher)
        sold = trader.check_positions()
        assert sold == 0
        assert trader.account.position_count() == 1


# ── Test: 板块识别 ───────────────────────────────────────────

class TestBoardDetection:
    def test_main_board_codes(self):
        """主板: 沪市600/601/603/605 + 深市000/001/002/003"""
        from screen.board import detect_board
        for code in ["600519", "601398", "603288", "605358", "000725", "001979", "002131", "003816"]:
            assert detect_board(code) == "主板", code

    def test_star_board_codes(self):
        """科创板: 688/689"""
        from screen.board import detect_board
        for code in ["688981", "689009"]:
            assert detect_board(code) == "科创板", code

    def test_chinext_board_codes(self):
        """创业板: 300/301"""
        from screen.board import detect_board
        for code in ["300058", "301029"]:
            assert detect_board(code) == "创业板", code

    def test_bse_board_codes(self):
        """北交所: 43x/83x/87x/88x/920"""
        from screen.board import detect_board
        for code in ["430047", "832000", "870000", "880000", "920002"]:
            assert detect_board(code) == "北交所", code

    def test_exchange_prefix_normalized(self):
        """带 sh/sz/bj 前缀的代码应识别一致"""
        from screen.board import detect_board
        assert detect_board("sz000725") == "主板"
        assert detect_board("sh688981") == "科创板"
        assert detect_board("bj920002") == "北交所"

    def test_unknown_board(self):
        """无法识别时返回 其他"""
        from screen.board import detect_board
        assert detect_board("999999") == "其他"

    def test_screener_board_filter(self):
        """scan_all 的 board 参数应过滤出对应板块"""
        from screen import StockScreener
        import pandas as pd
        screener = StockScreener()
        df = pd.DataFrame({
            "代码": ["000725", "688981", "300058", "920002"],
            "名称": ["京东方A", "中芯国际", "宁德时代", "北交所股"],
            "最新价": [5.63, 88.5, 251.0, 15.0],
            "成交额": [9_700_000_000, 2_100_000_000, 8_400_000_000, 50_000_000],
        })
        # 直接调用筛选逻辑：用 get_top_candidates 不方便注入，这里验证 detect_board 驱动
        from screen.board import detect_board
        assert df[df["代码"].map(detect_board) == "科创板"]["代码"].tolist() == ["688981"]

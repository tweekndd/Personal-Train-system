#!/usr/bin/env python3
"""
MiniQbot-Lite V0.6
个人低风险AI自动交易系统 - AI辅助分析

功能:
  1. 数据获取（akshare）
  2. 数据库初始化（SQLite）
  3. 股票列表同步
  4. 基础筛选预览
  5. 策略信号生成（趋势策略 + 轮动策略）
  6. 回测系统（历史模拟 + 绩效统计）
  7. 模拟交易（虚拟账户 + 实盘模拟）
  8. AI分析（市场环境 + 交易复盘 + 策略优化）

启动:
  python main.py
"""

import sys
from pathlib import Path

# 确保项目根目录在路径中
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import argparse
from datetime import datetime

import pandas as pd
from loguru import logger

from config import LOG_FILE
from data import DataFetcher
from database import DatabaseManager
from screen import StockScreener
from signals import SignalEngine
from strategy import TrendStrategy, RotationStrategy, ETFRotationStrategy
from backtest import BacktestEngine, PerformanceReport, PortfolioBacktest
from trading import PaperTrader
from analysis import MarketAnalyzer, TradeReview, StrategyAdvisor
from analysis.walk_forward import WalkForwardOptimizer
from analysis.disclaimer import RISK_DISCLAIMER
from data.validator import assert_kline_valid
from scheduler import DailyScheduler


def setup_logger():
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:7}</level> | <cyan>{message}</cyan>",
        level="INFO",
    )
    try:
        logger.add(
            str(LOG_FILE),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level:7} | {message}",
            level="DEBUG",
            rotation="10 MB",
        )
    except PermissionError:
        logger.warning(f"无法写入日志文件 {LOG_FILE}，本次仅输出到控制台")
    logger.info("╔══════════════════════════════════╗")
    logger.info("║   MiniQbot-Lite V0.6 启动        ║")
    logger.info("╚══════════════════════════════════╝")


def print_banner():
    """打印启动横幅"""
    print("""
    ╔══════════════════════════════════════╗
    ║     MiniQbot-Lite  v0.6             ║
    ║     个人低风险AI自动交易系统         ║
    ║     AI分析 · 市场 · 复盘 · 优化     ║
    ╚══════════════════════════════════════╝
    """)


# ── V0.1 命令 ──────────────────────────────────────────────

def cmd_init(args):
    """初始化数据库并同步股票列表"""
    logger.info("🔄 初始化数据库...")
    db = DatabaseManager()
    fetcher = DataFetcher()

    logger.info("🔄 获取股票列表...")
    df = fetcher.get_a_stock_list()
    if df.empty:
        logger.error("获取股票列表失败")
        return

    count = db.save_stock_list(df)
    stats = db.get_stats()
    logger.info(f"✅ 数据库初始化完成: {stats}")

    print(f"\n📊 数据库状态:")
    print(f"  总股票数: {stats['total_stocks']}")
    print(f"  数据路径: {stats['db_path']}")


def cmd_scan(args):
    """扫描并筛选候选股票"""
    logger.info("🔍 开始扫描候选股票...")
    screener = StockScreener()
    df = screener.scan_all(board=args.board)

    if df.empty:
        logger.warning("没有找到符合条件的候选股票")
        return

    top_n = args.top or 10
    top_df = df.head(top_n)
    board_tag = f"｜板块: {args.board}" if args.board else ""
    print(f"\n📊 候选股票 Top {top_n}{board_tag}:\n")

    code_col = "代码"
    name_col = "名称"
    price_col = "最新价"
    pct_col = "涨跌幅"
    amount_col = "成交额"

    for i, (_, row) in enumerate(top_df.iterrows(), 1):
        price = row.get(price_col, "N/A")
        pct = row.get(pct_col, 0)
        amount = row.get(amount_col, 0)
        code = str(row.get(code_col, ""))
        pct_val = float(pct) if pd.notna(pct) else 0.0
        amount_val = float(amount) if pd.notna(amount) else 0.0
        arrow = "📈" if pct_val >= 0 else "📉"
        print(
            f"  {i:2d}. {row.get(name_col, '')}({code})  "
            f"¥{price}  {arrow}{pct}%  "
            f"成交额: ¥{amount_val/1e8:.2f}亿"
        )

    print(f"\n  共筛选出 {len(df)} 只候选股票")


def cmd_fetch(args):
    """获取指定股票的日K线数据并存入数据库"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: --symbol 000001")
        return

    logger.info(f"📥 获取 {symbol} K线数据...")
    fetcher = DataFetcher()
    db = DatabaseManager()

    df = fetcher.get_daily_kline(symbol)
    if df.empty:
        logger.warning(f"未获取到 {symbol} 的数据")
        return

    # 数据质量校验
    assert_kline_valid(df, symbol)

    count = db.save_kline(df)
    logger.info(f"✅ {symbol}: 保存 {count} 条K线记录")

    print(f"\n📈 {symbol} 最近K线:")
    print(df[["date", "open", "close", "high", "low", "volume"]].tail(5).to_string(index=False))


def cmd_status(args):
    """显示系统状态"""
    db = DatabaseManager()
    stats = db.get_stats()
    eng = SignalEngine()
    eng.register_defaults()

    print(f"\n📊 MiniQbot-Lite V0.6 系统状态")
    print(f"  {'='*45}")
    print(f"  数据库:     {Path(stats['db_path']).name}")
    print(f"  股票数量:   {stats['total_stocks']}")
    print(f"  K线记录数:  {stats['total_klines']}")
    print(f"  数据路径:   {stats['db_path']}")
    print(f"  日志路径:   {LOG_FILE}")
    print(f"  {'='*45}")
    print(f"  已加载策略:")
    for s in eng.list_strategies():
        print(f"    ⚙️  {s['name']} ({s['type']})")
    print(f"  {'='*45}")
    print(f"  运行时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def cmd_full_run(args):
    """完整运行：初始化 + 扫描"""
    logger.info("🚀 执行完整流程...")
    db = DatabaseManager()

    fetcher = DataFetcher()
    df_stocks = fetcher.get_a_stock_list()
    if df_stocks.empty:
        logger.error("股票列表获取失败，终止")
        return
    db.save_stock_list(df_stocks)

    screener = StockScreener()
    df_candidates = screener.scan_all()

    print(f"\n{'='*50}")
    print(f"  ✅ V0.2 基础框架运行完成")
    print(f"  {'='*50}")
    print(f"  总股票数:    {len(df_stocks)}")
    print(f"  候选股票数:  {len(df_candidates)}")
    print(f"  数据库:      {db.get_stats()}")
    print(f"  {'='*50}")


# ── V0.2 策略命令 ──────────────────────────────────────────

def cmd_strategy_signal(args):
    """对指定股票运行趋势策略，生成买卖信号"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: -s 000001")
        return

    logger.info(f"📊 分析 {symbol} 趋势信号...")

    # 获取K线数据
    fetcher = DataFetcher()
    df = fetcher.get_daily_kline(symbol)
    if df.empty:
        print(f"\n❌ 无法获取 {symbol} 的K线数据（当前服务器网络限制）")
        print("   建议在本地环境运行此命令")
        return

    print(f"\n📈 {symbol} 技术分析 ({len(df)} 个交易日):\n")

    # 运行趋势策略
    strategy = TrendStrategy()
    strategy.on_market_data(df)

    # 显示最新指标值
    latest = df.iloc[-1]
    ma_short_val = df["close"].rolling(5).mean().iloc[-1]
    ma_long_val = df["close"].rolling(20).mean().iloc[-1]

    rsi = None
    try:
        from strategy.indicators import compute_rsi
        rsi_series = compute_rsi(df["close"])
        rsi = rsi_series.iloc[-1]
    except Exception:
        pass

    print(f"  当前价格:     ¥{latest['close']:.2f}")
    print(f"  5日均线:      ¥{ma_short_val:.2f}  {'📈' if ma_short_val > ma_long_val else '📉'}")
    print(f"  20日均线:     ¥{ma_long_val:.2f}")
    if rsi:
        print(f"  RSI(14):      {rsi:.1f}")
    print(f"  成交量:       {latest.get('volume', 'N/A')}")
    print()

    # 生成信号
    signal = strategy.generate_signal()
    if signal:
        action = signal.get("action", "HOLD")
        reason = signal.get("reason", "")
        if action == "BUY":
            print(f"  🟢 信号: BUY 买入")
        elif action == "SELL":
            print(f"  🔴 信号: SELL 卖出")
        else:
            print(f"  ⚪ 信号: HOLD 持有")
        print(f"  策略: {signal.get('strategy', '')}")
        print(f"  原因: {reason}")
    else:
        print(f"  ⚪ 无明确信号 (HOLD)")

    # 打印最近10个交易日信号历史
    print(f"\n  📋 最近交易日指标:\n")
    df_display = df.tail(10)[["date", "close", "volume"]].copy()
    df_display["close"] = df_display["close"].round(2)
    print(df_display.to_string(index=False))


def cmd_strategy_scan(args):
    """全市场运行策略，输出候选信号"""
    logger.info("🔍 全市场策略扫描...")

    # ETF 模式：运行 ETF 轮动策略
    if args.board == "ETF":
        etf_strategy = ETFRotationStrategy()
        df = etf_strategy.scan()

        if df.empty:
            print("\n❌ 未获取到 ETF 数据（当前服务器网络限制）")
            print("   建议在本地环境运行")
            return

        print(f"\n🏆 {etf_strategy.name} 扫描结果:\n")
        print(etf_strategy.format_candidates(df))
        return

    # 默认模式：运行轮动策略
    rotation = RotationStrategy()
    df = rotation.scan()

    if df.empty:
        print("\n❌ 未获取到市场数据（当前服务器网络限制）")
        print("   建议在本地环境运行")
        return

    print(f"\n🏆 {rotation.name} 扫描结果:\n")
    print(rotation.format_candidates(df))

    # 如果有symbol参数，对指定股运行趋势策略
    if args.symbol:
        print(f"\n{'='*50}")
        print(f"  📊 个股趋势分析: {args.symbol}")
        cmd_strategy_signal(args)


def cmd_strategy_list(args):
    """列出所有可用策略"""
    eng = SignalEngine()
    eng.register_defaults()

    print(f"\n⚙️  已注册策略列表:\n")
    for s in eng.list_strategies():
        print(f"  📌 {s['name']} ({s['type']})")
        print(f"     优先级: {s['priority']}")
        print(f"     参数: {s['params']}")
        print()


def cmd_strategy(args):
    """策略命令分发"""
    sub = args.sub_command or "list"
    sub_map = {
        "signal": cmd_strategy_signal,
        "scan": cmd_strategy_scan,
        "list": cmd_strategy_list,
    }
    fn = sub_map.get(sub)
    if fn:
        fn(args)
    else:
        print(f"未知子命令: {sub}")


# ── V0.3 回测命令 ──────────────────────────────────────────

def cmd_backtest(args):
    """运行回测：对指定股票用历史数据模拟交易"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: -s 000725")
        return

    logger.info(f"📊 开始回测 {symbol}...")

    # 获取K线数据（尽量多）
    fetcher = DataFetcher()
    # 取近1年数据做回测
    from datetime import timedelta
    end = datetime.now()
    start = end - timedelta(days=365)
    df = fetcher.get_daily_kline(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))

    if df.empty:
        print(f"\n❌ 无法获取 {symbol} 的K线数据")
        return

    print(f"\n📈 {symbol} | 加载 {len(df)} 条日K线 | {df.iloc[0]['date']} ~ {df.iloc[-1]['date']}")

    # 运行回测
    engine = BacktestEngine(initial_capital=1000)
    strategy = TrendStrategy()
    engine.run(symbol, df, strategy, verbose=False)

    # 生成绩效报告
    report = PerformanceReport.from_engine(engine)
    print(report.summary())
    print(RISK_DISCLAIMER)

    # 显示交易明细
    log = engine.trade_log()
    if not log.empty:
        print(f"\n  📋 交易明细:")
        print(f"  {'='*50}")
        print(log.to_string(index=False))
        print()


def cmd_backtest_list(args):
    """列出可回测的策略"""
    print(f"\n⚙️  可用的回测策略:\n")
    print(f"  1. {TrendStrategy().name} (trend)")
    print(f"     - 参数: 均线金叉策略, 止盈+5% 止损-5%")
    print(f"  2. 组合回测 (portfolio)")
    print(f"     - 多标的同时回测 + 沪深300基准对比")
    print(f"     - 参数: 最大持仓, 单只资金上限, 交易成本模型")
    print(f"\n使用方法: python main.py backtest -s 000725")
    print(f"          python main.py backtest portfolio [-t 10] [-b 板块]")


def cmd_backtest_portfolio(args):
    """组合回测：多标的 + 基准对比（V0.8）"""
    logger.info("🧺 组合回测: 加载标的K线...")
    db = DatabaseManager()

    # 1) 构建标的池
    if args.symbol:
        symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    else:
        symbols = db.get_symbols_with_klines(min_bars=20)
        if not symbols:
            screener = StockScreener()
            df = screener.scan_all(board=args.board)
            if df.empty:
                print("\n❌ 无K线数据且行情扫描失败，无法组合回测")
                print("   先运行 `python main.py daily --sync` 或 `python main.py fetch -s 000725`")
                return
            code_col = StockScreener._find_column(df, ["代码", "code", "symbol"])
            symbols = [str(c) for c in df.head(args.top)[code_col].tolist()]
        symbols = symbols[:args.top]

    if not symbols:
        print("\n❌ 没有可回测的标的")
        return

    # 2) 从DB加载K线
    kline_map = {}
    for sym in symbols:
        df = db.get_klines(sym)
        if df is not None and len(df) >= 30:
            kline_map[sym] = df
        else:
            logger.warning(f"  跳过 {sym}: K线不足 ({len(df)}条)")

    if not kline_map:
        print("\n❌ 所有标的K线均不足30条，无法回测")
        print("   先运行 `python main.py daily --sync` 拉取更多数据")
        return

    # 3) 基准：沪深300（尽力获取，失败不影响回测）
    benchmark_df = None
    try:
        fetcher = DataFetcher()
        benchmark_df = fetcher.get_index_kline("000300")
        if benchmark_df is None or benchmark_df.empty:
            logger.warning("沪深300数据获取失败，本次不进行基准对比")
    except Exception as e:
        logger.warning(f"基准获取失败: {e}")

    # 4) 运行
    bt = PortfolioBacktest(initial_capital=1000, max_positions=args.top_positions or 2)
    bt.run(kline_map, benchmark_df=benchmark_df)
    print(bt.report())
    print(RISK_DISCLAIMER)

    log = bt.trade_log()
    if not log.empty:
        print(f"\n  📋 交易明细:")
        print(f"  {'='*50}")
        print(log.to_string(index=False))
        print()


# ── V0.4 模拟交易命令 ───────────────────────────────────────

def cmd_trade(args):
    """模拟交易：运行策略并执行虚拟买卖"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: -s 000725")
        return

    logger.info(f"💼 模拟交易: {symbol}")
    trader = PaperTrader()
    result = trader.analyze_and_trade(symbol)

    print(f"\n{'='*50}")
    print(f"  💼 模拟交易执行结果 — {symbol}")
    print(f"  {'='*50}")

    if result.get("signal") is None:
        print(f"\n  ⚪ 无交易信号 (HOLD)")
    else:
        signal = result["signal"]
        action = signal.get("action")
        reason = signal.get("reason", "")
        if action == "BUY":
            print(f"\n  🟢 信号: BUY — {reason}")
        elif action == "SELL":
            print(f"\n  🔴 信号: SELL — {reason}")

    if result.get("trade"):
        t = result["trade"]
        print(f"\n  ✅ 已执行: {t.get('action')} {t.get('shares')}股 @ ¥{t.get('price'):.2f}")
    else:
        print(f"\n  ⏭️  未执行: {result.get('reason', '条件不满足')}")

    # 显示账户状态
    prices = {}
    df = trader.fetcher.get_daily_kline(symbol)
    if not df.empty:
        prices[symbol] = float(df.iloc[-1]["close"])
    print(trader.account.summary(prices))


def cmd_trade_status(args):
    """查看虚拟账户状态"""
    trader = PaperTrader()
    prices = {}
    for sym in list(trader.account.positions.keys()):
        df = trader.fetcher.get_daily_kline(sym)
        if not df.empty:
            prices[sym] = float(df.iloc[-1]["close"])

    print(trader.account.summary(prices))
    trader.journal.print(n=10)


def cmd_trade_reset(args):
    """重置模拟交易"""
    trader = PaperTrader()
    trader.reset()
    print("\n🔄 模拟交易已重置，账户已归零\n")


def cmd_trade_run(args):
    """模拟交易完整日运行：先检查持仓卖出，再扫描候选买入"""
    trader = PaperTrader()

    print(f"\n{'='*50}")
    print(f"  💼 模拟交易 日运行 — {datetime.now().strftime('%Y-%m-%d')}")
    print(f"  {'='*50}")

    # Step 1: 检查现有持仓是否需要卖出
    sells = trader.check_positions()
    print(f"\n  🔍 持仓检查: 卖出 {sells} 笔")

    # Step 2: 扫描候选买入
    if args.symbol:
        symbols = [args.symbol]
    else:
        screener = StockScreener()
        df = screener.scan_all(board=args.board)
        if df.empty:
            logger.warning("没有找到候选股票，跳过买入")
            symbols = []
        else:
            top_n = args.top or 10
            code_col = StockScreener._find_column(df, ["代码", "code", "symbol"])
            symbols = [str(c) for c in df.head(top_n)[code_col].tolist()]
            board_tag = f"（板块: {args.board}）" if args.board else ""
            print(f"  📊 扫描候选 Top {top_n}{board_tag}: {'、'.join(symbols)}")

    buys = 0
    if symbols:
        results = trader.scan_and_trade(symbols)
        buys = sum(1 for r in results if r.get("trade"))
        for r in results:
            if r.get("trade"):
                t = r["trade"]
                print(f"    ✅ {t['action']} {t['symbol']} {t['shares']}股 @ ¥{t['price']:.2f}")
            elif r.get("signal"):
                sig = r["signal"]
                print(f"    ⏭️  {r['symbol']}: 信号 {sig.get('action')} 未执行 — {r.get('reason', '条件不满足')}")
            else:
                print(f"    ⏭️  {r['symbol']}: {r.get('reason', '无信号 (HOLD)')}")

    # Step 3: 账户摘要
    prices = trader._get_current_prices(symbols or [])
    print(trader.account.summary(prices))
    print(f"\n  📋 今日执行: 买入 {buys} 笔 / 卖出 {sells} 笔")

    # 风控摘要
    rsnap = trader.risk.snapshot()
    print(f"  🛡️ 风控: 市场={rsnap['regime']} | 仓位缩放={rsnap['position_scale']} "
          f"| 回撤={rsnap['drawdown']}% | 可开仓={rsnap['can_buy']}")

    trader.journal.print(n=10)


# ── V0.8 每日调度命令 ────────────────────────────────────────

def cmd_daily(args):
    """每日自动运行：增量同步 → 市场环境 → 风控 → 持仓检查 → 扫描买入 → 报告"""
    scheduler = DailyScheduler()

    print(f"\n{'='*56}")
    print(f"  📅 MiniQbot-Lite 每日自动运行 — {datetime.now().strftime('%Y-%m-%d')}")
    print(f"  {'='*56}")

    summary = scheduler.run(
        top=args.top or 10,
        board=args.board,
        do_sync=bool(args.sync),
        symbol=args.symbol,
    )

    snap = summary["snapshot"]
    risk = summary["risk"]
    print(f"\n  🌍 市场环境:  {risk['regime_label']} (仓位缩放 {risk['position_scale']})")
    if args.sync:
        sync = summary["sync"]
        print(f"  🔄 数据同步:  {sync['synced']}/{sync['total']} 只成功, 入库 {sync['saved']} 条"
              + (f" | 失败: {sync['failed']}" if sync["failed"] else ""))
    print(f"  💼 总资产:    ¥{snap['total_equity']:.2f} "
          f"({snap['total_pnl']:+.2f} / {snap['total_pnl_pct']:+.2f}%)")
    print(f"  📋 今日执行:  买入 {summary['buys']} 笔 / 卖出 {summary['sells']} 笔")
    print(f"  🛡️ 风控:      回撤 {risk['drawdown']}% | 连亏 {risk['consecutive_losses']} "
          f"| 可开仓: {risk['can_buy']}")
    print(f"  📄 报告:      {summary['report_path']}")
    print(f"  {'='*56}")

    if args.show_report:
        print(scheduler.report(summary["date"]))


# ── V0.6 AI分析命令 ─────────────────────────────────────────

def cmd_analyze(args):
    """AI智能分析"""
    cmd = args.sub_command or "market"
    if cmd == "market":
        _analyze_market(args)
    elif cmd == "review":
        _analyze_review(args)
    elif cmd == "optimize":
        _analyze_optimize(args)
    elif cmd == "wfo":
        _analyze_wfo(args)
    else:
        print(f"未知分析命令: {cmd}")
        print("可用: market, review -s 000725, optimize -s 000725, wfo -s 000725")


def _analyze_market(args):
    """市场环境分析"""
    logger.info("🌍 分析市场环境...")
    analyzer = MarketAnalyzer()
    print(analyzer.summary())


def _analyze_review(args):
    """交易复盘"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: -s 000725")
        return
    logger.info(f"📋 复盘分析: {symbol}")
    reviewer = TradeReview()
    print(reviewer.report(symbol))
    print(RISK_DISCLAIMER)


def _analyze_optimize(args):
    """策略参数优化"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: -s 000725")
        return
    logger.info(f"🔧 参数优化: {symbol}")
    advisor = StrategyAdvisor()
    print(advisor.report(symbol))
    print(RISK_DISCLAIMER)


def _analyze_wfo(args):
    """Walk-forward 参数优化（避免过拟合）"""
    symbol = args.symbol
    if not symbol:
        logger.error("请指定股票代码, 如: -s 000725")
        return
    logger.info(f"🔬 Walk-forward 优化: {symbol}")
    optimizer = WalkForwardOptimizer(n_splits=3)
    print(optimizer.report(symbol))


def main():
    """主入口"""
    setup_logger()

    parser = argparse.ArgumentParser(
        description="MiniQbot-Lite V0.6 - 个人低风险量化交易助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
基础命令:
  python main.py init                     # 初始化数据库 + 同步股票列表
  python main.py scan -t 10               # 扫描候选股票
  python main.py scan -b 创业板 -t 10     # 按板块扫描（主板/科创板/创业板/北交所）
  python main.py scan -b ETF -t 10        # 扫描 ETF
  python main.py fetch -s 000001          # 获取个股K线
  python main.py status                   # 系统状态
  python main.py run                      # 完整运行

策略命令 (V0.2):
  python main.py strategy signal -s 000001   # 个股趋势信号
  python main.py strategy scan               # 全市场轮动扫描
  python main.py strategy scan -s 000001     # 轮动扫描 + 个股分析
  python main.py strategy scan -b ETF        # ETF 轮动扫描
  python main.py strategy list               # 列出所有策略

回测命令 (V0.3):
  python main.py backtest -s 000725          # 回测指定股票
  python main.py backtest list               # 查看可回测的策略
  python main.py backtest portfolio -t 10    # 组合回测 + 沪深300基准对比 (V0.8)

模拟交易 (V0.4):
  python main.py trade -s 000725             # 模拟买入/卖出（单只）
  python main.py trade run -t 10             # 完整日运行（持仓卖出 + 扫描买入）
  python main.py trade run -b 创业板 -t 10   # 指定板块日运行
  python main.py trade status                # 查看账户和持仓
  python main.py trade reset                 # 重置虚拟账户

每日调度 (V0.8):
  python main.py daily                       # 每日自动运行（市场环境→风控→交易）
  python main.py daily --sync                # 先增量同步K线再运行
  python main.py daily -b 科创板 -t 10       # 指定板块
  python main.py daily --show-report         # 运行后打印完整报告
  # crontab: 10 15 * * 1-5 scripts/cron_daily.sh --sync
        """,
    )
    parser.add_argument("command", nargs="?", default="status", help="init | scan | fetch | status | run | strategy | backtest | trade | analyze | daily")
    parser.add_argument("sub_command", nargs="?", help="strategy: signal|scan|list | backtest: list|portfolio | trade: status|reset|run | analyze: market|review|optimize")
    parser.add_argument("-s", "--symbol", help="股票代码（多个用逗号分隔，如 000725,000001）")
    parser.add_argument("-t", "--top", type=int, default=10, help="显示前N只")
    parser.add_argument("-b", "--board", choices=["主板", "科创板", "创业板", "北交所", "ETF"],
                        help="按类型过滤: 主板/科创板/创业板/北交所/ETF")
    parser.add_argument("-p", "--positions", dest="top_positions", type=int, default=2,
                        help="组合回测最大持仓数 (默认2)")
    parser.add_argument("--sync", action="store_true", help="daily: 运行前增量同步K线")
    parser.add_argument("--show-report", action="store_true", help="daily: 运行后打印完整报告")

    args = parser.parse_args()

    print_banner()

    cmd_map = {
        "init": cmd_init,
        "scan": cmd_scan,
        "fetch": cmd_fetch,
        "status": cmd_status,
        "run": cmd_full_run,
        "strategy": cmd_strategy,
        "backtest": cmd_backtest,
        "trade": cmd_trade,
        "analyze": cmd_analyze,
        "daily": cmd_daily,
    }

    cmd_func = cmd_map.get(args.command)
    if cmd_func:
        # 子命令分发
        if args.command == "trade" and args.sub_command:
            sub_map = {
                "status": cmd_trade_status,
                "reset": cmd_trade_reset,
                "run": cmd_trade_run,
            }
            fn = sub_map.get(args.sub_command)
            if fn:
                fn(args)
                return
            else:
                print(f"未知 trade 子命令: {args.sub_command}")
                print("可用: status, reset, run")
                return
        if args.command == "backtest" and args.sub_command == "list":
            cmd_backtest_list(args)
            return
        if args.command == "backtest" and args.sub_command == "portfolio":
            cmd_backtest_portfolio(args)
            return
        cmd_func(args)
    else:
        print(f"未知命令: {args.command}")
        print("可用命令: init, scan, fetch, status, run, strategy, backtest, trade, analyze, daily")
        parser.print_help()


if __name__ == "__main__":
    main()

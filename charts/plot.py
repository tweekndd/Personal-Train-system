"""
K线可视化
使用 mplfinance 生成带买卖点标记的 K 线图
V0.6
"""

import os
from datetime import datetime

import pandas as pd
from loguru import logger

# 图表输出目录（项目根目录 / charts，.gitignore 已排除 *.png）
CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts")


def plot_kline_with_signals(
    kline_df: pd.DataFrame,
    symbol: str = "",
    trades: list[dict] = None,
    title: str = None,
    save: bool = True,
) -> str:
    """绘制K线图 + 买卖点标记

    Args:
        kline_df: K线数据 (需含 date, open, close, high, low, volume)
        symbol: 股票代码
        trades: 交易记录列表 [{"action": "BUY", "date": "...", "price": ...}, ...]
        title: 图表标题
        save: 是否保存文件

    Returns:
        str: 图片文件路径（save=True时）
    """
    try:
        import mplfinance as mpf
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("请安装 mplfinance: pip install mplfinance")
        return ""

    # 准备数据
    df = kline_df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            logger.error(f"缺少必要列: {col}")
            return ""

    df = df[required].dropna()

    # 构造买卖点标记
    buy_dates, buy_prices = [], []
    sell_dates, sell_prices = [], []
    if trades:
        for t in trades:
            try:
                d = pd.to_datetime(t.get("date", ""))
                p = float(t.get("price", 0))
                if t.get("action") == "BUY":
                    buy_dates.append(d)
                    buy_prices.append(p)
                elif t.get("action") == "SELL":
                    sell_dates.append(d)
                    sell_prices.append(p)
            except (ValueError, TypeError):
                continue

    # 创建买卖点 Series
    apds = []
    if buy_dates:
        buy_series = pd.Series(buy_prices, index=buy_dates, dtype=float)
        # 只保留在 df 索引范围内的点
        buy_series = buy_series[buy_series.index.isin(df.index)]
        if not buy_series.empty:
            apds.append(mpf.make_addplot(buy_series, type="scatter",
                         markersize=120, marker="^", color="green",
                         label="BUY"))

    if sell_dates:
        sell_series = pd.Series(sell_prices, index=sell_dates, dtype=float)
        sell_series = sell_series[sell_series.index.isin(df.index)]
        if not sell_series.empty:
            apds.append(mpf.make_addplot(sell_series, type="scatter",
                         markersize=120, marker="v", color="red",
                         label="SELL"))

    # 绘制
    chart_title = title or f"{symbol} K线图 (含买卖点)"
    fig, axes = mpf.plot(
        df.tail(120),  # 最近 120 个交易日
        type="candle",
        volume=True,
        style="charles",
        title=chart_title,
        addplot=apds if apds else None,
        figsize=(12, 7),
        returnfig=True,
    )

    # 保存
    os.makedirs(CHART_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{symbol}_{ts}.png"
    fpath = os.path.join(CHART_DIR, fname)
    fig.savefig(fpath, dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info(f"📊 图表已保存: {fpath}")
    return fpath

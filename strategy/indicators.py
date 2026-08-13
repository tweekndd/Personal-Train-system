"""
技术指标计算模块
纯 pandas 实现，无需 ta-lib
V0.2
"""

import pandas as pd
import numpy as np


def compute_ma(series: pd.Series, window: int = 20) -> pd.Series:
    """计算移动平均线 (Simple Moving Average)

    Args:
        series: 价格序列 (close)
        window: 周期数

    Returns:
        移动平均线 Series
    """
    return series.rolling(window=window).mean()


def compute_ema(series: pd.Series, window: int = 20) -> pd.Series:
    """计算指数移动平均线 (Exponential Moving Average)"""
    return series.ewm(span=window, adjust=False).mean()


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """计算相对强弱指标 (RSI)

    Args:
        series: 价格序列 (close)
        window: 周期数，默认14

    Returns:
        RSI 值 Series (0-100)
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()

    # Wilder 平滑
    for i in range(window, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (window - 1) + gain.iloc[i]) / window
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (window - 1) + loss.iloc[i]) / window

    # 处理纯涨/纯跌/平盘的边界情况
    #   纯涨: loss=0 → rs=∞ → RSI=100
    #   纯跌: gain=0 → rs=0  → RSI=0
    #   平盘: 0/0   → NaN   → RSI=50
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50.0).clip(0, 100)
    return rsi


def detect_golden_cross(short_ma: pd.Series, long_ma: pd.Series) -> pd.Series:
    """检测金叉信号（短期均线上穿长期均线）

    Returns:
        bool Series: True 表示当天发生金叉
    """
    prev_cross = short_ma.shift(1) <= long_ma.shift(1)
    curr_cross = short_ma > long_ma
    return prev_cross & curr_cross


def detect_death_cross(short_ma: pd.Series, long_ma: pd.Series) -> pd.Series:
    """检测死叉信号（短期均线下穿长期均线）

    Returns:
        bool Series: True 表示当天发生死叉
    """
    prev_cross = short_ma.shift(1) >= long_ma.shift(1)
    curr_cross = short_ma < long_ma
    return prev_cross & curr_cross


def compute_bollinger_bands(series: pd.Series, window: int = 20, num_std: int = 2):
    """计算布林带

    Returns:
        (middle, upper, lower) 三元组
    """
    middle = compute_ma(series, window)
    std = series.rolling(window=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def compute_volume_ratio(volume: pd.Series, window: int = 5) -> pd.Series:
    """计算量比 (当前成交量 / 过去N日均量)

    Args:
        volume: 成交量序列
        window: 基准周期

    Returns:
        量比序列，>1 表示放量
    """
    avg_volume = volume.rolling(window=window).mean()
    return volume / avg_volume.replace(0, np.nan)

"""
数据质量校验模块
对从 akshare 获取的 K 线数据进行完整性检查
V0.6
"""

import pandas as pd
from loguru import logger


def validate_kline(df: pd.DataFrame, symbol: str = "") -> list[str]:
    """校验 K 线数据质量

    Args:
        df: 日K线 DataFrame
        symbol: 股票代码（日志用）

    Returns:
        list[str]: 发现的错误列表（空列表 = 数据合格）
    """
    errors = []

    if df.empty:
        errors.append(f"{symbol}: 数据为空")
        return errors

    # 1. 非正价格
    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            bad = (df[col] <= 0).sum()
            if bad > 0:
                errors.append(f"{symbol}: {col} 存在 {bad} 条非正值")

    # 2. 缺失成交量
    if "volume" in df.columns:
        missing_vol = df["volume"].isna().sum()
        if missing_vol > 0:
            errors.append(f"{symbol}: 存在 {missing_vol} 条缺失成交量")

    # 3. 日期排序
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"])
        if not dates.is_monotonic_increasing:
            errors.append(f"{symbol}: 日期未按升序排列")

    # 4. 异常跳空（单日涨跌幅超过 20%，可能是除权未处理）
    if "close" in df.columns:
        pct = df["close"].pct_change().abs()
        gaps = (pct > 0.20).sum()
        if gaps > 0:
            errors.append(f"{symbol}: 存在 {gaps} 个单日涨跌幅 > 20%（可能除权未处理）")

    # 5. 重复日期
    if "date" in df.columns:
        dup = df["date"].duplicated().sum()
        if dup > 0:
            errors.append(f"{symbol}: 存在 {dup} 个重复日期")

    return errors


def assert_kline_valid(df: pd.DataFrame, symbol: str = "") -> bool:
    """断言式校验，返回是否通过"""
    errors = validate_kline(df, symbol)
    if errors:
        for e in errors:
            logger.warning(f"⚠️ 数据质量: {e}")
        return False
    logger.info(f"✅ 数据校验通过: {symbol} ({len(df)} 条)")
    return True

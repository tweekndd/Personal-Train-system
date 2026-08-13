"""
数据中心 - 数据获取模块
功能：通过 akshare 获取市场数据
V0.1 - 基础数据获取
"""

import time
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
from loguru import logger

_EFINANCE = None


def _import_efinance():
    """惰性导入 efinance 备选数据源（未安装时返回 None）"""
    global _EFINANCE
    if _EFINANCE is None:
        try:
            import efinance as ef
            _EFINANCE = ef
            logger.info("已加载备选数据源 efinance")
        except ImportError:
            logger.warning("efinance 未安装，跳过备选数据源")
            _EFINANCE = False
    return _EFINANCE or None


# ── 代码工具 ─────────────────────────────────────────────────

def normalize_symbol(symbol) -> str:
    """去除 sh/sz/bj 交易所前缀，返回纯 6 位代码"""
    code = str(symbol).strip().lower()
    for p in ("sh", "sz", "bj"):
        if code.startswith(p):
            return code[len(p):]
    return code


# 场内 ETF 代码前缀（沪市 5xx/56x/58x，深市 159）
_ETF_PREFIXES = (
    "159",
    "510", "511", "512", "513", "515", "516", "517", "518",
    "560", "561", "562", "563",
    "588", "589",
)


def is_etf_code(symbol) -> bool:
    """判断 6 位代码是否为场内 ETF

    场内 ETF：深市 159 开头，沪市 510/511/512/513/515/516/517/518/
    560/561/562/563/588/589 开头。
    """
    code = normalize_symbol(symbol)
    return (
        code.isdigit()
        and len(code) == 6
        and any(code.startswith(p) for p in _ETF_PREFIXES)
    )


class DataFetcher:
    """数据获取器 - 封装 akshare 接口，akshare 失效时回退到 efinance"""

    def __init__(self):
        self._cache = {}

    # ── 股票列表 ──────────────────────────────────────────────

    def get_a_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表（全市场）

        Returns:
            DataFrame 包含: 股票代码, 名称 等基本信息
        """
        logger.info("正在获取A股股票列表...")

        # 方案1: 带实时行情的接口（可能网络慢）
        for api_name, api_fn in [
            ("stock_zh_a_spot_em", lambda: ak.stock_zh_a_spot_em()),
            ("stock_zh_a_spot", lambda: ak.stock_zh_a_spot()),
            ("stock_info_a_code_name", lambda: ak.stock_info_a_code_name()),
        ]:
            try:
                df = api_fn()
                if df is not None and not df.empty:
                    logger.info(f"[{api_name}] 成功获取 {len(df)} 只股票")
                    return df
            except Exception as e:
                logger.warning(f"[{api_name}] 失败: {e}")
                continue

        # 备选数据源: efinance（主源全部失效时）
        ef = _import_efinance()
        if ef is not None:
            try:
                df = ef.stock.get_realtime_quotes()
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        "股票代码": "代码",
                        "股票名称": "名称",
                        "动态市盈率": "市盈率-动态",
                    })
                    logger.info(f"[efinance] 成功获取 {len(df)} 只股票")
                    return df
            except Exception as e:
                logger.warning(f"[efinance] 失败: {e}")

        logger.error("所有数据源均失败")
        return pd.DataFrame()

    def get_stock_names(self) -> pd.DataFrame:
        """获取股票代码-名称映射表"""
        # 优先用名称映射专用接口
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"stock_info_a_code_name 失败: {e}")

        # 备用：从实时行情提取
        for fn in [ak.stock_zh_a_spot_em, ak.stock_zh_a_spot]:
            try:
                df = fn()
                if df is not None and not df.empty:
                    code_col = "代码" if "代码" in df.columns else "code"
                    name_col = "名称" if "名称" in df.columns else "name"
                    return df[[code_col, name_col]].copy()
            except Exception:
                continue

        # 备选数据源: efinance
        ef = _import_efinance()
        if ef is not None:
            try:
                df = ef.stock.get_realtime_quotes()
                if df is not None and not df.empty:
                    return df[["股票代码", "股票名称"]].rename(
                        columns={"股票代码": "代码", "股票名称": "名称"}
                    ).copy()
            except Exception as e:
                logger.warning(f"[efinance] 股票名称映射失败: {e}")

        return pd.DataFrame()

    # ── 日K线数据 ─────────────────────────────────────────────

    def get_daily_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """获取个股日K线数据

        Args:
            symbol: 股票代码，如 "000001"
            start_date: 开始日期 "YYYYMMDD"，默认90天前
            end_date: 结束日期 "YYYYMMDD"，默认今天
            adjust: 复权类型, "qfq"(前复权) / "hfq"(后复权) / ""

        Returns:
            DataFrame 包含: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额
        """
        # 默认最近90天
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start = datetime.now() - timedelta(days=90)
            start_date = start.strftime("%Y%m%d")

        logger.info(f"获取 {symbol} 日K线: {start_date} ~ {end_date}")
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            if df is not None and not df.empty:
                # 统一列名
                df.rename(
                    columns={
                        "日期": "date",
                        "开盘": "open",
                        "收盘": "close",
                        "最高": "high",
                        "最低": "low",
                        "成交量": "volume",
                        "成交额": "amount",
                        "振幅": "amplitude",
                        "涨跌幅": "pct_change",
                        "涨跌额": "change",
                        "换手率": "turnover",
                    },
                    inplace=True,
                )
                df["symbol"] = symbol
                logger.info(f"  [stock_zh_a_hist] {symbol}: {len(df)} 条")
                return df
        except Exception as e:
            logger.warning(f"  [stock_zh_a_hist] {symbol} 失败: {e}")

        # 备用接口: stock_zh_a_daily (更老但更稳定)
        try:
            # 需要加 sz/sh 前缀
            prefix = "sz" if symbol.startswith("0") or symbol.startswith("3") else "sh"
            df = ak.stock_zh_a_daily(symbol=f"{prefix}{symbol}", adjust=adjust)
            if df is not None and not df.empty:
                df.rename(
                    columns={
                        "date": "date",
                        "open": "open",
                        "high": "high",
                        "close": "close",
                        "low": "low",
                        "volume": "volume",
                        "amount": "amount",
                    },
                    inplace=True,
                )
                df["symbol"] = symbol
                # stock_zh_a_daily 的成交量单位是"股"，统一换算为"手"(1手=100股)，
                # 与 stock_zh_a_hist 保持一致，避免不同数据源信号不一致
                if "volume" in df.columns:
                    df["volume"] = df["volume"] / 100
                # stock_zh_a_daily 返回的 date 是 datetime.date 类型
                if start_date:
                    sd = datetime.strptime(start_date, "%Y%m%d").date()
                    df = df[df["date"] >= sd]
                if end_date:
                    ed = datetime.strptime(end_date, "%Y%m%d").date()
                    df = df[df["date"] <= ed]
                logger.info(f"  [stock_zh_a_daily] {symbol}: {len(df)} 条")
                return df
        except Exception as e:
            logger.warning(f"  [stock_zh_a_daily] {symbol} 失败: {e}")

        # 备选数据源: efinance（akshare 全部失效后，本地缓存之前）
        ef = _import_efinance()
        if ef is not None:
            try:
                fqt_map = {"qfq": 1, "hfq": 2, "": 0}
                df = ef.stock.get_quote_history(
                    symbol,
                    beg=start_date,
                    end=end_date,
                    klt=101,
                    fqt=fqt_map.get(adjust, 1),
                )
                if df is not None and not df.empty:
                    df.rename(
                        columns={
                            "日期": "date",
                            "开盘": "open",
                            "收盘": "close",
                            "最高": "high",
                            "最低": "low",
                            "成交量": "volume",
                            "成交额": "amount",
                            "振幅": "amplitude",
                            "涨跌幅": "pct_change",
                            "涨跌额": "change",
                            "换手率": "turnover",
                        },
                        inplace=True,
                    )
                    df["symbol"] = symbol
                    # efinance 成交量单位为"手"，与 stock_zh_a_hist 一致，无需换算
                    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                    # 去除多余的中文列，保持与 akshare 输出一致
                    df = df.drop(columns=["股票名称", "股票代码"], errors="ignore")
                    # 统一按日期升序（与 stock_zh_a_hist 保持一致）
                    df = df.sort_values("date").reset_index(drop=True)
                    logger.info(f"  [efinance] {symbol}: {len(df)} 条")
                    return df
            except Exception as e:
                logger.warning(f"  [efinance] {symbol} 失败: {e}")

        # 兜底：从本地数据库读取已缓存K线
        try:
            from database import DatabaseManager
            db_df = DatabaseManager().get_klines(symbol)
            if db_df is not None and not db_df.empty:
                # 本地缓存日期为 YYYY-MM-DD 字符串
                if start_date:
                    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                    db_df = db_df[db_df["date"] >= sd]
                if end_date:
                    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
                    db_df = db_df[db_df["date"] <= ed]
                logger.info(f"  [database] {symbol}: {len(db_df)} 条（本地缓存）")
                return db_df
        except Exception as e:
            logger.warning(f"  [database] {symbol} 读取缓存失败: {e}")

        logger.error(f"获取 {symbol} K线: 所有接口均失败")
        return pd.DataFrame()

    # ── 指数K线数据 ───────────────────────────────────────────

    def get_index_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """获取指数日K线数据（如上证指数、深证成指）

        Args:
            symbol: 指数代码，如 "000001"（上证）, "399001"（深证）, "399006"（创业板）, "000688"（科创50）
            start_date, end_date: 日期范围 "YYYYMMDD"
        """
        # 指数代码前缀映射
        prefix_map = {
            "000": "sh",
            "399": "sz",
            "688": "sh",
        }
        prefix = "sh"
        for code_start, p in prefix_map.items():
            if symbol.startswith(code_start):
                prefix = p
                break

        full_symbol = f"{prefix}{symbol}"
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start = datetime.now() - timedelta(days=90)
            start_date = start.strftime("%Y%m%d")

        logger.info(f"获取指数 {full_symbol} 日K线: {start_date} ~ {end_date}")
        for api_name, api_fn in [
            ("stock_zh_index_daily_em", lambda: ak.stock_zh_index_daily_em(symbol=full_symbol)),
            ("stock_zh_index_daily", lambda: ak.stock_zh_index_daily(symbol=full_symbol)),
        ]:
            try:
                df = api_fn()
                if df is None or df.empty:
                    continue
                df.rename(columns={"date": "date", "open": "open",
                                    "close": "close", "high": "high",
                                    "low": "low", "volume": "volume",
                                    "amount": "amount"}, inplace=True)
                df["symbol"] = symbol
                # 归一化日期为 YYYY-MM-DD 字符串（不同接口返回 date 类型或 str）
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                # 过滤日期（统一转为 YYYY-MM-DD 格式比较）
                if start_date:
                    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                    df = df[df["date"] >= sd]
                if end_date:
                    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
                    df = df[df["date"] <= ed]
                logger.info(f"  [指数] {full_symbol}: {len(df)} 条")
                return df
            except Exception as e:
                logger.warning(f"  [{api_name}] {full_symbol} 失败: {e}")

        return pd.DataFrame()

    # ── 实时行情快照 ──────────────────────────────────────────

    def get_realtime_quote(self, symbol: str) -> pd.Series:
        """获取个股实时行情

        Args:
            symbol: 股票代码

        Returns:
            Series 包含实时价格、涨跌幅等
        """
        try:
            df = ak.stock_zh_a_spot_em()
            match = df[df["代码"] == symbol]
            if not match.empty:
                return match.iloc[0]
        except Exception as e:
            logger.error(f"获取 {symbol} 实时行情失败: {e}")

        # 备选数据源: efinance
        ef = _import_efinance()
        if ef is not None:
            try:
                df = ef.stock.get_latest_quote([symbol])
                if df is not None and not df.empty:
                    match = df[df["代码"] == symbol]
                    if not match.empty:
                        return match.iloc[0]
            except Exception as e:
                logger.error(f"[efinance] 获取 {symbol} 实时行情失败: {e}")

        return pd.Series()

    # ── 批量数据 ──────────────────────────────────────────────

    def sync_kline(
        self,
        symbol: str,
        lookback_days: int = 90,
        adjust: str = "qfq",
    ) -> dict:
        """增量同步单只股票K线到本地数据库

        思路：从数据库中已有最新K线的下一天开始拉取，仅补缺失的增量数据；
        无本地数据时拉取最近 lookback_days 天全量历史。
        依赖 save_kline 的 (symbol, date) 唯一约束，重复写入自动去重。

        Args:
            symbol: 股票代码，如 "000725"
            lookback_days: 无本地数据时回看的天数（默认90天）
            adjust: 复权类型

        Returns:
            {
                "symbol": str,
                "status": "synced" | "up_to_date" | "failed",
                "latest_date": 本地最新日期 or None,
                "fetched": 本次拉取条数,
                "saved": 实际入库条数,
            }
        """
        from database import DatabaseManager

        db = DatabaseManager()
        latest = db.get_latest_kline_date(symbol)
        end_date = datetime.now().strftime("%Y%m%d")

        # 已有数据：从下一天增量拉取
        if latest:
            start_dt = datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)
            start_date = start_dt.strftime("%Y%m%d")
            if start_date > end_date:
                logger.info(f"  [sync] {symbol} 已是最新 ({latest})")
                return {"symbol": symbol, "status": "up_to_date",
                        "latest_date": latest, "fetched": 0, "saved": 0}
        else:
            start = datetime.now() - timedelta(days=lookback_days)
            start_date = start.strftime("%Y%m%d")

        logger.info(f"  [sync] {symbol}: 增量同步 {start_date} ~ {end_date} "
                    f"(本地最新: {latest or '无'})")
        df = self.get_daily_kline(symbol, start_date, end_date, adjust)

        # 统一日期格式为 YYYY-MM-DD（不同数据源可能返回 datetime 或 str）
        if not df.empty and "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        saved = db.save_kline(df) if not df.empty else 0
        new_latest = db.get_latest_kline_date(symbol)

        if saved == 0 and df.empty:
            return {"symbol": symbol, "status": "failed",
                    "latest_date": latest, "fetched": 0, "saved": 0}

        logger.info(f"  [sync] {symbol}: 拉取 {len(df)} 条, 入库 {saved} 条, "
                    f"最新 {new_latest}")
        return {"symbol": symbol, "status": "synced",
                "latest_date": new_latest, "fetched": len(df), "saved": saved}

    def sync_klines(
        self,
        symbols: list[str],
        lookback_days: int = 90,
        sleep: float = 0.3,
        retries: int = 2,
    ) -> dict:
        """批量增量同步多只股票K线

        Args:
            symbols: 股票代码列表
            lookback_days: 无本地数据时回看天数
            sleep: 每次请求间隔秒数
            retries: 单只失败后的重试次数

        Returns:
            {"total": n, "synced": m, "failed": [...], "saved": k}
        """
        results = []
        for i, sym in enumerate(symbols):
            logger.info(f"批量同步 [{i+1}/{len(symbols)}] {sym}")
            for attempt in range(retries + 1):
                try:
                    res = self.sync_kline(sym, lookback_days=lookback_days)
                    results.append(res)
                    break
                except Exception as e:
                    if attempt < retries:
                        logger.warning(f"  {sym} 第{attempt+1}次失败，重试: {e}")
                        time.sleep(sleep * 2)
                    else:
                        logger.error(f"  {sym} 同步失败: {e}")
                        results.append({"symbol": sym, "status": "failed",
                                        "latest_date": None, "fetched": 0, "saved": 0})
            time.sleep(sleep)

        synced = [r for r in results if r.get("status") == "synced"]
        failed = [r["symbol"] for r in results if r.get("status") == "failed"]
        saved_total = sum(r.get("saved", 0) for r in results)
        return {
            "total": len(symbols),
            "synced": len(synced),
            "failed": failed,
            "saved": saved_total,
        }

    def batch_get_klines(
        self, symbols: list[str], start_date: str = None, end_date: str = None
    ) -> dict[str, pd.DataFrame]:
        """批量获取多只股票K线

        Args:
            symbols: 股票代码列表
            start_date, end_date: 日期范围

        Returns:
            {symbol: DataFrame} 字典
        """
        result = {}
        total = len(symbols)
        for i, sym in enumerate(symbols):
            logger.info(f"批量获取 [{i+1}/{total}] {sym}")
            df = self.get_daily_kline(sym, start_date, end_date)
            if df is not None and not df.empty:
                result[sym] = df
            time.sleep(0.3)  # 避免请求过快
        return result

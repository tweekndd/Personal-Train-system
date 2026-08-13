"""
股票筛选模块
功能：按价格、流动性、风险等条件预筛选股票
V0.1 - 基础筛选逻辑
"""

from typing import Optional

import akshare as ak
import pandas as pd
from loguru import logger

from config import EXCLUDE_KEYWORDS, MIN_DAILY_AMOUNT, PRICE_RANGE
from .board import detect_board


class StockScreener:
    """股票筛选器 - 寻找适合小资金的交易品种"""

    def __init__(self):
        self._candidates: pd.DataFrame = pd.DataFrame()

    # ── 全市场扫描 ────────────────────────────────────────────

    @staticmethod
    def _fetch_market_data() -> pd.DataFrame:
        """容错获取市场行情数据"""
        for api_name, api_fn in [
            ("stock_zh_a_spot_em", lambda: ak.stock_zh_a_spot_em()),
            ("stock_zh_a_spot", lambda: ak.stock_zh_a_spot()),
        ]:
            try:
                df = api_fn()
                if df is not None and not df.empty:
                    logger.info(f"[{api_name}] 获取全市场行情: {len(df)} 只股票")
                    return df
            except Exception as e:
                logger.warning(f"[{api_name}] 失败: {e}")
                continue
        logger.error("所有行情源均失败")
        return pd.DataFrame()

    def scan_all(self, price_low=None, price_high=None, board: Optional[str] = None) -> pd.DataFrame:
        """扫描全市场，筛选符合基本条件的股票

        Args:
            price_low: 最低价格 (默认 PRICE_RANGE[0])
            price_high: 最高价格 (默认 PRICE_RANGE[1])
            board: 板块过滤，可选 "主板" / "科创板" / "创业板" / "北交所"，None 表示不过滤

        Returns:
            筛选后的候选股票 DataFrame
        """
        price_low = price_low or PRICE_RANGE[0]
        price_high = price_high or PRICE_RANGE[1]

        logger.info(f"开始全市场扫描: 价格区间 {price_low}-{price_high}元" +
                    (f"，板块 {board}" if board else ""))

        # 使用容错数据获取
        df = self._fetch_market_data()
        if df.empty:
            return pd.DataFrame()

        # 统一股票代码：去掉 sh/sz/bj 交易所前缀（部分接口返回 "sz000725"）
        code_col = self._find_column(df, ["代码", "code", "symbol"])
        if code_col:
            df[code_col] = df[code_col].astype(str).str.replace(
                r"^(sh|sz|bj)", "", regex=True)

        # 记录筛选过程
        stages = []

        # 板块过滤（在代码归一化之后，直接按代码前缀过滤）
        if board and code_col:
            board = str(board).strip()
            before = len(df)
            df = df[df[code_col].map(detect_board) == board]
            stages.append(f"板块筛选({board}): {before} -> {len(df)}")

        # 步骤1: 过滤价格
        price_col = self._find_column(df, ["最新价", "current", "price"])
        if price_col:
            df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
            before = len(df)
            df = df[(df[price_col] >= price_low) & (df[price_col] <= price_high)]
            stages.append(f"价格筛选: {before} -> {len(df)}")
        else:
            logger.warning("未找到价格列，跳过价格筛选")

        # 步骤2: 排除风险股票（名称过滤）
        name_col = self._find_column(df, ["名称", "name"])
        if name_col:
            before = len(df)
            for kw in EXCLUDE_KEYWORDS:
                df = df[~df[name_col].str.contains(kw, na=False)]
            stages.append(f"排除风险股: {before} -> {len(df)}")

        # 步骤3: 流动性过滤
        amount_col = self._find_column(df, ["成交额", "amount", "turnover"])
        if amount_col:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce")
            before = len(df)
            df = df[df[amount_col] >= MIN_DAILY_AMOUNT]
            stages.append(f"流动性筛选: {before} -> {len(df)}")

        # 步骤4: 排序 - 按成交额降序（优先选活跃股）
        if amount_col and amount_col in df.columns:
            df = df.sort_values(amount_col, ascending=False)

        # 步骤5: 去重（确保代码唯一）
        code_col = self._find_column(df, ["代码", "code", "symbol"])
        if code_col:
            df = df.drop_duplicates(subset=[code_col])

        # 步骤6: 新股过滤（上市不满60天，均线不可靠）
        # 通过排除价格稳定性和成交量数据量不足来间接处理
        # akshare spot 不直接提供上市日期，这里用成交量连续性近似判断

        for s in stages:
            logger.info(s)
        logger.info(f"扫描完成: 候选股票 {len(df)} 只")

        self._candidates = df
        return df

    # ── 候选列表 ──────────────────────────────────────────────

    def get_top_candidates(self, n: int = 10) -> pd.DataFrame:
        """获取排名靠前的候选股票

        Args:
            n: 返回数量

        Returns:
            前N只候选股
        """
        if self._candidates.empty:
            self.scan_all()
        return self._candidates.head(n)

    def get_candidate_by_code(self, code: str) -> pd.Series:
        """按代码查找候选股"""
        code_col = self._find_column(self._candidates, ["代码", "code", "symbol"])
        if code_col is None:
            return pd.Series()
        match = self._candidates[self._candidates[code_col] == code]
        return match.iloc[0] if not match.empty else pd.Series()

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        """在DataFrame中查找可能的列名"""
        for col in candidates:
            if col in df.columns:
                return col
        return None

    @staticmethod
    def format_candidates(df: pd.DataFrame) -> str:
        """将候选股票格式化为可读文本"""
        if df.empty:
            return "暂无候选股票"

        code_col = StockScreener._find_column(df, ["代码", "code", "symbol"])
        name_col = StockScreener._find_column(df, ["名称", "name"])
        price_col = StockScreener._find_column(df, ["最新价", "current", "price"])
        pct_col = StockScreener._find_column(df, ["涨跌幅", "pct_change", "changepercent"])

        lines = ["📊 候选股票列表:\n"]
        for i, (_, row) in enumerate(df.iterrows(), 1):
            code = str(row.get(code_col, ""))
            name = str(row.get(name_col, ""))
            price = row.get(price_col, "")
            pct = row.get(pct_col, "")
            pct_val = float(pct) if pd.notna(pct) else 0.0
            lines.append(
                f"  {i}. {name}({code}) "
                f"¥{price} "
                f"({'📈' if pct_val >= 0 else '📉'}{pct}%)"
            )
        return "\n".join(lines)

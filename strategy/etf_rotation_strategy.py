"""
策略C: ETF 轮动策略
参考 config.py — ETF_ROTATION_STRATEGY 参数
场内 ETF 普遍低价（0.5~5 元），与小资金轮动策略天然契合
"""

from typing import Optional

import akshare as ak
import pandas as pd
from loguru import logger

from data import DataFetcher
from strategy.base import BaseStrategy
from config import ETF_ROTATION_STRATEGY as CONFIG_PARAMS
from screen.board import is_etf


class ETFRotationStrategy(BaseStrategy):
    """ETF 轮动策略

    每日扫描全市场 ETF:
    条件:
        - 价格 0.5-5 元
        - 近20日上涨趋势（20日涨幅 > 0）
        - 成交活跃（成交额 >= 2000万）
    输出:
        - 候选 ETF 列表，按综合评分排序 Top N
    """

    def __init__(self, params: dict = None):
        default_params = dict(CONFIG_PARAMS)  # 从 config.py 读取
        if params:
            default_params.update(params)
        super().__init__("ETF轮动策略", default_params)

        self._candidates: pd.DataFrame = pd.DataFrame()
        self._signal: Optional[dict] = None

    def on_market_data(self, kline_df: pd.DataFrame) -> None:
        """轮动策略不做逐K分析，由 scan 驱动"""
        pass

    def generate_signal(self) -> Optional[dict]:
        """返回当期轮动榜单（作为信号输出）"""
        if self._candidates.empty:
            return None
        return {
            "action": "ROTATION_LIST",
            "strategy": self.name,
            "candidates": self._candidates.to_dict("records"),
            "reason": f"ETF轮动Top{self.params['top_n']}",
        }

    def scan(self) -> pd.DataFrame:
        """执行全市场 ETF 扫描

        Returns:
            排序后的候选 ETF DataFrame
        """
        p = self.params
        logger.info(f"🔄 {self.name}: 开始全市场 ETF 扫描")

        # 获取行情数据
        df = self._fetch_market_data()
        if df.empty:
            logger.warning(f"{self.name}: 未获取到行情数据")
            return pd.DataFrame()

        code_col = self._find_column(df, ["代码", "code", "symbol"])
        if not code_col:
            logger.error("未找到代码列")
            return pd.DataFrame()

        # 统一代码格式
        df[code_col] = df[code_col].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)

        # 筛选步骤
        stages = []

        # 1. ETF 代码过滤
        before = len(df)
        df = df[df[code_col].map(is_etf)]
        stages.append(f"ETF代码筛选: {before} -> {len(df)}")

        if df.empty:
            logger.warning(f"{self.name}: 无 ETF 匹配")
            return pd.DataFrame()

        # 2. 价格筛选
        price_col = self._find_column(df, ["最新价", "current", "price"])
        if price_col:
            df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
            before = len(df)
            df = df[(df[price_col] >= p["price_low"]) & (df[price_col] <= p["price_high"])]
            stages.append(f"价格筛选({p['price_low']}-{p['price_high']}元): {before} -> {len(df)}")

        # 3. 流动性筛选
        amount_col = self._find_column(df, ["成交额", "amount", "turnover"])
        if amount_col:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce")
            before = len(df)
            df = df[df[amount_col] >= p["min_amount"]]
            stages.append(f"流动性筛选(>= {p['min_amount']/1e8:.1f}亿): {before} -> {len(df)}")

        if df.empty:
            for s in stages:
                logger.info(s)
            logger.warning(f"{self.name}: 无满足条件的 ETF")
            return pd.DataFrame()

        # 4. 计算真实的20日涨幅
        df = self._add_trend_score(df)
        if df.empty:
            for s in stages:
                logger.info(s)
            logger.warning(f"{self.name}: 无满足20日上涨趋势的 ETF")
            return df

        # 5. 综合评分排序
        df = self._score(df)
        df = df.sort_values("rotation_score", ascending=False)

        # 6. 取 Top N
        top_n = min(p["top_n"], len(df))
        self._candidates = df.head(top_n)

        for s in stages:
            logger.info(s)
        logger.info(f"  ✅ ETF 轮动候选 Top{top_n}")
        self._signal = self.generate_signal()
        return self._candidates

    def _add_trend_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算20日涨幅并对候选进行趋势过滤"""
        p = self.params
        limit = p.get("trend_scan_limit", 30)
        code_col = self._find_column(df, ["代码", "code", "symbol"])
        amount_col = self._find_column(df, ["成交额", "amount", "turnover"])

        top = df.sort_values(amount_col, ascending=False).head(limit)

        fetcher = DataFetcher()
        scores: dict[str, float] = {}
        for _, row in top.iterrows():
            code = str(row[code_col])
            kline = fetcher.get_daily_kline(code)
            if kline is None or kline.empty or len(kline) < 21:
                logger.warning(f"  {code}: 无足够K线计算20日趋势，跳过")
                continue
            close = kline["close"].astype(float)
            trend = (close.iloc[-1] / close.iloc[-21] - 1) * 100
            scores[code] = trend

        if not scores:
            return pd.DataFrame()

        df = df[df[code_col].isin(scores)].copy()
        df["trend20"] = df[code_col].map(scores)
        # 过滤20日下跌的 ETF
        df = df[df["trend20"] >= p["min_trend_20d"] * 100]
        # 趋势评分：20日涨幅，限制涨幅上限避免追高
        df["trend_score"] = df["trend20"].clip(
            p["min_trend_20d"] * 100, p["max_trend_20d"] * 100
        )
        logger.info(f"  20日趋势筛选: {len(df)} 只")
        return df

    def _score(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算轮动综合评分（趋势评分 + 流动性评分）"""
        amount_col = self._find_column(df, ["成交额", "amount", "turnover"])
        amount = pd.to_numeric(df[amount_col], errors="coerce")
        max_amount = amount.max()
        df["liquidity_score"] = (amount / max_amount * 100) if max_amount > 0 else 0

        # 综合评分 (50% 趋势 + 50% 流动性)
        df["rotation_score"] = df["trend_score"] * 0.5 + df["liquidity_score"] * 0.5

        return df

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        """在DataFrame中查找可能的列名"""
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def get_candidates(self) -> pd.DataFrame:
        """获取当前候选列表"""
        if self._candidates.empty:
            self.scan()
        return self._candidates

    @staticmethod
    def _fetch_market_data() -> pd.DataFrame:
        """容错获取市场行情"""
        for fn in [ak.stock_zh_a_spot_em, ak.stock_zh_a_spot]:
            try:
                df = fn()
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"行情源失败: {e}")
                continue
        return pd.DataFrame()

    @staticmethod
    def format_candidates(df: pd.DataFrame) -> str:
        """格式化候选列表为可读文本"""
        if df.empty:
            return "暂无 ETF 轮动候选"

        code_col = "代码" if "代码" in df.columns else "code"
        name_col = "名称" if "名称" in df.columns else "name"
        price_col = "最新价" if "最新价" in df.columns else "price"
        pct_col = "涨跌幅" if "涨跌幅" in df.columns else "pct_change"

        lines = ["🏆 ETF 轮动候选:\n"]
        for i, (_, row) in enumerate(df.iterrows(), 1):
            code = row.get(code_col, "")
            name = row.get(name_col, "")
            price = row.get(price_col, 0)
            pct = row.get(pct_col, 0)
            pct_val = float(pct) if pd.notna(pct) else 0.0
            arrow = "📈" if pct_val >= 0 else "📉"
            trend_txt = ""
            if "trend20" in df.columns and pd.notna(row.get("trend20")):
                trend_txt = f" | 20日涨幅 {row['trend20']:+.1f}%"
            lines.append(f"  {i:2d}. {name}({code})  ¥{price}  {arrow}{pct}%{trend_txt}")

        return "\n".join(lines)

    def reset(self):
        super().reset()
        self._candidates = pd.DataFrame()
        self._signal = None

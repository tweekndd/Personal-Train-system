"""
策略B: 低价轮动策略
参考 PRD — 每日扫描3-15元区间，筛选Top 10
V0.2
"""

from typing import Optional

import akshare as ak
import pandas as pd
from loguru import logger

from data import DataFetcher
from strategy.base import BaseStrategy
from config import ROTATION_STRATEGY as CONFIG_PARAMS


class RotationStrategy(BaseStrategy):
    """低价轮动策略

    每日扫描全市场:
    条件:
        - 价格 3-15 元
        - 近20日上涨趋势（20日涨幅 > 0）
        - 成交活跃（成交额达标）
        - 波动合理
    输出:
        - 候选股票列表，按综合评分排序 Top 10
    """

    def __init__(self, params: dict = None):
        default_params = dict(CONFIG_PARAMS)  # 从 config.py 读取
        if params:
            default_params.update(params)
        super().__init__("低价轮动策略", default_params)

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
            "reason": f"轮动Top{self.params['top_n']}",
        }

    def scan(self) -> pd.DataFrame:
        """执行全市场扫描

        Returns:
            排序后的候选股 DataFrame
        """
        p = self.params
        logger.info(f"🔄 {self.name}: 开始全市场扫描")

        # 获取行情数据
        df = self._fetch_market_data()
        if df.empty:
            logger.warning(f"{self.name}: 未获取到行情数据")
            return pd.DataFrame()

        # 筛选步骤
        code_col = "代码"
        name_col = "名称"
        price_col = "最新价"
        pct_col = "涨跌幅"
        amount_col = "成交额"

        # 1. 价格筛选
        df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
        df = df[(df[price_col] >= p["price_low"]) & (df[price_col] <= p["price_high"])]
        logger.info(f"  价格筛选 3-15元: {len(df)} 只")

        # 2. 排除风险股
        name_col_found = "名称" if "名称" in df.columns else "name"
        for kw in ["ST", "退市", "风险警示"]:
            df = df[~df[name_col_found].str.contains(kw, na=False)]
        logger.info(f"  排除风险股: {len(df)} 只")

        # 3. 流动性筛选
        df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce")
        df = df[df[amount_col] >= p["min_amount"]]
        logger.info(f"  流动性筛选: {len(df)} 只")

        # 4. 计算真实的20日涨幅（行情快照不含历史，对流动性 Top N 拉取K线）
        df = self._add_trend_score(df)
        if df.empty:
            logger.warning(f"{self.name}: 无满足20日上涨趋势的候选")
            self._candidates = pd.DataFrame()
            self._signal = None
            return df

        # 5. 综合评分排序
        df = self._score(df)
        df = df.sort_values("rotation_score", ascending=False)

        # 6. 取 Top N
        top_n = min(p["top_n"], len(df))
        self._candidates = df.head(top_n)

        logger.info(f"  ✅ 轮动候选 Top{top_n}")
        self._signal = self.generate_signal()
        return self._candidates

    def _add_trend_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算20日涨幅并对候选进行趋势过滤

        行情快照不含20日历史数据，因此只对流动性靠前的股票拉取日K线
        计算真实20日涨幅；无法获取K线或20日涨幅 < min_trend_20d 的股票
        将被剔除（不再用当日涨跌幅冒充20日趋势）。
        """
        p = self.params
        limit = p.get("trend_scan_limit", 30)
        top = df.sort_values("成交额", ascending=False).head(limit)

        fetcher = DataFetcher()
        scores: dict[str, float] = {}
        for _, row in top.iterrows():
            code = str(row["代码"])
            kline = fetcher.get_daily_kline(code)
            if kline is None or kline.empty or len(kline) < 21:
                logger.warning(f"  {code}: 无足够K线计算20日趋势，跳过")
                continue
            close = kline["close"].astype(float)
            trend = (close.iloc[-1] / close.iloc[-21] - 1) * 100
            scores[code] = trend

        if not scores:
            return pd.DataFrame()

        df = df[df["代码"].isin(scores)].copy()
        df["trend20"] = df["代码"].map(scores)
        # 过滤20日下跌的股票
        df = df[df["trend20"] >= p["min_trend_20d"] * 100]
        # 趋势评分：20日涨幅，限制涨幅上限避免追高
        df["trend_score"] = df["trend20"].clip(
            p["min_trend_20d"] * 100, p["max_trend_20d"] * 100
        )
        logger.info(f"  20日趋势筛选: {len(df)} 只")
        return df

    def _score(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算轮动综合评分（趋势评分 + 流动性评分）"""
        amount = pd.to_numeric(df["成交额"], errors="coerce")
        max_amount = amount.max()
        df["liquidity_score"] = (amount / max_amount * 100) if max_amount > 0 else 0

        # 综合评分 (50% 趋势 + 50% 流动性)
        df["rotation_score"] = df["trend_score"] * 0.5 + df["liquidity_score"] * 0.5

        return df

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
            return "暂无轮动候选"

        code_col = "代码"
        name_col = "名称"
        price_col = "最新价"
        pct_col = "涨跌幅"

        lines = ["🏆 低价轮动候选 Top 10:\n"]
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

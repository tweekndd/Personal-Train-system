"""
数据库管理模块
功能：SQLite 数据库初始化、建表、基础CRUD
V0.1 - 数据库初始化 + 股票列表表
"""

from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_PATH

Base = declarative_base()


# ── ORM 模型 ────────────────────────────────────────────────

class StockInfo(Base):
    """股票基本信息表"""
    __tablename__ = "stock_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), unique=True, nullable=False, index=True, comment="股票代码")
    name = Column(String(50), nullable=False, comment="股票名称")
    listing_date = Column(String(10), nullable=True, comment="上市日期")
    industry = Column(String(50), nullable=True, comment="所属行业")
    is_suspended = Column(Integer, default=0, comment="是否停牌 0否1是")
    is_st = Column(Integer, default=0, comment="是否ST 0否1是")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DailyKline(Base):
    """日K线数据表"""
    __tablename__ = "daily_kline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True, comment="股票代码")
    date = Column(String(10), nullable=False, comment="日期 YYYY-MM-DD")
    open = Column(Float, comment="开盘价")
    close = Column(Float, comment="收盘价")
    high = Column(Float, comment="最高价")
    low = Column(Float, comment="最低价")
    volume = Column(Float, comment="成交量(手)")
    amount = Column(Float, comment="成交额(元)")
    turnover = Column(Float, comment="换手率(%)")
    pct_change = Column(Float, comment="涨跌幅(%)")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="idx_symbol_date"),
        Index("idx_daily_kline_symbol", "symbol"),
    )


# MarketIndex 等更多表将在后续版本添加


# ── 数据库管理器 ─────────────────────────────────────────────

class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self.Session = sessionmaker(bind=self.engine)
        self._init_db()

    def _init_db(self):
        """初始化数据库 - 建表"""
        Base.metadata.create_all(self.engine)
        logger.info(f"数据库初始化完成: {self.db_path}")
        # 打印所有表名
        tables = Base.metadata.tables.keys()
        logger.info(f"已创建表: {list(tables)}")

    def get_session(self):
        """获取数据库会话"""
        return self.Session()

    # ── 股票信息操作 ─────────────────────────────────────────

    def save_stock_list(self, df: pd.DataFrame) -> int:
        """保存股票列表到数据库（增量和更新）

        Args:
            df: 包含 代码、名称 列的DataFrame

        Returns:
            新增/更新的记录数
        """
        session = self.get_session()
        count = 0
        try:
            # 智能列名映射：兼容中文/英文列名
            # stock_zh_a_spot_em -> 中文列
            # stock_info_a_code_name -> code/name 英文列
            code_col = "代码" if "代码" in df.columns else "code"
            name_col = "名称" if "名称" in df.columns else "name"

            for _, row in df.iterrows():
                symbol = str(row.get(code_col, ""))
                name = str(row.get(name_col, ""))

                if not symbol or not name:
                    continue

                # 检查是否已存在
                existing = session.query(StockInfo).filter_by(symbol=symbol).first()
                if existing:
                    existing.name = name
                    existing.updated_at = datetime.now()
                else:
                    record = StockInfo(
                        symbol=symbol,
                        name=name,
                    )
                    session.add(record)
                    count += 1

            session.commit()
            logger.info(f"股票列表已同步: 新增{count}条, 总记录数待查")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"保存股票列表失败: {e}")
            return 0
        finally:
            session.close()

    def get_all_stocks(self) -> list[dict]:
        """获取所有股票基本信息

        Returns:
            [{symbol, name, ...}]
        """
        session = self.get_session()
        try:
            stocks = session.query(StockInfo).all()
            return [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "listing_date": s.listing_date,
                    "industry": s.industry,
                    "is_st": s.is_st,
                    "is_suspended": s.is_suspended,
                }
                for s in stocks
            ]
        finally:
            session.close()

    def get_stock_count(self) -> int:
        """获取数据库中股票总数量"""
        session = self.get_session()
        try:
            return session.query(StockInfo).count()
        finally:
            session.close()

    # ── K线数据操作 ──────────────────────────────────────────

    def save_kline(self, df: pd.DataFrame) -> int:
        """批量保存日K线数据（依赖 (symbol, date) 唯一约束，INSERT OR IGNORE 去重）

        Args:
            df: 包含 symbol, date, open, close 等列

        Returns:
            实际写入行数
        """
        if df.empty:
            return 0

        now = datetime.now()
        records = []
        for _, row in df.iterrows():
            symbol = row.get("symbol", "")
            date_val = row.get("date", "")
            if not symbol or not date_val:
                continue
            records.append({
                "symbol": str(symbol),
                "date": str(date_val),
                "open": row.get("open"),
                "close": row.get("close"),
                "high": row.get("high"),
                "low": row.get("low"),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
                "turnover": row.get("turnover"),
                "pct_change": row.get("pct_change"),
                "created_at": now,
            })
        if not records:
            return 0

        session = self.get_session()
        try:
            stmt = text(
                "INSERT OR IGNORE INTO daily_kline "
                "(symbol, date, open, close, high, low, volume, amount, "
                " turnover, pct_change, created_at) "
                "VALUES (:symbol, :date, :open, :close, :high, :low, :volume, "
                "        :amount, :turnover, :pct_change, :created_at)"
            )
            result = session.execute(stmt, records)
            session.commit()
            inserted = result.rowcount if result.rowcount not in (None, -1) else len(records)
            logger.info(f"保存K线数据: {inserted}条新记录 (尝试 {len(records)} 条)")
            return inserted
        except Exception as e:
            session.rollback()
            logger.error(f"保存K线失败: {e}")
            return 0
        finally:
            session.close()

    def get_latest_kline_date(self, symbol: str) -> Optional[str]:
        """获取某只股票最新一条K线日期 (YYYY-MM-DD)，无数据返回 None"""
        session = self.get_session()
        try:
            row = (
                session.query(DailyKline)
                .filter_by(symbol=symbol)
                .order_by(DailyKline.date.desc())
                .first()
            )
            return row.date if row else None
        finally:
            session.close()

    def get_symbols_with_klines(self, min_bars: int = 1) -> list[str]:
        """获取已有K线数据的股票代码列表（按K线条数降序）

        Args:
            min_bars: 至少需要多少条K线才纳入

        Returns:
            股票代码列表
        """
        session = self.get_session()
        try:
            rows = (
                session.query(DailyKline.symbol)
                .group_by(DailyKline.symbol)
                .having(func.count(DailyKline.id) >= min_bars)
                .order_by(func.count(DailyKline.id).desc())
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()

    def get_klines(self, symbol: str) -> pd.DataFrame:
        """读取某只股票的全部K线数据（按日期升序）

        Args:
            symbol: 股票代码

        Returns:
            DataFrame 含 date, open, close, high, low, volume, amount 等列
        """
        session = self.get_session()
        try:
            rows = (
                session.query(DailyKline)
                .filter_by(symbol=symbol)
                .order_by(DailyKline.date)
                .all()
            )
            if not rows:
                return pd.DataFrame()
            data = [{
                "date": r.date,
                "open": r.open,
                "close": r.close,
                "high": r.high,
                "low": r.low,
                "volume": r.volume,
                "amount": r.amount,
                "turnover": r.turnover,
                "pct_change": r.pct_change,
                "symbol": r.symbol,
            } for r in rows]
            return pd.DataFrame(data)
        finally:
            session.close()

    # ── 数据库统计 ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取数据库统计信息"""
        session = self.get_session()
        try:
            stock_count = session.query(StockInfo).count()
            kline_count = session.query(DailyKline).count()
            return {
                "total_stocks": stock_count,
                "total_klines": kline_count,
                "db_path": self.db_path,
            }
        finally:
            session.close()

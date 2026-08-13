"""
MiniQbot-Lite 配置文件
V0.2 - 策略系统
"""

from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent

# 数据库路径
DB_DIR = ROOT_DIR / "storage"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "mini_qbot.db"

# ============================================================
# 数据配置
# ============================================================
# 优先筛选的股票价格区间（小资金适用）
PRICE_RANGE = (3.0, 20.0)

# 需要排除的板块/标记
EXCLUDE_KEYWORDS = [
    "ST", "退市", "风险警示", "停牌",
]

# 板块代码前缀 → 板块名称（A股）
# 主板: 沪市 600/601/603/605, 深市 000/001/002/003
# 科创板: 688/689
# 创业板: 300/301
# 北交所: 43x/83x/87x/88x/920
BOARD_PREFIXES = {
    "主板": ["600", "601", "603", "605", "000", "001", "002", "003"],
    "科创板": ["688", "689"],
    "创业板": ["300", "301"],
    "北交所": ["43", "83", "87", "88", "920"],
}
BOARD_NAMES = list(BOARD_PREFIXES.keys())

# 流动性最低标准（日均成交额，单位：元）
MIN_DAILY_AMOUNT = 10_000_000  # 1000万

# ============================================================
# 资金配置
# ============================================================
INITIAL_CAPITAL = 1000.0        # 初始资金
MAX_POSITIONS = 2               # 最大同时持仓
MAX_PER_POSITION = 500.0        # 单只最大资金
MIN_TRADE_AMOUNT = 100.0        # 单次最小交易金额
MAX_TRADE_AMOUNT = 500.0        # 单次最大交易金额（与单只上限一致，否则 100 股整手在 3~5 元区间无法成交）
MAX_LOSS_PER_STOCK = 20.0       # 单只股票最大亏损

# ============================================================
# 策略参数 — V0.2
# ============================================================

# 策略A: 低风险趋势策略
TREND_STRATEGY = {
    "ma_short": 5,              # 短期均线周期
    "ma_long": 20,              # 长期均线周期
    "rsi_window": 14,           # RSI 计算周期
    "rsi_low": 40,              # RSI 买入下限
    "rsi_high": 70,             # RSI 买入上限
    "volume_ratio_min": 1.2,    # 最小量比
    "take_profit": 0.05,        # 止盈 +5%
    "stop_loss": 0.05,          # 止损 -5%
}

# 策略B: 低价轮动策略
ROTATION_STRATEGY = {
    "price_low": 3.0,           # 最低价格
    "price_high": 15.0,         # 最高价格
    "min_trend_20d": 0.0,       # 20日最低涨幅
    "max_trend_20d": 0.50,      # 20日最高涨幅上限
    "min_amount": MIN_DAILY_AMOUNT,
    "trend_scan_limit": 30,     # 拉取K线计算真实20日涨幅的流动性Top N
    "top_n": 10,
}

# 策略C: ETF 轮动策略 (V0.9)
# 场内 ETF 普遍低价（宽基/行业 ETF 多在 0.5~5 元），与小资金轮动策略天然契合
ETF_PRICE_RANGE = (0.5, 5.0)         # ETF 常用价格区间（元）
ETF_MIN_DAILY_AMOUNT = 20_000_000    # ETF 流动性最低标准（日均成交额，元）= 2000万

ETF_ROTATION_STRATEGY = {
    "price_low": 0.5,           # 最低价格
    "price_high": 5.0,          # 最高价格
    "min_trend_20d": 0.0,       # 20日最低涨幅
    "max_trend_20d": 0.50,      # 20日最高涨幅上限
    "min_amount": ETF_MIN_DAILY_AMOUNT,
    "trend_scan_limit": 30,     # 拉取K线计算真实20日涨幅的流动性Top N
    "top_n": 10,
}

# ============================================================
# 组合级风控 — V0.8
# ============================================================
RISK_MANAGEMENT = {
    # 组合最大回撤暂停买入阈值（0.10 = 从峰值回撤10%停止买入）
    "max_drawdown_halt": 0.10,
    # 连续亏损达到该笔数后触发冷却
    "consecutive_loss_limit": 2,
    # 冷却天数
    "cooldown_days": 3,
    # 市场环境对应的仓位缩放因子（新买入金额 = 默认额度 * scale）
    "regime_position_scale": {
        "trending": 1.0,          # 上涨趋势: 满仓额
        "consolidating": 0.75,    # 震荡市: 七五成
        "bear": 0.5,              # 下跌市: 半仓额
        "unknown": 1.0,           # 无法判断时保守满额
    },
    # 组合回撤暂停后，市场转暖多少个交易日解除暂停
    "halt_release_days": 2,
}

# 每日调度（V0.8）
SCHEDULER = {
    # 增量同步的工作集上限（拉取K线的股票数，网络不稳时控制时长）
    "sync_universe_limit": 20,
    # 无本地数据时拉取历史天数
    "sync_lookback_days": 90,
    # 报告输出目录
    "report_dir": ROOT_DIR / "reports",
}

# ============================================================
# 日志配置
# ============================================================
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "qbot.log"

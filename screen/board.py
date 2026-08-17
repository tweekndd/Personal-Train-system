"""板块识别模块

根据股票代码前缀判断所属板块（主板/科创板/创业板/北交所/ETF）。
代码可能带 sh/sz/bj 前缀（如 sz000725），需先归一化。
"""

from config import BOARD_PREFIXES

# 场内 ETF 代码前缀（沪市 5xx/56x/58x，深市 159）
_ETF_PREFIXES = (
    "159",
    "510", "511", "512", "513", "515", "516", "517", "518",
    "560", "561", "562", "563",
    "588", "589",
)


def _normalize_code(symbol) -> str:
    """统一代码为纯6位数字"""
    code = str(symbol).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    return code.zfill(6)[:6]


def detect_board(symbol) -> str:
    """根据股票代码识别所属板块

    Args:
        symbol: 股票代码，如 "000725" 或 "sz000725"

    Returns:
        板块名称: 主板 / 科创板 / 创业板 / 北交所 / 其他
    """
    code = _normalize_code(symbol)

    for board, prefixes in BOARD_PREFIXES.items():
        if any(code.startswith(p) for p in prefixes):
            return board
    return "其他"


def is_etf(symbol) -> bool:
    """判断代码是否为场内 ETF

    场内 ETF：深市 159 开头，沪市 510/511/512/513/515/516/517/518/
    560/561/562/563/588/589 开头。
    """
    code = _normalize_code(symbol)
    return (
        code.isdigit()
        and len(code) == 6
        and any(code.startswith(p) for p in _ETF_PREFIXES)
    )

"""板块识别模块

根据股票代码前缀判断所属板块（主板/科创板/创业板/北交所）。
代码可能带 sh/sz/bj 前缀（如 sz000725），需先归一化。
"""

from config import BOARD_PREFIXES


def detect_board(symbol) -> str:
    """根据股票代码识别所属板块

    Args:
        symbol: 股票代码，如 "000725" 或 "sz000725"

    Returns:
        板块名称: 主板 / 科创板 / 创业板 / 北交所 / 其他
    """
    code = str(symbol).strip().lower()
    # 去掉交易所前缀（sh/sz/bj）
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    code = code.zfill(6)[:6]

    for board, prefixes in BOARD_PREFIXES.items():
        if any(code.startswith(p) for p in prefixes):
            return board
    return "其他"

"""
MiniQbot-Lite Web Console
FastAPI 后端：将 CLI 命令以 SSE 流式输出到浏览器
运行: venv/bin/python web/run.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / "venv" / "bin" / "python"

app = FastAPI(title="MiniQbot-Lite Web Console", version="0.1.0")


class RunRequest(BaseModel):
    command: str = Field(..., description="命令名")
    symbol: str = Field("", description="股票代码，如 000725")
    top: int = Field(10, ge=1, le=50, description="扫描数量")
    board: str = Field("", description="板块: 主板/科创板/创业板/北交所/ETF")
    sync: bool = Field(False, description="daily: 是否先增量同步K线")


# ── 命令注册表 ──────────────────────────────────────────────
# 每个命令映射到 main.py 的 argv 片段
# "{symbol}" / "{top}" / "{board}" 会被运行时替换

COMMANDS: dict[str, dict] = {
    "status": {
        "label": "系统状态",
        "tokens": ["status"],
        "needs_symbol": False,
    },
    "scan": {
        "label": "全市场扫描",
        "tokens": ["scan", "-t", "{top}", "-b", "{board}"],
        "needs_symbol": False,
    },
    "scan_etf": {
        "label": "ETF扫描",
        "tokens": ["scan", "-t", "{top}", "-b", "ETF"],
        "needs_symbol": False,
    },
    "fetch": {
        "label": "获取K线",
        "tokens": ["fetch", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "signal": {
        "label": "策略信号",
        "tokens": ["strategy", "signal", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "backtest": {
        "label": "回测",
        "tokens": ["backtest", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "market": {
        "label": "市场分析",
        "tokens": ["analyze", "market"],
        "needs_symbol": False,
    },
    "review": {
        "label": "交易复盘",
        "tokens": ["analyze", "review", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "optimize": {
        "label": "参数优化",
        "tokens": ["analyze", "optimize", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "wfo": {
        "label": "前向验证",
        "tokens": ["analyze", "wfo", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "trade": {
        "label": "模拟交易",
        "tokens": ["trade", "-s", "{symbol}"],
        "needs_symbol": True,
    },
    "trade_run": {
        "label": "日运行",
        "tokens": ["trade", "run", "-t", "{top}", "-b", "{board}"],
        "needs_symbol": False,
    },
    "trade_run_etf": {
        "label": "ETF日运行",
        "tokens": ["trade", "run", "-t", "{top}", "-b", "ETF"],
        "needs_symbol": False,
    },
    "trade_status": {
        "label": "账户状态",
        "tokens": ["trade", "status"],
        "needs_symbol": False,
    },
    "trade_reset": {
        "label": "重置账户",
        "tokens": ["trade", "reset"],
        "needs_symbol": False,
    },
    "daily": {
        "label": "每日自动运行",
        "tokens": ["daily", "-t", "{top}", "-b", "{board}", "{sync}"],
        "needs_symbol": False,
    },
    "daily_etf": {
        "label": "ETF每日运行",
        "tokens": ["daily", "-t", "{top}", "-b", "ETF", "{sync}"],
        "needs_symbol": False,
    },
    "portfolio": {
        "label": "组合回测",
        "tokens": ["backtest", "portfolio", "-t", "{top}"],
        "needs_symbol": False,
    },
}


def _safe_symbol(symbol: str) -> str:
    """股票代码只允许数字和 sh/sz/bj 前缀"""
    sym = (symbol or "").strip().lower()
    for p in ("sh", "sz", "bj"):
        if sym.startswith(p):
            sym = sym[2:]
            break
    if not sym.isdigit() or len(sym) != 6:
        raise HTTPException(400, "股票代码必须是6位数字，如 000725")
    return sym


def _build_argv(cmd: dict, req: RunRequest) -> list[str]:
    symbol = _safe_symbol(req.symbol) if cmd.get("needs_symbol") else ""
    board = req.board.strip()
    if board and board not in ("主板", "科创板", "创业板", "北交所", "ETF"):
        raise HTTPException(400, f"非法板块: {board}")
    top = str(max(1, min(req.top, 50)))
    tokens: list[str] = []
    for tok in cmd["tokens"]:
        if tok == "-b" and not board:
            continue  # 未指定板块时不传 -b
        tokens.append(tok)
    argv = [str(VENV_PYTHON), "main.py"]
    for tok in tokens:
        replaced = (
            tok.replace("{symbol}", symbol)
            .replace("{top}", top)
            .replace("{board}", board)
            .replace("{sync}", "--sync" if req.sync else "")
        )
        if replaced:  # 空占位符（如未指定板块/不同步）直接丢弃
            argv.append(replaced)
    return argv


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_command(argv: list[str], label: str):
    """运行命令并逐行推送 SSE 事件"""
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    started = time.time()
    yield _sse("start", {"label": label, "argv": " ".join(argv[2:])})

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    assert proc.stdout is not None
    buffer = b""
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip():
                yield _sse("line", {"text": line.decode("utf-8", errors="replace")})

    rc = await proc.wait()
    elapsed = time.time() - started
    yield _sse("done", {"exit_code": rc, "elapsed": round(elapsed, 2)})


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "static" / "index.html")


@app.get("/api/commands")
async def list_commands():
    """命令清单（前端据此渲染按钮）"""
    return [
        {"id": cid, "label": meta["label"], "needs_symbol": meta["needs_symbol"]}
        for cid, meta in COMMANDS.items()
    ]


@app.get("/api/health")
async def health():
    """健康检查 + 系统摘要"""
    try:
        from database import DatabaseManager

        db = DatabaseManager()
        stats = db.get_stats()
        return {"ok": True, "stocks": stats["total_stocks"], "klines": stats["total_klines"]}
    except Exception:
        return {"ok": False, "stocks": 0, "klines": 0}


@app.get("/api/dashboard")
async def dashboard():
    """仪表盘数据：账户 + 持仓 + 日志 + 风控 + 净值曲线"""
    data = {"ok": True}
    try:
        from trading import PaperTrader

        trader = PaperTrader()
        data["account"] = {
            "initial_capital": trader.account.initial_capital,
            "cash": trader.account.cash,
            "position_count": trader.account.position_count(),
            "max_positions": 2,
        }
        prices = {}
        for sym in list(trader.account.positions.keys()):
            df = trader.fetcher.get_daily_kline(sym)
            if not df.empty:
                prices[sym] = float(df.iloc[-1]["close"])
        snap = trader.account.snapshot(prices)
        data["snapshot"] = snap
        data["positions"] = snap["positions"]
        data["risk"] = trader.risk.snapshot()
        data["equity_history"] = trader.equity_history
        data["journal"] = trader.journal.to_records()[-10:][::-1]
        data["report_date"] = trader.risk.last_run_date
    except Exception as e:
        data["ok"] = False
        data["error"] = str(e)
    return data


@app.get("/api/report")
async def daily_report(date: str = ""):
    """读取某天的每日运行报告文本"""
    try:
        from scheduler import DailyScheduler

        text = DailyScheduler().report(date or None)
        return {"ok": True, "date": date or "", "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/run")
async def run_command(req: RunRequest):
    cmd = COMMANDS.get(req.command)
    if cmd is None:
        raise HTTPException(404, f"未知命令: {req.command}")
    argv = _build_argv(cmd, req)
    return StreamingResponse(
        _stream_command(argv, cmd["label"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)

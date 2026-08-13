#!/usr/bin/env bash
# MiniQbot-Lite 每日自动运行包装脚本 (V0.8)
# 用法:
#   scripts/cron_daily.sh                 # 标准日运行
#   scripts/cron_daily.sh --sync          # 先增量同步K线再运行
#   scripts/cron_daily.sh -b 创业板       # 指定板块
#
# crontab 示例 (每个交易日 15:10 收盘后运行):
#   10 15 * * 1-5 /opt/personal/scripts/cron_daily.sh --sync >> /opt/personal/logs/cron.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="$ROOT/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi

exec "$PYTHON" main.py daily "$@"

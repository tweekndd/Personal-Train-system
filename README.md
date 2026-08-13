# MiniQbot-Lite V0.8

> 个人低风险AI自动交易系统 — 从数据到决策的全流程工具

**不是**高频交易系统/自动赚钱机器人/股票预测机器人，而是帮你用程序化方式做低风险投资的辅助工具。

---

## 📦 快速安装

```bash
# 1. 进入项目目录
cd /opt/personal

# 2. 使用虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 初始化数据库（同步A股股票列表）
python main.py init

# 4. 查看状态
python main.py status
```

---

## 📖 完整命令参考

### 🔹 基础系统 (V0.1)

#### `python main.py init`
初始化 SQLite 数据库，从 akshare 获取全市场股票列表。
```
✅ 数据库初始化完成: 5534 只股票
```

#### `python main.py status`
系统状态：股票数量、K线记录、已加载策略列表。

#### `python main.py scan -t 10`
筛选适合小资金的候选股票（3~20元、排除ST、流动性≥1000万）。

#### `python main.py fetch -s 000725`
获取个股日K线数据（自动容错备用接口）。

#### `python main.py run`
一键完整运行：同步 → 筛选 → 输出统计。

#### `python main.py scan -b 创业板`
按板块扫描候选股票，可选 `主板` / `科创板` / `创业板` / `北交所`。

板块识别规则（按代码前缀）：
| 板块 | 代码前缀 |
|------|---------|
| 主板 | 沪市 600/601/603/605、深市 000/001/002/003 |
| 科创板 | 688/689 |
| 创业板 | 300/301 |
| 北交所 | 43x/83x/87x/88x/920 |

也可与 `trade run` 组合：`python main.py trade run -b 科创板 -t 10`

---

### 🔹 策略信号 (V0.2)

#### `python main.py strategy list`
列出所有已注册策略及其参数。

#### `python main.py strategy signal -s 000725`
对指定股票运行趋势策略，输出技术指标和买卖信号。
```
📈 000725 技术分析:
  当前价格:     ¥5.97
  5日均线:      ¥6.03  📉
  20日均线:     ¥7.10
  RSI(14):      42.4
  信号: HOLD（条件未满足）
```

#### `python main.py strategy scan`
全市场运行轮动策略，输出综合评分 Top 10。

---

### 🔹 回测系统 (V0.3)

#### `python main.py backtest -s 000725`
对指定股票运行回测，模拟真实交易并输出绩效报告。

交易成本模型：
| 项目 | 费率 |
|------|------|
| 手续费 | 万2.5（最低5元） |
| 印花税 | 千1（仅卖出） |
| 滑点 | 0.1% |

```
📊 回测绩效报告 — 000725
  💰 初始资金:       ¥1000.00
  💰 最终资产:       ¥938.99
  📈 总收益率:       -6.10%
  📉 最大回撤:       9.21%
  🎯 总交易次数:     2
  🏆 胜率:           0.0%
  📊 夏普比率:       -1.25
```

---

### 🔹 模拟交易 (V0.4)

#### `python main.py trade -s 000725`
运行策略并执行**虚拟买卖**（非真实资金）。

交易规则：
- 💰 初始资金 ¥1000
- 📦 最大持仓 2 只，单只 ≤ ¥500
- 💳 单笔 100~500 元（A股 100 股整手，故实际可交易价格约 ¥1~5）
- 🚫 禁止满仓单股、连续补仓、追涨

```
💼 模拟交易执行结果 — 000725
  🟢 信号: BUY — 价格站上20MA | 5MA金叉20MA
  ✅ 已执行: BUY 100股 @ ¥4.02

  💼 虚拟账户
  💰 当前现金:    ¥592.80
  📊 持仓市值:    ¥402.00
  📈 总资产:      ¥994.80
```

#### `python main.py trade run -t 10`
**完整日运行**：先检查现有持仓是否触发卖出，再扫描 Top 候选股执行买入。
不带 `-t` 时默认扫描 10 只，也可用 `-s 000725` 只处理指定股票。

```
💼 模拟交易 日运行 — 2026-08-05
  🔍 持仓检查: 卖出 0 笔
  📊 扫描候选 Top 3: 000725、002131、600667
  ...
  📋 今日执行: 买入 1 笔 / 卖出 0 笔
```

#### `python main.py trade status`
查看当前虚拟账户状态、持仓明细和交易记录。

#### `python main.py trade reset`
重置虚拟账户，归零所有持仓和交易记录。

---

### 🔹 AI辅助分析 (V0.5)

#### `python main.py analyze market`
扫描主要指数（上证/深证/创业板/科创50），判断市场状态并给出综合建议。

```
🌍 市场环境分析
  上涨趋势 📈 上证指数
     现价: 11.11 | MA20: 10.65
     💡 顺势而为，持股为主
  下跌趋势 📉 科创50
     现价: 28.32 | MA20: 30.89
  💡 综合建议: ⚖️ 市场分化，控制仓位
```

#### `python main.py analyze review -s 000725`
交易复盘 — K线形态分析 + 回测绩效 + AI分析结论。

#### `python main.py analyze optimize -s 000725`
策略参数优化 — 自动扫描24组参数组合，推荐最佳止盈止损参数。

```
🔧 策略参数优化 — 000725
  🏆 最佳参数组合:
     止盈: 5% | 止损: 5% | RSI下限: 40
     预期收益: -6.10% | 夏普: -1.25
```

### 🔹 Web 控制台 (V0.7 → V0.8)

单文件 FastAPI 网页控制台 — 通过按钮执行 15 个 CLI 命令，实时流式输出。

```
# 启动（后台）
venv/bin/python web/run.py
# 打开浏览器 http://127.0.0.1:8000
```

| 端点 | 说明 |
|------|------|
| `GET /` | 网页控制台（单文件前端） |
| `GET /api/health` | 健康检查 + DB 统计 |
| `GET /api/commands` | 可用命令列表 |
| `GET /api/dashboard` | 仪表盘：账户 + 持仓 + 净值曲线 + 风控 + 日志 |
| `GET /api/report?date=` | 读取某天每日运行报告 |
| `POST /api/run` | 执行命令，SSE 流式输出 `{command, symbol, board, sync}` |

支持 `-b 主板/科创板/创业板/北交所` 板块过滤（scan、trade run）。
V0.8 新增 **Live Dashboard** 区块：净值曲线（内联 SVG）、风控面板
（regime / 仓位缩放 / 回撤 / 交易闸门）、持仓表、最近日志、最新每日报告；
`daily` 命令带 **Sync first** 开关（先增量同步 K 线再运行）。

---

### 🔹 每日自动调度 (V0.8)

#### `python main.py daily`
一键完成：增量同步 K 线 → 判断市场环境 → 组合风控 → 持仓检查/扫描买入 → 生成中文文本报告。

```
python main.py daily                    # 不联网同步，直接用现有数据
python main.py daily --sync             # 先增量同步 K 线再运行
python main.py daily -b 科创板 -t 10    # 指定板块/扫描数量
python main.py daily --show-report      # 运行后打印报告
```

调度流程 `scheduler.py`：
1. **增量同步** — 从数据库最新日期 +1 天拉取，避免全量重抓（`sync_lookback_days` 兜底）
2. **市场环境** — 多指数判定 trending / consolidating / bear（网络带 25s 超时）
3. **组合回测级风控** — `RiskManager` 三重闸门（见下）
4. **日运行** — 复用 `trade run` 逻辑，执行卖出/买入并记录净值点
5. **文本报告** — 写入 `reports/daily_YYYY-MM-DD.txt`

报告目录：`/opt/personal/reports/daily_YYYY-MM-DD.txt`

#### 组合级风控 (V0.8)

单只止盈/止损之上增加组合层控制（`trading/risk_manager.py`）：

| 闸门 | 规则 | 配置 |
|------|------|------|
| 市场环境仓位缩放 | trending 满仓 / consolidating 75% / bear 50% | `regime_position_scale` |
| 组合回撤暂停 | 从净值峰值回撤 ≥10% 暂停买入，收窄连续 2 天解除 | `max_drawdown_halt`, `halt_release_days` |
| 连续亏损冷却 | 连续 2 笔亏损暂停买入 3 天（到期日当天恢复） | `consecutive_loss_limit`, `cooldown_days` |

#### 组合回测 (V0.8)

多标的同步回测 + 沪深300 基准对比：

```
python main.py backtest portfolio               # 用DB中有K线的全部标的
python main.py backtest portfolio -t 5          # 只用最近5只
python main.py backtest portfolio -p 3          # 最大持仓3只
python main.py backtest portfolio -s 000725,600519   # 指定标的池
```

- 多标的共用交易日历、共享最大持仓数，T+1、100股整手、万2.5/千1 手续费、0.1% 滑点
- 自动对齐沪深300区间计算基准收益与超额收益
- `PerformanceReport` 复用单股回测绩效口径

#### 增量数据同步 (V0.8)

`daily --sync` 会先增量同步 DB 中已有 K 线的标的（默认前 20 只，`SCHEDULER.sync_universe_limit`），
`sync_kline()` 从数据库最新日期 +1 天开始增量拉取，`(symbol, date)` 唯一去重，已是最新则跳过。

---

## ⚙️ 策略说明

### 策略A: 低风险趋势策略

```
📗 买入条件（同时满足4项）:
   ① 价格站上20日均线
   ② 5日均线上穿20日均线（金叉）
   ③ RSI 处于 40~70
   ④ 量比 > 1.2

📕 卖出条件（满足任一）:
   a. 止盈 +5%
   b. 止损 -5%
   c. 趋势破坏（死叉 或 跌破20MA）
```

### 策略B: 低价轮动策略

```
🏆 每日全市场扫描:
   - 价格 3~15 元
   - 近20日上涨趋势
   - 成交活跃（≥1000万）
   - 综合评分 Top 10
```

---

## 🗂️ 项目结构

```
MiniQbot-Lite/
├── main.py                 # 📟 主入口 CLI
├── config.py               # ⚙️ 配置
├── scheduler.py            # 📅 V0.8 每日自动调度
├── CHANGELOG.md            # 📝 更新日志
│
├── data/
│   └── data_fetcher.py     # 📥 数据中心 (含增量同步)
│
├── database/
│   └── db_manager.py       # 🗄️ 数据库
│
├── screen/
│   ├── stock_screener.py   # 🔍 股票筛选
│   └── board.py            # 🧭 板块识别 (主板/科创板/创业板/北交所)
│
├── strategy/               # V0.2 策略系统
│   ├── base.py             #    BaseStrategy
│   ├── indicators.py       #    技术指标
│   ├── trend_strategy.py   #    📗 低风险趋势
│   └── rotation_strategy.py # 🏆 低价轮动
│
├── signals/                # V0.2 信号引擎
│   └── signal_engine.py
│
├── backtest/               # V0.3 回测系统
│   ├── backtest_engine.py  #    单股回测引擎
│   ├── portfolio_backtest.py # 🧺 V0.8 组合回测 (含基准对比)
│   └── performance.py      #    绩效统计
│
├── trading/                # V0.4 模拟交易
│   ├── virtual_account.py  #    💼 虚拟账户
│   ├── paper_trader.py     #    📊 交易引擎 (V0.8 接入风控+净值)
│   ├── risk_manager.py     #    🛡️ V0.8 组合级风控
│   └── journal.py          #    📋 交易日志
│
├── analysis/               # V0.5 AI分析
│   ├── market_analyzer.py  #    🌍 市场环境
│   ├── trade_review.py     #    🔍 交易复盘
│   └── strategy_advisor.py #    🔧 策略优化
│
├── web/                    # V0.7 Web控制台
│   ├── app.py              #    FastAPI 后端 (SSE + dashboard/report)
│   ├── run.py              #    启动脚本 (uvicorn :8000)
│   └── static/index.html   #    单文件前端 (V0.8 Live Dashboard)
│
├── reports/                # 📄 每日运行报告
├── storage/                # 💾 数据库文件
└── logs/                   # 📋 运行日志
```

---

## 🛤️ 开发路线

| 版本 | 内容 | 状态 |
|------|------|------|
| V0.1 | 基础框架: 数据 + 数据库 + 筛选 | ✅ |
| V0.2 | 策略系统: 趋势/轮动 + 信号引擎 | ✅ |
| V0.3 | 回测系统: 历史模拟 + 绩效统计 | ✅ |
| V0.4 | 模拟交易: 虚拟账户 + 实盘模拟 | ✅ |
| V0.5 | AI分析: 市场/复盘/优化 | ✅ |
| V0.6 | 板块过滤 + 模拟交易修复 | ✅ |
| V0.7 | Web控制台: FastAPI + 流式终端 | ✅ |
| **V0.8** | **增量同步 + 每日调度 + 组合风控 + 组合回测 + Live Dashboard** | **🟢 当前版本** |
| V1.0 | 定时任务 (cron) + 投资报告推送 | 📅 规划中 |

---

## 📐 设计原则

1. **模块化** — 每个模块独立，方便扩展
2. **先模拟后实盘** — 全部虚拟交易，安全第一
3. **不预测市场** — 只做条件判断和风险控制
4. **保护本金优先** — 单只最大亏损 ≤ 20元
5. **所有交易可追踪** — 每笔都有日志和原因

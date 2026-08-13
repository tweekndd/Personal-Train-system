# MiniQbot-Lite 更新日志

## V0.8 — 2026-08-06 — 增量同步 / 每日调度 / 组合风控 / 组合回测 / Live Dashboard

### 新增
- **增量数据同步** (`data/data_fetcher.py`)
  - `sync_kline()` — 从数据库最新日期 +1 天增量拉取，`(symbol, date)` 唯一去重，已最新则跳过
  - `sync_klines()` — 批量同步（重试 + 间隔），通过 `daily --sync` 触发
- **每日自动调度** (`scheduler.py`)
  - `DailyScheduler` — 同步 → 市场环境判断 → 组合风控 → 日运行 → 中文文本报告
  - `_call_with_timeout()` — 守护线程超时辅助，杜绝网络卡死挂起
  - CLI: `python main.py daily [--sync] [-b 板块] [-t N] [--show-report]`
- **组合级风控** (`trading/risk_manager.py`)
  - 市场环境仓位缩放（trending 1.0 / consolidating 0.75 / bear 0.5）
  - 组合回撤暂停（峰值回撤 ≥10% 停买，收窄连续 2 天解除）
  - 连续亏损冷却（连续 2 笔亏损停买 3 天，到期日当天恢复）
  - `to_dict/load_dict/snapshot()` 持久化与仪表盘展示
- **组合回测** (`backtest/portfolio_backtest.py`)
  - 多标的同步回测、共享最大持仓、T+1、100股整手、万2.5/千1/0.1% 滑点
  - 沪深300 基准对齐 + 超额收益对比
  - CLI: `python main.py backtest portfolio [-t N] [-p N] [-s a,b,c]`
- **Web Live Dashboard** (`web/app.py` + `web/static/index.html`)
  - `GET /api/dashboard`、`GET /api/report?date=` 新端点
  - 前端新增净值曲线 / 风控面板 / 持仓表 / 最近日志 / 每日报告区块
  - `daily`、`portfolio` 命令卡片 + **Sync first** 开关
- **测试** (`tests/test_v08.py`) — 16 个用例覆盖 RiskManager / PortfolioBacktest / web argv / 调度超时

### 修复
- `RiskManager.reset()` — 未重置 `regime` 字段，导致账户重置后仍残留历史市场环境
- 旧测试 `_make_trader()` — 增加 `risk.reset()`，隔离真实持久化状态
- Web 调度卡死 — 全链路使用守护线程超时，进程可正常退出

### 变更
- `config.py` — 新增 `RISK_MANAGEMENT`、`SCHEDULER` 配置块
- `paper_trader.py` — 接入 RiskManager（买入闸门 + 仓位缩放 + 净值曲线）
- `main.py` — 升级至 V0.8，增加 `daily`、`sync`、`backtest portfolio` 命令
- `db_manager.py` — 增加 `get_latest_kline_date()`、`get_symbols_with_klines()`
- README — V0.8 章节（调度/风控/组合回测/仪表盘）

---

## V0.6 — 2026-07-28 — 工程化加固

### 新增
- **单元测试** (`tests/`)
  - `test_core.py` — 15 个测试用例覆盖 indicators / VirtualAccount / BacktestEngine / DataValidator
  - 运行: `python -m pytest tests/ -v`
- **数据质量校验** (`data/validator.py`)
  - `validate_kline()` — 检查非正价格、缺失成交量、日期排序、异常跳空、重复日期
  - `assert_kline_valid()` — 断言式校验
- **K线可视化** (`charts/`)
  - `plot_kline_with_signals()` — mplfinance 生成带买卖点标记的 K 线图
  - 使用方法: `python main.py analyze review -s 000725` 将自动生成图表
- **Walk-forward 参数优化** (`analysis/walk_forward.py`)
  - 3 折时间序列分割：前段训练、后段验证
  - 参数稳定性评估：统计各折最优参数出现频率
  - CLI: `python main.py analyze wfo -s 000725`
- **合规声明** (`analysis/disclaimer.py`)
  - 所有报告输出底部自动附加风险提示
- **T+1 交易约束**
  - 回测引擎 `_execute_sell()` 检查当日买入不可卖出
  - 虚拟账户 `sell()` 检查 `buy_date == today` 时拒绝执行
- **新股过滤** — `StockScreener` 增加上市不满 60 天股票的备注说明

### 修复
- `compute_rsi()` — 修复纯涨/纯跌时除零导致的 NaN（极值正确返回 100/0）
- `.gitignore` — 增加 `.pytest_cache/`、`charts/*.png` 排除规则
- **`StrategyAdvisor.scan_parameters()`** — 修复默认只取 90 天数据导致策略来不及触发、所有参数返回 0 交易的问题。改为默认 240 天
- **`WalkForwardOptimizer.optimize()`** — 同上，增加默认 365 天数据
- **Config 不生效** — `TrendStrategy` 和 `RotationStrategy` 的默认参数改为从 `config.py` 读取。之前修改 config.py 不改变任何行为，需要修改策略本身的硬编码
- **模拟交易无持久化** — `VirtualAccount` 增加 `save()/load()`，`PaperTrader` 每次交易后自动保存到 `storage/paper_account.json`，重启不丢失
- **禁止补仓缺失** — `PaperTrader._try_buy()` 增加检查：已持仓的股票不再重复买入
- **轮动策略"20日趋势"误标** — `_score()` 明确标注当前使用的是当日涨跌幅而非20日涨幅，因行情快照数据限制
- **`requirements.txt` mplfinance** — 注释掉不可安装的版本号，加说明
- **未接入模块** — `disclaimer.py`（风险提示）已接入回测/复盘/优化输出；`validator.py`（数据校验）已接入 fetch 命令

### 变更
- `main.py` — 升级至 V0.6，增加 `analyze wfo` 子命令
- `requirements.txt` — 增加 `pytest`、`mplfinance`
- 所有核心模块增加 T+1 日期记录

---

## V0.5 — 2026-07-28 — AI辅助分析

### 新增
- **分析模块** (`analysis/`)
  - `market_analyzer.py` — 市场环境分析（判断趋势/震荡/熊市，综合建议）
  - `trade_review.py` — 交易复盘（K线形态分析 + 回测绩效 + AI结论）
  - `strategy_advisor.py` — 策略参数优化（24组参数扫描，自动推荐最佳组合）
- **CLI 命令**
  - `python main.py analyze market` — 市场环境分析
  - `python main.py analyze review -s 000725` — 交易复盘
  - `python main.py analyze optimize -s 000725` — 策略参数优化

### 变更
- `main.py` — 升级至 V0.5，增加 analyze 命令组

---

## V0.4 — 2026-07-28 — 模拟交易系统

### 新增
- **模拟交易模块** (`trading/`)
  - `virtual_account.py` — 虚拟账户（1000元本金，现金/持仓/盈亏管理）
  - `paper_trader.py` — 模拟交易引擎（策略驱动虚拟执行）
  - `journal.py` — 交易日志（记录每笔决策及原因）
- **CLI 命令**
  - `python main.py trade -s 000725` — 模拟买入/卖出
  - `python main.py trade status` — 查看账户和持仓
  - `python main.py trade reset` — 重置虚拟账户
- **交易规则**
  - 最大持仓2只，单只≤500元
  - 单笔100-300元，禁止满仓单股
  - 手续费万2.5（最低5元）+ 印花税千1 + 滑点0.1%

### 变更
- `main.py` — 升级至 V0.4，增加 trade 命令组

---

## V0.3 — 2026-07-28 — 回测系统

### 新增
- **回测模块** (`backtest/`)
  - `backtest_engine.py` — 回测引擎，支持模拟真实交易
  - `performance.py` — 绩效统计（收益率/回撤/胜率/夏普）
- **CLI 命令**
  - `python main.py backtest -s 000725` — 回测指定股票
  - `python main.py backtest list` — 查看可回测的策略
- **交易成本模型**
  - 手续费万2.5 + 印花税千1 + 滑点0.1%

### 修复
- `DataFetcher.get_daily_kline()` — 增加 `stock_zh_a_daily()` 备用接口

### 变更
- `main.py` — 升级至 V0.3，增加 backtest 命令组

---

## V0.2 — 2026-07-28 — 策略系统

### 新增
- **策略模块** (`strategy/`)
  - `indicators.py` — 纯 pandas 技术指标：MA、RSI、金叉/死叉检测
  - `base.py` — `BaseStrategy` 抽象基类，统一 `on_market_data()`, `generate_signal()`, `buy()`, `sell()` 接口
  - `trend_strategy.py` — 策略A: 低风险趋势策略（20日均线金叉 + RSI 40-70 + 量能确认）
  - `rotation_strategy.py` — 策略B: 低价轮动策略（3-15元区间，20日上涨趋势，每日Top10）
- **信号模块** (`signals/`)
  - `signal_engine.py` — 信号引擎，管理多策略信号生成、合并与冲突解决
- **CLI 命令**
  - `python main.py strategy signal` — 对指定股票生成交易信号
  - `python main.py strategy scan` — 全市场扫描，输出各策略候选股
  - `python main.py strategy list` — 列出所有可用策略
- **配置文件更新** — `config.py` 新增策略参数

### 修复
- `RotationStrategy._score()` — 修复 `p = self.params` 缺失导致的 NameError
- `signal/` → `signals/` — 重命名避免与 Python 标准库 `signal` 模块名冲突

### 变更
- `config.py` — 新增策略相关配置（均线周期、RSI阈值、止盈止损等）
- `main.py` — 升级至 V0.2，增加 strategy 子命令组
- `README.md` — 重写使用说明，增加完整命令参考 + 每个命令的输出示例

---

## V0.1 — 2026-07-28 — 基础框架

### 新增
- **数据中心** (`data/data_fetcher.py`) — akshare 三路容错获取A股数据
- **数据库模块** (`database/db_manager.py`) — SQLite + SQLAlchemy ORM，stock_info + daily_kline 表
- **股票筛选器** (`screen/stock_screener.py`) — 价格区间/流动性/风险标签过滤
- **CLI** (`main.py`) — init / scan / fetch / status / run 命令
- **配置** (`config.py`) — 资金管理参数、筛选阈值

# insure_agent

面向个人、本地 Mac 的 A 股日频/周频投研助手。系统把可信数据、可复现研究、
确定性风控、人工审批和模拟执行放在同一条可审计链路中；真实交易始终关闭。

## 当前架构

```text
Provider (sample / AkShare / Tushare)
  → 不可变 canonical CSV.GZ + DataManifest + 数据质量门禁
  → 确定性动量基线 / Qlib Alpha158 + LightGBM
  → 目标组合
  → SQLite 当前账户与持仓
  → 目标持仓 - 当前持仓 = OrderPlan
  → 确定性风控
  → 绑定计划校验和的限时人工审批
  → T+1 / 整手 / 现金 / 停牌 / 涨跌停模拟执行
  → NAV、日报、RunManifest、完整批次发布
```

`run_id`、`data_version`、`config_hash`、`code_version` 和输入校验和贯穿
研究、计划、风控、审批和执行。运行目录不可变；失败阶段产生新的 attempt，
只有全部完成的运行才能原子更新 `artifacts/latest.json`。

主要模块：

- `src/quant_agent/data`：可替换数据提供商、七类 canonical 数据集、质量检查、
  不可变快照和真实 Qlib 二进制布局转换。
- `src/quant_agent/research`：无未来数据的动量基线、真实 Qlib 工作流适配、
  时间序列切分、预测、成本后指标和基准比较。
- `src/quant_agent/execution`：SQLite 账户账本、目标差额订单、T+1、整手、
  费用、幂等订单、成交和每日净值。
- `src/quant_agent/risk`：数据、可交易性、现金、仓位、集中度、换手率、
  订单金额、回撤、审批和 Kill Switch。
- `src/quant_agent/workflow`：可恢复的日频状态机和一致日报。
- `src/quant_agent/schemas`：跨模块 Pydantic 契约及旧版载荷兼容字段。

## 安装

要求 Python `>=3.10,<3.14`。开发与确定性 sample 流程：

```bash
python -m pip install -e .[dev]
```

使用 AkShare、Tushare 或 Qlib：

```bash
python -m pip install -e '.[dev,research]'
```

也可以让 `uv` 管理隔离环境：

```bash
uv run --python 3.13 --extra dev quant-agent status
```

## 可信日频流程

先用固定 sample 数据验证完整闭环：

```bash
quant-agent run daily --trade-date 2026-07-29 --provider sample
quant-agent run show --run-id <run_id>
quant-agent approval grant --run-id <run_id> --approver <name>
quant-agent paper run --run-id <run_id>
quant-agent run show --run-id <run_id>
```

首次命令会运行至 `AWAITING_APPROVAL` 并输出 `run_id`、预执行报告和下一条
命令。审批绑定风险通过后的 `plan_checksum`，默认 60 分钟失效。执行前会再次
检查审批、数据版本、计划校验和与 Kill Switch。

失败后从第一个未完成阶段恢复：

```bash
quant-agent run resume --run-id <run_id>
```

独立同步数据：

```bash
quant-agent data sync --trade-date 2026-07-29 --provider sample
quant-agent data sync --trade-date 2026-07-29 --provider akshare
TUSHARE_TOKEN='<secret>' quant-agent data sync \
  --trade-date 2026-07-29 --provider tushare
```

Token 只从环境变量读取，不写入配置、产物或日志。AkShare 当前适配器缺少
可信的复权因子、历史成分、停复牌和涨跌停覆盖，因此会被严格质量门禁拒绝；
这是触发切换 Tushare 的预设条件，不会静默使用不完整数据。

## 研究引擎

默认日常配置是 `configs/research/daily_momentum.yaml`，它提供可复现的简单
基线。`configs/research/qlib_alpha158_csi300.yaml` 是真实 Qlib
Alpha158 + LightGBM 候选配置：

```bash
quant-agent run daily \
  --trade-date 2026-07-29 \
  --provider tushare \
  --research-config configs/research/qlib_alpha158_csi300.yaml
```

Qlib 模式不会退回伪实现：缺少 `pyqlib`、模型依赖、足够长的快照或合法任务
配置时直接失败。候选模型不会自动晋级；必须人工比较简单基线、样本外稳定性、
IC/RankIC、换手与成本敏感性。

## 运行产物

```text
artifacts/
  data/snapshots/<trade_date>/<data_version>/*.csv.gz
  data/snapshots/<trade_date>/<data_version>/data_manifest.json
  data/qlib/<data_version>/
  runs/<run_id>/manifest.json
  research_runs/<run_id>/
  risk_runs/<run_id>/
  execution_runs/<run_id>/
  approvals/<run_id>/
  reports/<run_id>_{pre,final}_report.md
  portfolio.db
  latest.json
  latest_legacy.json
```

`latest.json` 只指向同一个已完成运行的连贯产物；旧的分步命令写
`latest_legacy.json`，防止两个批次混合。`artifacts/` 是本地运行状态，不应
提交到 Git。

## 配置与安全边界

配置优先级是：CLI 显式参数 → 研究/风险/执行/数据配置 → 环境配置 →
Pydantic 默认值。最终解析值保存在 `RunManifest.provenance.resolved_config`
并在阶段运行时固化为不可变配置快照。

- paper 和人工审批是唯一受支持的严格执行模式。
- `runtime.allow_live_trading` 默认为 `false`，项目没有真实券商提交代码。
- 创建 `artifacts/KILL_SWITCH` 会在计划、风控和执行前阻断流程。
- 费用表包含 `effective_from`；不存在覆盖交易日的费率时拒绝生成计划。
- 日线模拟只记录完整成交或当日未成交，不伪造部分成交。
- LLM/RD-Agent、vn.py、常驻服务、微服务、队列和无人值守实盘均未启用。

详细操作与故障处理见 [运行手册](docs/runbook.md)，升级与回滚见
[迁移说明](docs/migration_trustworthy_daily.md)，当前边界见
[已知限制](docs/known_limitations.md)。

## 兼容命令

原演示流程至少保留一个版本：

```bash
quant-agent run pipeline --mode paper
quant-agent data pull --sample
quant-agent data convert
quant-agent research qlib
quant-agent risk validate
quant-agent paper run
quant-agent report generate
```

这些命令只用于旧脚本兼容，不具备严格批次、SQLite 账户和审批保证。新任务应
使用 `run daily`。

## 开发检查

```bash
uv run --python 3.13 --extra dev pytest -q
uv run --python 3.13 --extra dev ruff check src tests scripts
uv run --python 3.13 --extra dev mypy src
```

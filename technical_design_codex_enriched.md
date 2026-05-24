# A 股实盘型智能交易系统详细技术设计（Codex 实施版）

> 技术栈：RD-Agent + Qlib + vn.py + 自研风控 Agent  
> 目标市场：A 股  
> 推荐先实现：研究闭环 + 风控审查 + vn.py 模拟盘  
> 不建议第一版实现：无人值守实盘自动下单

---

## 0. 文档用途

本文档用于指导 Codex 或工程团队实施一个面向 A 股的智能量化系统。文档重点不是宏观架构说明，而是把项目拆成可以落地的模块、接口、数据契约、目录结构、配置文件、CLI 命令、测试用例和验收标准。

系统目标是先在本地 Mac 或开发服务器上完成以下闭环：

```text
A 股数据获取
    ↓
Qlib 数据转换
    ↓
RD-Agent / Qlib 研究与回测
    ↓
目标仓位生成
    ↓
自研风控 Agent 审查
    ↓
vn.py 模拟盘执行
    ↓
交易日志、风控日志、研究报告
```

后续再将执行层迁移到 Windows/Linux 交易服务器，接入真实券商网关。所有实盘相关能力必须默认关闭，必须经过显式配置、人工审批和风控放行。

---

## 1. 总体设计原则

### 1.1 分层隔离

RD-Agent、Qlib、风控 Agent 和 vn.py 不应放在一个大进程中。各模块通过文件协议、REST/gRPC 或消息队列通信。

推荐第一阶段使用文件协议，降低集成复杂度：

```text
research/outputs/<run_id>/target_positions.json
risk/outputs/<run_id>/approved_positions.json
execution/outputs/<run_id>/orders.json
execution/outputs/<run_id>/trades.json
```

第二阶段再引入 Redis Stream、ZeroMQ 或 gRPC。

### 1.2 配置优先

策略参数、数据源、风控阈值、运行模式、券商网关配置均不得硬编码。所有可变参数集中放在 `configs/` 目录。

必须支持以下运行模式：

| 模式 | 用途 | 实盘 |
|---|---|---:|
| `dev` | 本地开发 | 否 |
| `research` | 回测研究 | 否 |
| `paper` | 模拟盘 | 否 |
| `live_shadow` | 影子实盘 | 否 |
| `live` | 真实实盘 | 是 |

`live` 模式必须默认不可用。需要同时满足以下条件才允许启动：

```text
ENABLE_LIVE_TRADING=true
risk.live_enabled=true
approval.required=false 或存在有效审批单
broker.gateway 已配置
kill_switch=false
```

### 1.3 风控硬规则优先

LLM 只能用于策略解释、异常归因和报告生成。LLM 不允许绕过硬风控规则。

风控 Agent 的决策顺序：

```text
数据新鲜度检查
    ↓
市场状态检查
    ↓
标的可交易性检查
    ↓
账户与持仓检查
    ↓
仓位与集中度检查
    ↓
订单级检查
    ↓
人工审批检查
    ↓
输出批准、调整或拒绝
```

### 1.4 可审计与可复现

每次研究、风控和交易都必须有唯一 `run_id`。所有输入、输出、模型版本、配置快照、代码版本、数据版本都必须记录。

推荐 `run_id` 格式：

```text
YYYYMMDD-HHMMSS-<mode>-<strategy_id>-<short_hash>
```

示例：

```text
20260524-093000-research-lgb_alpha158-a1b2c3
```

---

## 2. 推荐仓库结构

Codex 应按以下结构创建或补全仓库。

```text
project_root/
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example
├── .gitignore
│
├── configs/
│   ├── env/
│   │   ├── dev.yaml
│   │   ├── research.yaml
│   │   ├── paper.yaml
│   │   ├── live_shadow.yaml
│   │   └── live.yaml
│   ├── data/
│   │   ├── tushare.yaml
│   │   ├── akshare.yaml
│   │   └── qlib.yaml
│   ├── research/
│   │   ├── baseline_lgb_alpha158.yaml
│   │   ├── rd_agent_fin_factor.yaml
│   │   └── rd_agent_fin_quant.yaml
│   ├── risk/
│   │   ├── default.yaml
│   │   ├── conservative.yaml
│   │   └── live.yaml
│   └── execution/
│       ├── vnpy_mock.yaml
│       └── vnpy_live.yaml
│
├── src/
│   └── quant_agent/
│       ├── __init__.py
│       ├── cli.py
│       ├── common/
│       │   ├── config.py
│       │   ├── logging.py
│       │   ├── paths.py
│       │   ├── time.py
│       │   └── ids.py
│       ├── schemas/
│       │   ├── market.py
│       │   ├── research.py
│       │   ├── risk.py
│       │   ├── execution.py
│       │   └── audit.py
│       ├── data/
│       │   ├── adapters/
│       │   │   ├── base.py
│       │   │   ├── tushare_adapter.py
│       │   │   ├── akshare_adapter.py
│       │   │   └── local_csv_adapter.py
│       │   ├── validators.py
│       │   ├── calendar.py
│       │   ├── symbol.py
│       │   └── qlib_converter.py
│       ├── research/
│       │   ├── qlib_runner.py
│       │   ├── rdagent_runner.py
│       │   ├── factor_registry.py
│       │   ├── model_registry.py
│       │   ├── portfolio_builder.py
│       │   └── report_writer.py
│       ├── risk/
│       │   ├── engine.py
│       │   ├── service.py
│       │   ├── rules/
│       │   │   ├── base.py
│       │   │   ├── data_freshness.py
│       │   │   ├── tradability.py
│       │   │   ├── position_limit.py
│       │   │   ├── industry_limit.py
│       │   │   ├── liquidity.py
│       │   │   ├── drawdown.py
│       │   │   ├── t_plus_one.py
│       │   │   ├── cash.py
│       │   │   └── kill_switch.py
│       │   └── reports.py
│       ├── execution/
│       │   ├── bridge.py
│       │   ├── sizing.py
│       │   ├── order_router.py
│       │   ├── vnpy_adapter.py
│       │   ├── mock_gateway.py
│       │   └── reconciliation.py
│       ├── storage/
│       │   ├── db.py
│       │   ├── repositories.py
│       │   └── migrations/
│       └── observability/
│           ├── events.py
│           ├── metrics.py
│           └── audit_logger.py
│
├── scripts/
│   ├── init_project.py
│   ├── pull_data.py
│   ├── convert_to_qlib.py
│   ├── run_qlib_backtest.py
│   ├── run_rdagent.py
│   ├── validate_targets.py
│   ├── run_paper_trading.py
│   └── generate_report.py
│
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
│
├── artifacts/
│   ├── data/
│   ├── research_runs/
│   ├── risk_runs/
│   ├── execution_runs/
│   └── reports/
│
├── docs/
│   ├── technical_design.md
│   ├── local_mac_setup.md
│   ├── runbook.md
│   ├── risk_rules.md
│   └── live_trading_checklist.md
└── docker/
    ├── docker-compose.dev.yaml
    ├── Dockerfile.research
    ├── Dockerfile.risk
    └── Dockerfile.execution
```

---

## 3. 本地 Mac 可实施范围

### 3.1 Mac 本地推荐目标

当前 Mac 电脑适合完成：

```text
Qlib 本地研究
A 股日频数据处理
RD-Agent Linux VM 实验
风控 Agent 原型
vn.py 模拟盘
文件协议联调
报告生成
测试体系
```

不建议在 Mac 上完成：

```text
真实 A 股实盘下单
券商网关长期稳定运行
全 A 分钟级大规模回测
高频交易
无人值守交易
```

### 3.2 本地环境分离

建议创建三个 Conda 环境。

```bash
conda create -n quant-research python=3.11 -y
conda create -n risk-agent python=3.11 -y
conda create -n vnpy python=3.13 -y
```

RD-Agent 建议放在 Linux VM 或容器环境中：

```text
Mac Host
└── Ubuntu VM
    ├── rdagent
    ├── qlib
    └── docker sandbox
```

### 3.3 Mac 快速启动命令

```bash
# 1. 安装基础依赖
brew install git wget curl cmake libomp redis postgresql

# 2. 初始化 Python 环境
conda activate quant-research
pip install -e .[research]

# 3. 初始化目录
make init

# 4. 下载或导入样例数据
make data.pull SAMPLE=1

# 5. 转换为 Qlib 格式
make data.convert

# 6. 跑基线回测
make research.baseline

# 7. 生成目标仓位
make research.targets

# 8. 风控检查
make risk.validate

# 9. 模拟盘执行
make paper.run

# 10. 生成报告
make report.latest
```

---

## 4. 配置体系

### 4.1 `.env.example`

```bash
# Runtime
APP_ENV=dev
PROJECT_ROOT=.
ARTIFACT_DIR=./artifacts
TZ=Asia/Shanghai

# Data provider
TUSHARE_TOKEN=
AKSHARE_ENABLED=true
RQDATA_ENABLED=false

# LLM / RD-Agent
OPENAI_API_KEY=
CHAT_MODEL=gpt-4.1
EMBEDDING_MODEL=text-embedding-3-small
RDAGENT_WORKDIR=./artifacts/rdagent

# Safety
ENABLE_LIVE_TRADING=false
GLOBAL_KILL_SWITCH=false
REQUIRE_MANUAL_APPROVAL=true

# Storage
DATABASE_URL=sqlite:///./artifacts/quant_agent.db
MLFLOW_TRACKING_URI=./artifacts/mlruns

# Execution
VNPY_MODE=mock
VNPY_GATEWAY=mock
```

### 4.2 `configs/env/dev.yaml`

```yaml
app:
  env: dev
  timezone: Asia/Shanghai
  artifact_dir: artifacts
  log_level: INFO

runtime:
  communication_mode: file
  allow_live_trading: false
  require_manual_approval: true

storage:
  database_url: sqlite:///artifacts/quant_agent.db
  mlflow_tracking_uri: artifacts/mlruns

paths:
  raw_data: artifacts/data/raw
  qlib_data: artifacts/data/qlib/cn_data
  research_runs: artifacts/research_runs
  risk_runs: artifacts/risk_runs
  execution_runs: artifacts/execution_runs
  reports: artifacts/reports
```

### 4.3 `configs/risk/default.yaml`

```yaml
risk:
  profile: default
  enabled: true
  live_enabled: false

limits:
  max_gross_exposure: 0.95
  max_single_weight: 0.05
  max_industry_weight: 0.25
  max_turnover_per_day: 0.30
  max_volume_participation: 0.05
  min_cash_ratio: 0.03
  max_drawdown_stop: 0.20
  daily_loss_stop: 0.05

tradability:
  block_st: true
  block_suspended: true
  block_limit_up_buy: true
  block_limit_down_sell: true
  enforce_t_plus_one: true
  min_lot_size: 100

approval:
  require_manual_approval: true
  approval_ttl_minutes: 60

kill_switch:
  enabled: true
  file_path: artifacts/KILL_SWITCH
```

### 4.4 `configs/research/baseline_lgb_alpha158.yaml`

```yaml
research:
  strategy_id: lgb_alpha158_csi300_v1
  universe: CSI300
  benchmark: SH000300
  train_start: 2015-01-01
  train_end: 2021-12-31
  valid_start: 2022-01-01
  valid_end: 2023-12-31
  test_start: 2024-01-01
  test_end: 2025-12-31

qlib:
  provider_uri: artifacts/data/qlib/cn_data
  region: cn

features:
  library: Alpha158
  neutralize:
    industry: true
    market_cap: true

model:
  type: LightGBM
  params:
    num_leaves: 31
    learning_rate: 0.01
    n_estimators: 1000
    subsample: 0.8
    colsample_bytree: 0.8

portfolio:
  method: topk_dropout
  topk: 50
  n_drop: 10
  rebalance_freq: daily
```

---

## 5. 数据模型与数据契约

### 5.1 统一标的代码

系统内部统一使用：

```text
600519.SH
000001.SZ
300750.SZ
```

Qlib 内部可按其要求转换为对应格式，但进入/离开 Qlib 时必须通过 `symbol.py` 做标准化。

```python
# src/quant_agent/data/symbol.py
from __future__ import annotations


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to 6-digit code + exchange suffix.

    Examples:
        600519 -> 600519.SH
        000001 -> 000001.SZ
        SH600519 -> 600519.SH
        SZ000001 -> 000001.SZ
    """
    s = symbol.strip().upper().replace(" ", "")
    if s.endswith(".SH") or s.endswith(".SZ"):
        return s
    if s.startswith("SH"):
        return f"{s[2:]}.SH"
    if s.startswith("SZ"):
        return f"{s[2:]}.SZ"
    if s.startswith(("5", "6", "9")):
        return f"{s}.SH"
    return f"{s}.SZ"
```

### 5.2 核心数据表

必须优先实现以下数据表。

| 表名 | 频率 | 用途 |
|---|---|---|
| `daily_bar` | 日频 | 行情 |
| `adjust_factor` | 日频 | 复权 |
| `instrument_status` | 日频 | 停牌 |
| `st_status` | 日频 | ST |
| `limit_price` | 日频 | 涨跌停 |
| `industry` | 低频 | 行业 |
| `index_member` | 日频 | 股票池 |
| `fundamental` | 财报 | 基本面 |

### 5.3 `daily_bar` schema

```python
# src/quant_agent/schemas/market.py
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class DailyBar(BaseModel):
    trade_date: date
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pre_close: Decimal | None = None
    volume: Decimal
    amount: Decimal
    adj_factor: Decimal | None = None
    source: str
    updated_at: datetime
```

### 5.4 `instrument_status` schema

```python
class InstrumentStatus(BaseModel):
    trade_date: date
    symbol: str
    is_suspended: bool = False
    is_st: bool = False
    is_delisted: bool = False
    list_date: date | None = None
    delist_date: date | None = None
```

### 5.5 `limit_price` schema

```python
class LimitPrice(BaseModel):
    trade_date: date
    symbol: str
    limit_up: Decimal
    limit_down: Decimal
```

### 5.6 数据新鲜度规则

A 股日频数据在收盘后更新。系统需要区分：

```text
盘前研究数据
盘中行情数据
盘后结算数据
```

风控 Agent 必须拒绝过期行情。例如：

```python
if market_state.as_of < expected_latest_bar_time:
    raise DataStalenessError("market data is stale")
```

---

## 6. 数据适配器实现

### 6.1 适配器接口

```python
# src/quant_agent/data/adapters/base.py
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd


class DataAdapter(ABC):
    @abstractmethod
    def fetch_daily_bar(self, start: date, end: date, symbols: list[str] | None = None) -> pd.DataFrame:
        pass

    @abstractmethod
    def fetch_adjust_factor(self, start: date, end: date, symbols: list[str] | None = None) -> pd.DataFrame:
        pass

    @abstractmethod
    def fetch_instrument_status(self, start: date, end: date) -> pd.DataFrame:
        pass

    @abstractmethod
    def fetch_limit_price(self, start: date, end: date, symbols: list[str] | None = None) -> pd.DataFrame:
        pass
```

### 6.2 本地 CSV 适配器

第一阶段建议先实现 `LocalCsvAdapter`，方便无 API key 的情况下测试。

```python
class LocalCsvAdapter(DataAdapter):
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def fetch_daily_bar(self, start, end, symbols=None):
        df = pd.read_parquet(self.base_dir / "daily_bar.parquet")
        df = df[(df["trade_date"] >= str(start)) & (df["trade_date"] <= str(end))]
        if symbols:
            df = df[df["symbol"].isin(symbols)]
        return df
```

### 6.3 数据校验

所有数据拉取后必须执行校验：

```python
# src/quant_agent/data/validators.py

def validate_daily_bar(df: pd.DataFrame) -> None:
    required = {"trade_date", "symbol", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {missing}")

    if df.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("duplicate daily bars detected")

    bad_price = df[(df["high"] < df["low"]) | (df["close"] <= 0)]
    if not bad_price.empty:
        raise ValueError("invalid price rows detected")
```

### 6.4 转换到 Qlib

Codex 应实现：

```text
scripts/convert_to_qlib.py
src/quant_agent/data/qlib_converter.py
```

输入：

```text
artifacts/data/raw/daily_bar.parquet
artifacts/data/raw/adjust_factor.parquet
artifacts/data/raw/instrument_status.parquet
```

输出：

```text
artifacts/data/qlib/cn_data/
```

转换前应自动生成股票池文件：

```text
instruments/csi300.txt
instruments/csi500.txt
instruments/all_a.txt
```

---

## 7. 研究模块实现

### 7.1 Qlib Runner

Codex 应实现 `QlibRunner`。

```python
# src/quant_agent/research/qlib_runner.py
from pathlib import Path
from dataclasses import dataclass


@dataclass
class QlibRunResult:
    run_id: str
    artifact_dir: Path
    metrics_path: Path
    target_positions_path: Path
    report_path: Path


class QlibRunner:
    def __init__(self, config_path: str, artifact_root: str):
        self.config_path = Path(config_path)
        self.artifact_root = Path(artifact_root)

    def run_backtest(self) -> QlibRunResult:
        """Run qlib workflow and export metrics + target positions.

        Must create:
        - metrics.json
        - predictions.parquet
        - target_positions.json
        - report.md
        """
        ...
```

### 7.2 研究输出目录

每次研究必须落盘到：

```text
artifacts/research_runs/<run_id>/
├── config_snapshot.yaml
├── code_version.json
├── data_version.json
├── predictions.parquet
├── portfolio_report.parquet
├── positions.parquet
├── metrics.json
├── target_positions.json
└── report.md
```

### 7.3 `metrics.json`

```json
{
  "run_id": "20260524-093000-research-lgb_alpha158-a1b2c3",
  "strategy_id": "lgb_alpha158_csi300_v1",
  "universe": "CSI300",
  "benchmark": "SH000300",
  "period": {
    "start": "2024-01-01",
    "end": "2025-12-31"
  },
  "metrics": {
    "annual_return": 0.123,
    "annual_volatility": 0.185,
    "sharpe": 0.92,
    "max_drawdown": -0.108,
    "information_ratio": 0.73,
    "turnover": 0.18,
    "rank_ic_mean": 0.032,
    "rank_ic_ir": 0.42
  }
}
```

### 7.4 目标仓位生成

Qlib/RD-Agent 不直接输出订单，只输出目标仓位。

```json
{
  "schema_version": "1.0",
  "run_id": "20260524-093000-research-lgb_alpha158-a1b2c3",
  "strategy_id": "lgb_alpha158_csi300_v1",
  "trade_date": "2026-05-25",
  "generated_at": "2026-05-24T17:00:00+08:00",
  "universe": "CSI300",
  "benchmark": "SH000300",
  "positions": [
    {
      "symbol": "600519.SH",
      "target_weight": 0.035,
      "score": 1.82,
      "rank": 1,
      "reason": "high alpha score"
    }
  ],
  "metadata": {
    "model_uri": "artifacts/models/lgb_alpha158_v1",
    "config_uri": "configs/research/baseline_lgb_alpha158.yaml"
  }
}
```

### 7.5 Portfolio Builder

Codex 应实现 `PortfolioBuilder`。

职责：

```text
读取预测分数
应用股票池
应用初步约束
生成目标权重
保存 target_positions.json
```

伪代码：

```python
class PortfolioBuilder:
    def build_targets(self, predictions: pd.DataFrame, config: dict) -> TargetPositionRequest:
        preds = predictions.sort_values("score", ascending=False)
        selected = preds.head(config["portfolio"]["topk"])
        weight = min(1 / len(selected), config["portfolio"].get("max_single_weight", 0.05))
        positions = [
            TargetPosition(symbol=row.symbol, target_weight=weight, score=row.score, rank=i + 1)
            for i, row in enumerate(selected.itertuples())
        ]
        return TargetPositionRequest(..., positions=positions)
```

---

## 8. RD-Agent 集成

### 8.1 RD-Agent Runner

Codex 应实现一个薄封装，而不是重写 RD-Agent。

```python
# src/quant_agent/research/rdagent_runner.py
class RDAgentRunner:
    def __init__(self, config_path: str, workdir: str):
        self.config_path = Path(config_path)
        self.workdir = Path(workdir)

    def run_fin_factor(self) -> Path:
        """Run RD-Agent factor evolution and return output directory."""
        ...

    def run_fin_model(self) -> Path:
        """Run RD-Agent model evolution and return output directory."""
        ...

    def run_fin_quant(self) -> Path:
        """Run RD-Agent factor-model co-optimization."""
        ...
```

### 8.2 RD-Agent 输出归一化

RD-Agent 的输出应被统一转换为系统内部格式：

```text
RD-Agent raw output
    ↓
normalize_rdagent_output()
    ↓
research_runs/<run_id>/metrics.json
research_runs/<run_id>/target_positions.json
research_runs/<run_id>/report.md
```

### 8.3 RD-Agent 约束

RD-Agent 生成的代码必须进入隔离目录执行。

必须禁止：

```text
访问交易密钥
访问 live 配置
直接调用 vn.py 下单接口
写入 live execution 目录
修改风控规则
绕过人工审批
```

建议在 RD-Agent 工作目录使用只读挂载：

```text
只读：configs/research, artifacts/data/qlib
可写：artifacts/rdagent_runs/<run_id>
不可见：configs/execution/live.yaml, .env
```

---

## 9. 风控 Agent 详细实现

### 9.1 输入输出契约

输入：`TargetPositionRequest`

```python
# src/quant_agent/schemas/risk.py
from datetime import date, datetime
from pydantic import BaseModel, Field


class TargetPosition(BaseModel):
    symbol: str
    target_weight: float = Field(ge=0, le=1)
    score: float | None = None
    rank: int | None = None
    reason: str | None = None


class TargetPositionRequest(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    trade_date: date
    generated_at: datetime
    universe: str
    benchmark: str | None = None
    positions: list[TargetPosition]
    metadata: dict = {}
```

输出：`RiskDecision`

```python
class RiskViolation(BaseModel):
    rule_id: str
    severity: str
    symbol: str | None = None
    message: str
    original_value: float | str | None = None
    adjusted_value: float | str | None = None


class ApprovedPosition(BaseModel):
    symbol: str
    target_weight: float
    adjusted: bool = False
    reason: str | None = None


class RiskDecision(BaseModel):
    run_id: str
    strategy_id: str
    approved: bool
    decision: str  # APPROVE / ADJUST / REJECT
    positions: list[ApprovedPosition]
    violations: list[RiskViolation]
    generated_at: datetime
    require_manual_approval: bool = True
```

### 9.2 风控规则接口

```python
# src/quant_agent/risk/rules/base.py
from abc import ABC, abstractmethod


class RiskRule(ABC):
    rule_id: str
    severity: str

    @abstractmethod
    def evaluate(self, context: "RiskContext") -> list[RiskViolation]:
        pass

    def adjust(self, context: "RiskContext") -> None:
        """Optional adjustment. Hard reject rules should not adjust."""
        return None
```

### 9.3 风控规则清单

必须实现以下规则。

| 规则 | 阶段 | 动作 |
|---|---|---|
| 数据新鲜度 | 事前 | 拒绝 |
| ST 过滤 | 事前 | 拒绝 |
| 停牌过滤 | 事前 | 拒绝 |
| 涨停禁买 | 订单前 | 拒绝 |
| 跌停禁卖 | 订单前 | 拒绝 |
| T+1 限制 | 订单前 | 拒绝 |
| 单票仓位 | 事前 | 调整 |
| 行业集中度 | 事前 | 调整 |
| 总仓位 | 事前 | 调整 |
| 流动性 | 订单前 | 调整 |
| 现金比例 | 订单前 | 调整 |
| 最大回撤 | 事中 | 暂停 |
| 日内亏损 | 事中 | 暂停 |
| Kill Switch | 全局 | 拒绝 |

### 9.4 风控引擎流程

```python
class RiskEngine:
    def __init__(self, rules: list[RiskRule], config: RiskConfig):
        self.rules = rules
        self.config = config

    def validate_targets(self, request: TargetPositionRequest, context: RiskContext) -> RiskDecision:
        violations = []
        adjusted_positions = list(request.positions)
        context.positions = adjusted_positions

        for rule in self.rules:
            rule_violations = rule.evaluate(context)
            violations.extend(rule_violations)
            if any(v.severity == "BLOCK" for v in rule_violations):
                return self._reject(request, violations)
            rule.adjust(context)

        if self.config.approval.require_manual_approval:
            violations.append(RiskViolation(rule_id="MANUAL_APPROVAL", severity="WARN", message="manual approval required"))
            return self._adjust_or_pending(request, context, violations)

        return self._approve(request, context, violations)
```

### 9.5 手工审批设计

第一阶段采用文件审批。

风控 Agent 输出：

```text
artifacts/risk_runs/<run_id>/approval_required.json
```

人工审批后写入：

```text
artifacts/risk_runs/<run_id>/approval.json
```

`approval.json` 示例：

```json
{
  "run_id": "20260524-093000-research-lgb_alpha158-a1b2c3",
  "approved": true,
  "approved_by": "operator",
  "approved_at": "2026-05-24T18:00:00+08:00",
  "expires_at": "2026-05-24T19:00:00+08:00",
  "comment": "paper trading only"
}
```

### 9.6 Kill Switch

实现两种 Kill Switch：

```text
环境变量：GLOBAL_KILL_SWITCH=true
文件开关：artifacts/KILL_SWITCH 存在
```

只要任一触发，所有目标仓位和订单都必须被拒绝。

---

## 10. 执行桥接设计

### 10.1 桥接职责

`execution/bridge.py` 负责把风控批准后的目标仓位转成可执行订单。

流程：

```text
approved_positions.json
    ↓
读取账户现金与当前持仓
    ↓
计算目标股数
    ↓
按 100 股取整
    ↓
生成差额订单
    ↓
订单级风控二次校验
    ↓
发送到 vn.py
```

### 10.2 输入：`approved_positions.json`

```json
{
  "run_id": "20260524-093000-research-lgb_alpha158-a1b2c3",
  "strategy_id": "lgb_alpha158_csi300_v1",
  "approved": true,
  "decision": "ADJUST",
  "trade_date": "2026-05-25",
  "positions": [
    {
      "symbol": "600519.SH",
      "target_weight": 0.03,
      "adjusted": true,
      "reason": "single position limit"
    }
  ]
}
```

### 10.3 输出：`orders.json`

```json
{
  "run_id": "20260524-093000-research-lgb_alpha158-a1b2c3",
  "strategy_id": "lgb_alpha158_csi300_v1",
  "orders": [
    {
      "client_order_id": "20260524-a1b2c3-0001",
      "symbol": "600519.SH",
      "side": "BUY",
      "order_type": "LIMIT",
      "price": 1688.00,
      "volume": 100,
      "reason": "rebalance_to_target"
    }
  ]
}
```

### 10.4 仓位换算

```python
def target_weight_to_volume(
    target_weight: float,
    total_equity: float,
    last_price: float,
    lot_size: int = 100,
) -> int:
    raw_volume = int((target_weight * total_equity) / last_price)
    return (raw_volume // lot_size) * lot_size
```

### 10.5 幂等性

桥接模块必须支持重复执行，不得重复下单。

实现方式：

```text
client_order_id = hash(run_id + symbol + side + volume + price)
```

在发送订单前查询 `order_audit` 表，如果 `client_order_id` 已存在，则跳过。

---

## 11. vn.py 模拟盘实现

### 11.1 模拟执行适配器

Codex 应先实现 `MockExecutionAdapter`，不直接依赖真实券商。

```python
class MockExecutionAdapter:
    def __init__(self, account_state_path: str):
        self.account_state_path = Path(account_state_path)

    def submit_order(self, order: OrderRequest) -> OrderResult:
        # 读取模拟行情
        # 检查现金和持仓
        # 生成模拟成交
        # 更新账户状态
        ...
```

### 11.2 vn.py Adapter

真实 vn.py 适配器只作为第二阶段。

```python
class VnpyExecutionAdapter:
    def __init__(self, main_engine, gateway_name: str):
        self.main_engine = main_engine
        self.gateway_name = gateway_name

    def submit_order(self, order: OrderRequest):
        # 转换为 vn.py OrderRequest
        # 调用 main_engine.send_order
        ...
```

### 11.3 策略模板

```python
class TargetPositionStrategy(CtaTemplate):
    author = "quant-agent"

    parameters = ["target_file"]
    variables = ["last_run_id"]

    def on_init(self):
        self.write_log("TargetPositionStrategy initialized")

    def on_start(self):
        self.write_log("TargetPositionStrategy started")

    def on_bar(self, bar):
        request = self.load_approved_positions()
        if request.run_id == self.last_run_id:
            return
        orders = self.bridge.build_orders(request)
        for order in orders:
            self.send_order_from_bridge(order)
        self.last_run_id = request.run_id
```

---

## 12. 存储与审计

### 12.1 数据库表

第一阶段使用 SQLite，后续迁移 PostgreSQL。

```sql
CREATE TABLE research_run (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    universe TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT,
    artifact_dir TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE risk_decision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    approved INTEGER NOT NULL,
    violations_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE order_audit (
    client_order_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL,
    volume INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE trade_audit (
    trade_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    volume INTEGER NOT NULL,
    traded_at TEXT NOT NULL
);
```

### 12.2 审计事件

所有模块统一输出 JSON Lines。

```json
{
  "event_id": "evt_20260524_000001",
  "event_type": "risk.decision.created",
  "run_id": "20260524-093000-research-lgb_alpha158-a1b2c3",
  "strategy_id": "lgb_alpha158_csi300_v1",
  "timestamp": "2026-05-24T18:10:00+08:00",
  "payload": {
    "decision": "ADJUST",
    "violations": 3
  }
}
```

输出位置：

```text
artifacts/audit/events-YYYYMMDD.jsonl
```

---

## 13. 可观测性与报告

### 13.1 指标

最少实现以下指标。

| 指标 | 模块 | 用途 |
|---|---|---|
| `data_freshness_seconds` | 数据 | 新鲜度 |
| `research_run_duration` | 研究 | 耗时 |
| `risk_reject_count` | 风控 | 拒绝数 |
| `risk_adjust_count` | 风控 | 调整数 |
| `orders_submitted` | 执行 | 订单数 |
| `paper_pnl` | 执行 | 盈亏 |
| `max_drawdown` | 风控 | 回撤 |

### 13.2 报告生成

每次 run 输出报告：

```text
artifacts/reports/<run_id>_report.md
```

报告结构：

```text
策略摘要
数据版本
模型版本
关键指标
目标仓位
风控结果
模拟订单
成交回报
风险事件
后续建议
```

### 13.3 用户便利性

系统应提供一个统一命令：

```bash
quant-agent report latest
```

输出最近一次完整闭环的报告路径，并可选打开：

```bash
quant-agent report open --run-id <run_id>
```

---

## 14. CLI 设计

### 14.1 主命令

```bash
quant-agent init
quant-agent data pull --start 2024-01-01 --end 2025-12-31 --universe CSI300
quant-agent data convert --config configs/data/qlib.yaml
quant-agent research qlib --config configs/research/baseline_lgb_alpha158.yaml
quant-agent research rdagent --task fin_factor --config configs/research/rd_agent_fin_factor.yaml
quant-agent risk validate --target artifacts/research_runs/<run_id>/target_positions.json
quant-agent execution build-orders --approved artifacts/risk_runs/<run_id>/approved_positions.json
quant-agent paper run --orders artifacts/execution_runs/<run_id>/orders.json
quant-agent report generate --run-id <run_id>
quant-agent status
quant-agent kill-switch enable
quant-agent kill-switch disable
```

### 14.2 CLI 实现建议

使用 Typer。

```python
# src/quant_agent/cli.py
import typer

app = typer.Typer()
data_app = typer.Typer()
research_app = typer.Typer()
risk_app = typer.Typer()
execution_app = typer.Typer()

app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(risk_app, name="risk")
app.add_typer(execution_app, name="execution")


@app.command()
def status():
    """Show environment, data, risk and execution status."""
    ...
```

---

## 15. Makefile 设计

```makefile
.PHONY: init test lint data-pull data-convert research risk paper report

init:
	python scripts/init_project.py

install:
	pip install -e .[dev,research,risk]

test:
	pytest -q

lint:
	ruff check src tests
	mypy src

data-pull:
	python scripts/pull_data.py --config configs/data/akshare.yaml

data-convert:
	python scripts/convert_to_qlib.py --config configs/data/qlib.yaml

research:
	python scripts/run_qlib_backtest.py --config configs/research/baseline_lgb_alpha158.yaml

risk:
	python scripts/validate_targets.py --latest

paper:
	python scripts/run_paper_trading.py --latest

report:
	python scripts/generate_report.py --latest
```

---

## 16. 测试设计

### 16.1 单元测试

必须覆盖：

```text
symbol normalization
配置读取
数据校验
目标仓位生成
风控规则
仓位换算
订单幂等
Kill Switch
```

示例：

```python
def test_single_weight_limit_adjusts_position():
    request = make_target_request(symbol="600519.SH", weight=0.10)
    config = make_risk_config(max_single_weight=0.05)
    decision = RiskEngine.from_config(config).validate_targets(request, make_context())
    assert decision.decision == "ADJUST"
    assert decision.positions[0].target_weight == 0.05
```

### 16.2 契约测试

目标：保证模块之间 JSON 契约稳定。

```text
target_positions.json 能被 RiskEngine 读取
approved_positions.json 能被 ExecutionBridge 读取
orders.json 能被 MockExecutionAdapter 读取
```

### 16.3 集成测试

实现以下端到端测试：

```bash
pytest tests/integration/test_research_to_risk.py
pytest tests/integration/test_risk_to_paper.py
pytest tests/integration/test_full_file_bus_flow.py
```

### 16.4 回归测试

选择一组小样本数据作为固定 fixture：

```text
5 支股票
60 个交易日
包含 ST、停牌、涨停、跌停、T+1 场景
```

每次 CI 必须确保：

```text
数据转换成功
回测可运行
风控能拒绝违规标的
模拟盘不会重复下单
报告能生成
```

---

## 17. 日后使用便利性设计

### 17.1 一键运行完整闭环

实现：

```bash
quant-agent run pipeline --mode paper --config configs/env/dev.yaml
```

内部流程：

```text
data.pull_if_needed
    ↓
data.convert_if_needed
    ↓
research.run
    ↓
risk.validate
    ↓
execution.build_orders
    ↓
paper.run
    ↓
report.generate
```

### 17.2 最近一次运行快捷命令

```bash
quant-agent latest
quant-agent latest report
quant-agent latest metrics
quant-agent latest risk
quant-agent latest orders
```

### 17.3 策略注册表

新增：

```text
configs/strategy_registry.yaml
```

示例：

```yaml
strategies:
  lgb_alpha158_csi300_v1:
    owner: quant
    type: qlib
    config: configs/research/baseline_lgb_alpha158.yaml
    risk_profile: default
    status: active

  rd_factor_csi300_v1:
    owner: quant
    type: rd-agent
    config: configs/research/rd_agent_fin_factor.yaml
    risk_profile: conservative
    status: experimental
```

使用：

```bash
quant-agent strategy list
quant-agent strategy run lgb_alpha158_csi300_v1 --mode research
quant-agent strategy run lgb_alpha158_csi300_v1 --mode paper
```

### 17.4 策略上线检查表

在 `docs/live_trading_checklist.md` 中维护。

上线前必须满足：

```text
回测通过
样本外测试通过
模拟盘至少 N 天
最大回撤未超限
换手率未超限
风控规则启用
人工审批记录存在
Kill Switch 可用
券商账户余额同步正确
交易网关重连测试通过
日志和监控可用
```

### 17.5 报告模板

在 `docs/report_template.md` 中定义报告格式。报告生成器将自动填充：

```text
run_id
strategy_id
数据区间
模型参数
核心指标
风控结论
订单明细
异常事件
下一步建议
```

### 17.6 用户目录和文件命名

所有运行结果都应可通过 `run_id` 定位，不需要用户记路径。

```bash
quant-agent open --run-id 20260524-093000-research-lgb_alpha158-a1b2c3
```

等价于打开：

```text
artifacts/research_runs/<run_id>/
artifacts/risk_runs/<run_id>/
artifacts/execution_runs/<run_id>/
artifacts/reports/<run_id>_report.md
```

---

## 18. Codex 实施任务拆解

### Phase 0：项目骨架

目标：创建基本目录、配置、CLI 和测试框架。

Codex 应创建：

```text
pyproject.toml
Makefile
.env.example
configs/env/dev.yaml
src/quant_agent/cli.py
src/quant_agent/common/config.py
src/quant_agent/common/paths.py
tests/unit/test_config.py
```

验收：

```bash
pip install -e .[dev]
quant-agent status
pytest -q
```

### Phase 1：数据层

目标：实现本地 CSV/Parquet 数据适配器、数据校验和 Qlib 转换入口。

Codex 应创建：

```text
src/quant_agent/data/adapters/base.py
src/quant_agent/data/adapters/local_csv_adapter.py
src/quant_agent/data/validators.py
src/quant_agent/data/symbol.py
src/quant_agent/data/qlib_converter.py
scripts/pull_data.py
scripts/convert_to_qlib.py
```

验收：

```bash
make data-pull SAMPLE=1
make data-convert
pytest tests/unit/test_data_*.py
```

### Phase 2：Qlib 研究基线

目标：运行一个可复现的 Qlib LightGBM/Alpha158 基线。

Codex 应创建：

```text
src/quant_agent/research/qlib_runner.py
src/quant_agent/research/portfolio_builder.py
src/quant_agent/research/report_writer.py
scripts/run_qlib_backtest.py
configs/research/baseline_lgb_alpha158.yaml
```

验收：

```bash
make research
ls artifacts/research_runs/<run_id>/target_positions.json
ls artifacts/research_runs/<run_id>/metrics.json
```

### Phase 3：风控 Agent

目标：实现目标仓位审查。

Codex 应创建：

```text
src/quant_agent/risk/engine.py
src/quant_agent/risk/rules/base.py
src/quant_agent/risk/rules/position_limit.py
src/quant_agent/risk/rules/tradability.py
src/quant_agent/risk/rules/industry_limit.py
src/quant_agent/risk/rules/kill_switch.py
src/quant_agent/risk/reports.py
scripts/validate_targets.py
configs/risk/default.yaml
```

验收：

```bash
make risk
pytest tests/unit/test_risk_*.py
```

### Phase 4：执行桥和模拟盘

目标：将批准后的目标仓位转为模拟订单，并记录成交。

Codex 应创建：

```text
src/quant_agent/execution/bridge.py
src/quant_agent/execution/sizing.py
src/quant_agent/execution/mock_gateway.py
src/quant_agent/execution/order_router.py
scripts/run_paper_trading.py
configs/execution/vnpy_mock.yaml
```

验收：

```bash
make paper
ls artifacts/execution_runs/<run_id>/orders.json
ls artifacts/execution_runs/<run_id>/trades.json
```

### Phase 5：RD-Agent 集成

目标：封装 RD-Agent 调用并归一化输出。

Codex 应创建：

```text
src/quant_agent/research/rdagent_runner.py
scripts/run_rdagent.py
configs/research/rd_agent_fin_factor.yaml
configs/research/rd_agent_fin_quant.yaml
```

验收：

```bash
quant-agent research rdagent --task fin_factor --dry-run
```

`--dry-run` 必须只检查配置和工作目录，不实际调用大模型。

### Phase 6：报告与用户便利性

目标：实现一键报告、最新运行查询和策略注册表。

Codex 应创建：

```text
configs/strategy_registry.yaml
src/quant_agent/research/report_writer.py
src/quant_agent/common/run_index.py
scripts/generate_report.py
docs/runbook.md
docs/live_trading_checklist.md
```

验收：

```bash
quant-agent latest
quant-agent report latest
make report
```

### Phase 7：vn.py 真实适配器

目标：接入 vn.py，但不直接开启实盘。

Codex 应创建：

```text
src/quant_agent/execution/vnpy_adapter.py
src/quant_agent/execution/reconciliation.py
execution/vnpy_strategies/target_position_strategy.py
```

验收：

```bash
quant-agent execution vnpy-check --mode mock
```

### Phase 8：实盘准备

目标：只做上线检查，不自动实盘。

Codex 应实现：

```text
quant-agent live precheck
quant-agent live dry-run
quant-agent kill-switch enable
quant-agent kill-switch disable
```

验收：

```bash
ENABLE_LIVE_TRADING=false quant-agent live precheck
# 必须显示 live disabled
```

---

## 19. `pyproject.toml` 建议

```toml
[project]
name = "a-share-quant-agent"
version = "0.1.0"
description = "A-share quant research, risk and execution agent"
requires-python = ">=3.10,<3.14"
dependencies = [
  "pydantic>=2",
  "typer>=0.12",
  "pandas>=2",
  "numpy>=1.26",
  "pyyaml>=6",
  "sqlalchemy>=2",
  "rich>=13",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-cov",
  "ruff",
  "mypy",
]
research = [
  "pyqlib",
  "lightgbm",
  "scikit-learn",
  "mlflow",
  "akshare",
  "tushare",
]
risk = [
  "fastapi",
  "uvicorn",
]
execution = [
  "vnpy",
]

[project.scripts]
quant-agent = "quant_agent.cli:app"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## 20. 最小可用 MVP 验收标准

MVP 完成后，应能执行：

```bash
make init
make data-pull SAMPLE=1
make data-convert
make research
make risk
make paper
make report
```

验收结果：

```text
1. 生成一个 research run
2. 生成 target_positions.json
3. 风控 Agent 至少识别并处理单票仓位限制
4. 生成 approved_positions.json
5. 模拟盘生成 orders.json 和 trades.json
6. 生成完整 report.md
7. 所有 run_id 可追溯
8. Kill Switch 可以阻断交易
9. 单元测试和集成测试通过
```

---

## 21. 后续演进路线

### 21.1 从文件协议迁移到消息协议

第一阶段使用文件协议。第二阶段可升级为：

```text
Redis Stream
ZeroMQ
gRPC
Kafka
```

推荐顺序：

```text
file → Redis Stream → gRPC
```

### 21.2 从 SQLite 迁移到 PostgreSQL

第一阶段 SQLite 足够。生产前迁移到 PostgreSQL，并加入 Alembic 管理 schema。

### 21.3 从模拟盘迁移到影子实盘

影子实盘只订阅真实行情和账户状态，不真实下单。系统生成订单，但不发送给券商，只记录若执行会产生什么结果。

```text
paper → live_shadow → live_manual → live_limited → live
```

### 21.4 从硬规则风控扩展到风险模型

第一版使用规则风控。后续加入：

```text
Barra 风格暴露
行业中性约束
VaR
CVaR
压力测试
因子拥挤度
流动性冲击成本
```

---

## 22. 工程安全边界

必须遵守：

```text
RD-Agent 不允许直接下单
Qlib 不允许直接调用券商接口
风控 Agent 不能被策略绕过
live 模式默认关闭
Kill Switch 优先级最高
订单必须可审计
重复执行不能重复下单
所有实盘指令必须记录 run_id
```

实盘前必须人工确认：

```text
数据源准确
账户同步准确
持仓同步准确
网关连接稳定
风控规则启用
审批流程启用
交易日志可查
回滚流程可用
```

---

## 23. 给 Codex 的实施要求

Codex 实施时必须遵守：

1. 优先实现可运行的最小闭环，不要直接实现实盘网关。
2. 每个模块必须有单元测试。
3. 所有外部接口必须有 Pydantic schema。
4. 所有脚本必须支持 `--config` 参数。
5. 所有输出必须写入 `artifacts/`，不得散落在项目根目录。
6. 所有运行必须生成 `run_id`。
7. 不得将 API key、券商账户、token 写入代码或配置样例。
8. `live` 模式必须默认关闭。
9. 风控失败时不得继续执行。
10. 生成的报告必须能说明策略、数据、风控和订单来源。

---

## 24. 推荐第一轮 Codex Prompt

可以直接把以下内容作为 Codex 第一轮任务：

```text
请根据 docs/technical_design_codex.md 实现 Phase 0 和 Phase 1。

要求：
1. 创建项目骨架、pyproject.toml、Makefile、.env.example。
2. 实现 quant_agent.cli，支持 status、init、data pull、data convert 命令。
3. 实现配置读取、路径管理、run_id 生成。
4. 实现 LocalCsvAdapter、symbol normalization、daily_bar 数据校验。
5. 添加 tests/unit，确保 pytest 通过。
6. 不要实现实盘交易。
7. 不要访问任何真实券商或真实交易接口。
8. 所有运行输出写入 artifacts/。
```

第二轮任务：

```text
请实现 Phase 2 和 Phase 3。

要求：
1. 添加 QlibRunner 和 PortfolioBuilder。
2. 能生成 target_positions.json。
3. 添加 RiskEngine 和基础风控规则。
4. 能生成 approved_positions.json 或 rejected decision。
5. 添加契约测试，验证 target_positions.json 可被 RiskEngine 读取。
```

第三轮任务：

```text
请实现 Phase 4 和 Phase 6。

要求：
1. 添加 ExecutionBridge 和 MockExecutionAdapter。
2. 将 approved_positions.json 转换为 orders.json。
3. 模拟生成 trades.json。
4. 添加 report_writer，生成 run report。
5. 实现 quant-agent latest 和 quant-agent report latest。
```

---

## 25. 附录：最小端到端文件协议示例

### 25.1 `target_positions.json`

```json
{
  "schema_version": "1.0",
  "run_id": "demo-run-001",
  "strategy_id": "demo_strategy",
  "trade_date": "2026-05-25",
  "generated_at": "2026-05-24T17:00:00+08:00",
  "universe": "CSI300",
  "positions": [
    {"symbol": "600519.SH", "target_weight": 0.10, "score": 1.8, "rank": 1},
    {"symbol": "000001.SZ", "target_weight": 0.03, "score": 1.2, "rank": 2}
  ],
  "metadata": {}
}
```

### 25.2 `approved_positions.json`

```json
{
  "run_id": "demo-run-001",
  "strategy_id": "demo_strategy",
  "approved": true,
  "decision": "ADJUST",
  "positions": [
    {"symbol": "600519.SH", "target_weight": 0.05, "adjusted": true, "reason": "max_single_weight"},
    {"symbol": "000001.SZ", "target_weight": 0.03, "adjusted": false, "reason": null}
  ],
  "violations": [
    {"rule_id": "MAX_SINGLE_WEIGHT", "severity": "WARN", "symbol": "600519.SH", "message": "weight adjusted from 0.10 to 0.05"}
  ]
}
```

### 25.3 `orders.json`

```json
{
  "run_id": "demo-run-001",
  "strategy_id": "demo_strategy",
  "orders": [
    {"client_order_id": "demo-run-001-600519-buy", "symbol": "600519.SH", "side": "BUY", "order_type": "LIMIT", "price": 1688.0, "volume": 100},
    {"client_order_id": "demo-run-001-000001-buy", "symbol": "000001.SZ", "side": "BUY", "order_type": "LIMIT", "price": 11.2, "volume": 1000}
  ]
}
```

---

## 26. 结论

本设计把原始架构进一步细化为可实施的工程方案。第一阶段应聚焦本地可运行闭环：

```text
数据 → Qlib 研究 → 目标仓位 → 风控 → 模拟执行 → 报告
```

第二阶段再接入 RD-Agent 自动研究。第三阶段再接入 vn.py 真实执行环境。实盘自动化必须放在最后，且必须经过风控、审批、审计和 Kill Switch 保护。

该方案相比从零搭建的关键优势是：Qlib 复用成熟研究与回测能力，RD-Agent 复用自动化研发流程，vn.py 复用交易执行与网关生态；自研部分集中在最需要可控和最贴近 A 股业务的地方，即数据适配、风控、信号桥接、审计和用户操作体验。

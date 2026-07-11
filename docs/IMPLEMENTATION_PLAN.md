# A 股智能量化系统实施计划

> 目标：在 Mac 上交付可复现的研究、确定性风控、Paper Execution 和评测闭环。  
> 生产边界：默认 `dev/paper`，不启用真实券商下单。  
> 架构来源：`technical_design_codex_enriched.md`。  
> 仓库决策：见 `docs/adr/0001-repository-integration.md`。

## 1. 实施原则

1. 先定义契约和验收用例，再实现业务逻辑。
2. 研究、风控、执行保持进程和模块隔离。
3. 风控与订单批准必须是确定性逻辑；LLM 仅用于研究、解释和报告。
4. 所有运行绑定 `run_id`、配置快照、代码版本、数据版本和随机种子。
5. 所有写操作具备幂等语义；关键状态变化进入审计日志。
6. Mac 负责研发、回测和模拟盘；RD-Agent 运行在 Linux；真实网关运行在专用 Linux/Windows 主机。
7. 一个 PR 原则上只完成一个可验收 Issue，并附带测试或评测案例。

## 2. 当前基线

仓库当前已具备一个确定性的本地 MVP：

```text
样本 A 股日线
→ 本地 Qlib 风格转换
→ 确定性研究目标仓位
→ 单票仓位限制与 Kill Switch
→ Mock Paper 成交
→ Markdown 报告与 latest.json
```

已有能力主要对应 M0 的 Python 骨架，以及 M2-M5 的最小占位实现。它们用于验证端到端协议，不代表真实 Qlib、完整 A 股 PIT 数据、完整风控或 vn.py 网关已经完成。

## 3. GitHub 工作方式

### 3.1 分支

```text
codex/qta-<issue>-<slug>
```

### 3.2 提交

采用 Conventional Commits：

```text
feat(scope): ...
fix(scope): ...
test(scope): ...
docs(scope): ...
```

### 3.3 PR 必备信息

- 变更内容与原因。
- 受影响契约和迁移说明。
- 执行的测试与评测套件。
- 已知限制、未执行检查和回滚方式。
- 风控或执行变更对应的 reason code / eval case。

### 3.4 合并门槛

```bash
pytest -q
ruff check src tests scripts
mypy src
```

安全关键模块还必须运行对应 eval suite。不得通过删除、跳过或弱化测试来获得通过结果。

## 4. Milestone 总览

| 里程碑 | 目标 | 主要退出条件 |
|---|---|---|
| M-1 | 仓库勘察与接入决策 | ADR、保护边界、能力矩阵 |
| M0 | 工程骨架与本地体验 | doctor、配置、日志、CI、开发命令 |
| M1 | 领域契约与 Registry | 稳定 JSON Schema、状态机、审计模型 |
| M2 | 数据平台与 PIT | 不可变数据快照、DQ、Qlib 数据集 |
| M3 | Qlib 基线 | 可复现 Alpha158 + LightGBM 研究闭环 |
| M4 | 确定性风控 | 规则编排、reason code、持久化 Kill Switch |
| M5 | Paper Execution | 订单状态机、FillModel、幂等、对账 |
| M6 | RD-Agent | Linux 沙箱、因子扫描、产物导入 |
| M7 | Web UX | Onboarding、研究、审批、风险、订单旅程 |
| M8 | 评测与硬化 | 统一 Eval Runner、隐藏集、混沌测试、发布门槛 |
| M9 | 实盘候选 | vn.py RPC、双人审批、物理隔离、灾备演练 |

## 5. M-1：仓库勘察与接入

### 已完成

- 仓库确认是独立的 A 股量化 Agent 项目。
- 采用根目录项目结构，不创建嵌套子项目。
- 根级 `AGENTS.md` 定义代码、安全和交易规则。
- ADR-0001 固化接入决策。

### 待完成

- CODEOWNERS：契约、风控、执行、实盘路径需要明确所有者。
- GitHub labels、milestones 和 Project 字段。
- Mac/Linux/Windows 能力矩阵和依赖版本矩阵。

## 6. M0：工程骨架与开发体验

### Issues

- QTA-010：确认目录骨架和包边界。
- QTA-011：锁定 Python workspace 与依赖策略。
- QTA-013：Postgres/Redis/MLflow 开发 Compose。
- QTA-014：分层配置及 `.env.example`。
- QTA-015：结构化日志与 correlation ID。
- QTA-016：`quant-agent doctor`。
- QTA-017：GitHub Actions 基础 CI。
- QTA-018：统一 Makefile 命令。
- QTA-019：健康检查 API。

### Doctor 验收

`quant-agent doctor` 至少检查：

- Python 版本和操作系统架构。
- YAML 配置合法性和时区。
- artifact 目录可写性。
- `allow_live_trading` 与人工审批安全默认值。
- Qlib、LightGBM、MLflow、RD-Agent、vn.py 可用性。
- uv 与 Docker 可用性。
- 人类可读输出和 JSON 输出。

MVP profile 允许缺少可选研究/执行依赖；research/execution profile 对必需依赖 fail closed。

## 7. M1：领域契约、状态机与 Registry

### 核心契约

- `InstrumentId`：统一 `600519.SH` / `000001.SZ`。
- 时间：所有事件时间必须带时区，持久化使用 UTC。
- 金额、价格和数量：使用 Decimal 语义，禁止隐式二进制浮点资金计算。
- `EventEnvelope`：event_id、event_type、occurred_at、correlation_id、causation_id、schema_version。
- `ResearchSpec`：数据快照、标的池、特征、模型、切分、成本和随机种子。
- `TargetPortfolio`：目标权重、score、约束和生成证据。
- `RiskDecision`：APPROVE/ADJUST/REJECT、rule results、policy version、解释。
- `OrderIntent`：账户、标的、方向、数量、价格、时效、幂等键和审批引用。

### 数据库与 Registry

使用 SQLAlchemy/Alembic 实现：

- data_snapshot
- experiment
- model_version
- strategy_version
- risk_policy
- approval
- order / fill / position_snapshot
- audit_event

Registry 必须能够回答：一个策略由哪份数据、代码、配置、模型和评测结果产生。

### 退出门槛

- JSON Schema 可自动导出。
- 当前版本能读取前一版本的兼容 payload。
- 契约评测集 v0.1 通过。
- 状态机拒绝非法跃迁。

## 8. M2：数据、PIT 和不可变快照

### 数据分层

```text
raw/          原始供应商响应，只追加
normalized/   统一标的、日历、价格、财务和状态语义
snapshot/     带 manifest 和 hash 的不可变研究快照
qlib/         从 snapshot 构建的 Qlib 数据集
```

### PIT 要求

- 财务数据以公告可知时间而不是报告期结束时间进入样本。
- 指数成分和行业分类使用有效期。
- 复权因子不能泄漏未来公司行为。
- 停牌、ST、退市、涨跌停和上市天数按当日状态计算。

### Data Quality

至少检测：

- 主键重复、字段缺失、OHLC 非法、负成交量。
- 交易日缺口、时间倒序、时区错误。
- 标的映射冲突、复权突变、异常收益。
- 财务公告时间倒挂、指数成分有效期重叠。
- 数据新鲜度和供应商覆盖率。

严重错误阻断 snapshot；告警必须进入 manifest。

### Snapshot Manifest

记录：snapshot_id、source versions、时间范围、universe、row counts、quality report、file hashes、builder code version、created_at。

## 9. M3：Qlib 基线研究

### 基线

- CSI300 日频。
- Alpha158。
- LightGBM。
- 固定随机种子。
- Train/Validation/Test 时间切分。
- Purge 与 Embargo。
- A 股手续费、印花税、滑点、涨跌停、停牌和成交量约束。

### 产物

```text
research_runs/<run_id>/
├── research_spec.json
├── config_snapshot.yaml
├── data_manifest.json
├── metrics.json
├── predictions.parquet
├── target_portfolio.json
├── model/
├── logs/
└── report.md
```

### 退出门槛

- 相同数据、代码、参数和种子得到相同关键结果。
- 训练、验证和测试完全按时间隔离。
- 报告包括收益、波动、Sharpe、IR、MDD、换手、成本、容量和基准对比。
- 研究评测集 v0.3 通过。

## 10. M4：确定性风控

### 规则顺序

```text
输入完整性
→ 数据新鲜度/快照一致性
→ Kill Switch
→ 标的可交易性
→ 账户/现金/T+1
→ 手数/单票/总仓位
→ 行业/风格暴露
→ 流动性/订单限制
→ 波动/亏损/回撤熔断
→ 审批
```

### 每条规则输出

- rule_id 与 rule_version。
- PASS/WARN/ADJUST/REJECT。
- 原值、阈值和调整值。
- symbol/account 作用域。
- 稳定 reason code。
- 人类可读说明。

### Kill Switch

至少支持：

1. 策略级：阻止某策略新订单。
2. 账户级：阻止账户新订单，可选择仅允许平仓。
3. 全局级：阻止所有新订单。

状态必须持久化并进入审计日志；系统异常时 fail closed。

## 11. M5：Paper Execution 与对账

### 组件

- `ExecutionGateway` 协议。
- `RebalancePlanner`：目标组合 → 差额订单。
- 订单状态机。
- 幂等键和去重存储。
- `FillModel` 与故障注入模型。
- `PaperExecutionGateway`。
- 乱序/重复事件处理。
- 对账服务。
- vn.py paper 进程适配。

### 状态机

```text
CREATED → VALIDATED → SUBMITTED → ACKNOWLEDGED
→ PARTIALLY_FILLED → FILLED
                    ↘ CANCEL_PENDING → CANCELLED
任意允许状态 → REJECTED / EXPIRED / ERROR
```

非法跃迁必须拒绝并审计。重复提交相同 idempotency key 不得生成第二笔订单。

### FillModel

支持：全成、部分成交、无成交、涨停买不到、跌停卖不出、停牌、延迟 ACK、重复回报、乱序回报和连接中断。

### 对账

比较内部订单/成交/持仓与 gateway snapshot。差异按严重度分类；关键差异触发 execution halt。

## 12. M6：RD-Agent 自动研究

### 运行边界

RD-Agent 作为 Linux 服务运行，不与 Mac 主进程共享 Python 环境。服务提供：

- start/status/cancel API。
- 作业队列、心跳和预算。
- 受限 Docker 沙箱。
- 只读数据 snapshot。
- 输出 artifact 导入 Registry。

### 因子安全扫描

在执行前检查：

- Python AST 禁止网络、subprocess、任意文件访问和危险 import。
- 允许列白名单。
- lookback 与 shift 方向。
- 未来函数和标签泄漏。
- 非确定性调用。
- 资源、时间和成本预算。

第一阶段仅接入 `fin_factor`；稳定后再启用 `fin_model` 和实验性 `fin_quant`。

## 13. M7：Web UX

### 核心旅程

1. **Onboarding**：环境检查、数据状态、可选依赖、paper safety。
2. **数据中心**：导入向导、快照、质量问题和血缘。
3. **研究工作台**：ResearchSpec 表单、预估资源、运行日志、取消、实验对比。
4. **策略详情**：模型、因子、数据、代码、指标、评测和发布历史。
5. **审批中心**：目标组合 diff、风险调整、证据链接和审批期限。
6. **风险中心**：当前 policy、暴露、violations、Kill Switch。
7. **订单与持仓**：状态时间线、成交、对账差异和异常恢复。
8. **评测中心**：suite 结果、失败案例、版本比较和 release gate。
9. **审计日志**：按 run/order/user/reason code 检索。

### 页面状态

每个页面都必须实现 loading、empty、error、stale data、permission denied 和 partial data 状态。时间同时显示 UTC 和 Asia/Shanghai；危险操作需要确认和明确后果。

## 14. M8：评测体系

### 统一案例格式

每个案例包含：

```yaml
id: risk-t1-sell-001
suite: risk
version: 1
input: {}
expected: {}
assertions: []
tags: [a-share, t-plus-one, critical]
severity: critical
owner: risk
```

### 目标规模

| Suite | 目标案例 |
|---|---:|
| contracts | 40 |
| data/PIT | 120 |
| research/backtest | 80 |
| risk | 150 |
| execution | 120 |
| agent | 80 |
| API/UX | 60 |
| chaos/security | 120 |
| **总计** | **770** |

### 关键案例

- PIT 财务公告日和指数成分有效期。
- 停牌、ST、涨跌停、T+1、100 股手数。
- 未来函数、幸存者偏差和成本遗漏。
- 超重仓调整、现金不足、行业集中、流动性不足。
- 重复订单、部分成交、乱序事件、断线重连、对账差异。
- RD-Agent 危险代码、列泄漏、超预算和不可复现。
- API 幂等、权限、加载/空/错误状态和 Kill Switch UX。

### Hidden Set

- Gold label 由量化、风控或执行责任人审核。
- 隐藏集不进入 Agent 可读取目录。
- 测试集按版本冻结，修改需要审计。
- 公开开发集与隐藏发布集不得共享 case ID 或原始 fixture。

### 报告

Eval Runner 输出 JUnit、JSON 和 HTML，并记录 suite version、code SHA、config hash、data snapshot、duration、pass rate 和失败证据。

### Paper MVP Release Gate

- 所有 critical cases 100% 通过。
- contracts/data/risk/execution 总通过率达到约定阈值。
- 无未解释的不可复现结果。
- Kill Switch、幂等和对账混沌测试通过。
- 无高危依赖或密钥泄漏。
- runbook、恢复步骤和审批证据齐全。

## 15. M9：实盘候选

进入 M9 前，Paper MVP 必须稳定运行并完成正式 Live Readiness Review。

M9 包括：

- vn.py RPC gateway。
- 专用执行服务器和券商兼容性验证。
- paper/live 配置、账户、密钥、网络和数据库物理隔离。
- 双人审批和短时有效审批单。
- shadow 模式和小资金分阶段放量。
- 断网、网关崩溃、行情停滞、数据库故障和灾备演练。

M9 不允许把 Mac 作为无人值守实盘主机。

## 16. 当前执行顺序

### Sprint 0

1. QTA-016：环境 doctor、ADR 和实施计划入库。
2. QTA-017：CI 基础工作流。
3. QTA-020/QTA-021：InstrumentId、时间和 Decimal 类型。
4. QTA-022：EventEnvelope。
5. QTA-031/QTA-032：JSON Schema 导出与契约评测 v0.1。

### Sprint 1

1. QTA-040/QTA-041：MarketDataProvider 与合成 provider。
2. QTA-043/QTA-044：Raw/Normalized 数据层。
3. QTA-049：Data Quality Engine。
4. QTA-050：Snapshot Builder。
5. QTA-054：数据/PIT 评测 v0.2。

### Sprint 2

1. QTA-060/QTA-061：Qlib Runner 与 ResearchSpec。
2. QTA-062/QTA-063：Alpha158 + LightGBM。
3. QTA-064/QTA-065：时间切分与 A 股成交成本。
4. QTA-066/QTA-072：指标与可复现性。
5. QTA-073：研究评测 v0.3。

## 17. Codex Issue 模板

```markdown
## Objective
一句话描述可验收结果。

## Context
引用设计章节、依赖 Issue 和现有实现。

## Inputs
输入契约、配置和 fixture。

## Outputs
产物、API、状态变化和审计记录。

## Files
预计创建和修改的文件。

## Acceptance criteria
- [ ] 行为标准
- [ ] 单元/契约/集成测试
- [ ] 对应 eval case
- [ ] 文档与迁移

## Non-goals
明确本 Issue 不实现的能力。

## Safety
列出 live、风控、权限、数据和密钥限制。

## Verification
列出必须执行的命令。
```

## 18. Codex 完工报告

每个任务完成时输出：

```text
Issue:
Branch/PR:
What changed:
Contracts changed:
Migrations:
Tests run:
Eval suites run:
Results:
Known limitations:
Rollback:
Next dependency:
```

# 日频投研助手运行手册

## 1. 每日盘后流程

确认系统日期、交易日和代码版本后运行：

```bash
quant-agent run daily --trade-date YYYY-MM-DD --provider sample
```

生产级本地 paper 观察应把 `sample` 换成通过质量验收的数据源。成功的首次
运行会停在 `AWAITING_APPROVAL`。先阅读输出的预执行日报，再检查清单：

```bash
quant-agent run show --run-id <run_id>
```

至少确认：

1. `DATA_SYNC` 至 `REPORT_PRE` 全部为 `COMPLETED`。
2. 数据健康没有 `ERROR`，`data_version` 与当日快照一致。
3. 当前仓位、目标仓位、调仓方向、预计费用和未成交原因可解释。
4. 风控结论为 `APPROVE` 或带明确调整记录的 `ADJUST`。
5. `artifacts/KILL_SWITCH` 不存在。

确认后签发限时审批并执行：

```bash
quant-agent approval grant \
  --run-id <run_id> \
  --approver <operator> \
  --expires-in-minutes 60

quant-agent paper run --run-id <run_id>
```

最后检查 `REPORT_FINAL`、成交/未成交原因、现金、持仓、总权益、日收益和回撤：

```bash
quant-agent run show --run-id <run_id>
```

只有状态为 `COMPLETED` 的批次会更新 `artifacts/latest.json`。

## 2. 数据源

### Sample

用于开发、回归和黄金文件重放：

```bash
quant-agent data sync --trade-date YYYY-MM-DD --provider sample
```

数据是确定性的，不代表真实市场。

### AkShare

安装 research extra 后可显式尝试：

```bash
quant-agent data sync --trade-date YYYY-MM-DD --provider akshare
```

当前适配器只能作为低成本探测源。由于缺少稳定的复权因子、历史 CSI300
成分、停复牌和涨跌停覆盖，严格同步会保存无效快照并退出非零；不得绕过这些
质量错误进入执行。

### Tushare Pro

Token 只通过进程环境注入：

```bash
export TUSHARE_TOKEN='<secret>'
quant-agent data sync --trade-date YYYY-MM-DD --provider tushare
```

不要把 Token 写入 YAML、shell 历史、日志或 Git。默认配置拉取约 1400 个
自然日以覆盖 Alpha158 示例窗口；CSI300 历史成分会用于确定需要拉取的证券。
首次同步会产生较多 API 请求，需确认账户积分、频率限制和接口权限。

每个数据版本位于：

```text
artifacts/data/snapshots/<trade_date>/<data_version>/
```

原始 canonical 数据是不可变 `.csv.gz`。`data_manifest.json` 记录来源、
拉取时间、截止日、行数、字段、SHA-256、提供商限制和每条质量规则。

## 3. 研究

日常默认使用确定性动量基线：

```bash
quant-agent run daily \
  --trade-date YYYY-MM-DD \
  --provider <provider> \
  --research-config configs/research/daily_momentum.yaml
```

真实 Qlib 候选：

```bash
quant-agent run daily \
  --trade-date 2026-07-29 \
  --provider tushare \
  --research-config configs/research/qlib_alpha158_csi300.yaml
```

Qlib 配置中的训练、验证、测试日期必须与快照覆盖范围一致。缺依赖或数据时
流程失败，不会降级成动量策略。修改日期窗口时要同步修改 Qlib handler、
segments 和回测窗口。

策略晋级是人工治理动作。至少复核：

- 特征截止时间不晚于预测时点；
- train/validation/test 严格按时间分离；
- 样本外 IC、RankIC、收益、回撤和换手稳定；
- 成本后仍优于确定性基线；
- 手续费、滑点和参数扰动不会让结论反转。

## 4. 失败与恢复

查看错误与阶段 attempts：

```bash
quant-agent run show --run-id <run_id>
```

修复外部原因后恢复：

```bash
quant-agent run resume --run-id <run_id>
```

恢复使用 RunManifest 内已解析的配置和已绑定的数据版本，不读取后来被改动的
研究/风险/执行参数。成功阶段不会重跑；失败阶段新增 attempt，不覆盖旧记录。

常见错误：

- `critical data validation failed`：更换或修复数据源，不能继续原运行。
- `approval has expired`：重新检查当前计划后再次 grant。
- `approval does not match`：计划已变化，旧审批自动无效。
- `kill switch is active`：先调查触发原因；只有人工确认安全后才移除开关。
- `Qlib is not installed`：安装 research extra；禁止静默回退。
- `fee schedule ... no schedule covers`：新增经确认且带生效日的费用配置。

数据同步在建立业务 `run_id` 前失败时，以无效 DataManifest 作为诊断记录；
修复数据后重新执行 `run daily`。

## 5. Kill Switch 演练

启用：

```bash
touch artifacts/KILL_SWITCH
```

它必须在计划生成、风险评估和执行前任一位置阻断。完成调查与人工确认后移除：

```bash
rm artifacts/KILL_SWITCH
```

仅删除这个明确文件，不要递归清理 `artifacts/`。然后对原 `run_id` 执行
`run resume`。若审批已过期，需要重新审批。

## 6. 调度

应用只提供幂等 `run daily`，不常驻。可由 macOS `launchd` 或 cron 在收盘
和数据源完成更新后触发。调度器应：

- 显式传入交易日；
- 保存退出码和标准错误；
- 非零退出立即提醒人工；
- 不自动 grant 审批；
- 不自动移除 Kill Switch；
- 不在日志中打印 Token。

## 7. Paper 验收与影子模式门槛

在任何交易连接提案前，至少连续 60 个交易日记录：

- 数据快照没有静默缺失；
- 同一订单意图没有重复订单；
- SQLite 与文件快照、现金、持仓、成交、费用和 NAV 每日一致；
- 所有未成交和风险调整均可解释；
- 审批过期、计划变化和 Kill Switch 演练均能阻断执行。

达到门槛后只能单独提出只读账户与 `live_shadow` 变更。当前代码不包含
`live_shadow`、`live_manual` 或真实订单提交。

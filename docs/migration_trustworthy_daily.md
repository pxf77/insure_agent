# 从演示流水线迁移到可信日频流程

## 兼容边界

旧命令和旧 JSON 契约至少保留一个版本可读。新字段先以可选字段加入，旧的
`target_positions.json`、`approved_positions.json` 和订单载荷仍可被原模块
读取。

旧命令继续写 `artifacts/latest_legacy.json`；严格日频状态机只在完整成功后
原子写 `artifacts/latest.json`。依赖“最近产物”的旧脚本应先固定读取
`latest_legacy.json`，再逐步改为显式 `run_id`。

## 推荐迁移步骤

1. 保留现有 `artifacts/` 备份，不编辑其中任何生成文件。
2. 使用 sample 跑通 `run daily → approval grant → paper run`。
3. 校验同一输入重复运行得到相同 `run_id`、信号、计划校验和和订单 ID。
4. 将外部脚本从隐式 latest 改为保存并传递 `run_id`。
5. 用固定历史夹具重放账户、T+1、费用、未成交和 NAV。
6. 显式选择真实数据源，观察质量门禁；AkShare 不合格时切换 Tushare。
7. paper 观察满 60 个交易日后再讨论只读/影子连接。

## 运行状态

严格流程的阶段顺序固定：

```text
DATA_SYNC → DATA_VALIDATE → RESEARCH → PLAN → RISK
→ REPORT_PRE → APPROVAL → EXECUTION → REPORT_FINAL
```

每个阶段记录开始、结束、输入和输出校验和、异常及 attempts。恢复从第一个
非完成阶段开始。运行目录和决策产物不可变；新的数据或配置会形成新的运行
身份，不覆盖旧批次。

## 回滚

代码回滚不会删除 SQLite 或不可变文件产物。需要暂时回到旧流程时：

1. 停止外部调度器；
2. 保留 `artifacts/portfolio.db`、`runs/`、`data/snapshots/` 和报告备份；
3. 仅运行兼容命令 `quant-agent run pipeline --mode paper`；
4. 让旧集成读取 `latest_legacy.json`；
5. 不复制旧 latest 内容覆盖新 `latest.json`。

不要直接编辑数据库或生成 JSON 来“修复”状态。发现账本差异时停止执行，
保留现场并通过新的迁移或对账脚本修复。

# DeepSeek Harness 真实恢复回答（Phase 6 试点 Feature）

- Feature：`FEAT-6cee9a20-f311-448c-8376-5ae57346db15`（domain=pilot，revision 4）
- Requirement：`REQ-abf206e0-b5a5-42a6-a8bd-5e1eaabde65e`（status=confirmed，revision 1）
- 恢复方式：仅依据仓库文件（AGENTS.md、README.md、skills/agent-project-manager/SKILL.md、docs/pilot-guide.md、`.project/` 事实与 artifacts 中的已有报告）；未读取任何会话外信息
- 实际工具：DeepSeek Harness（desktop profile，0.2.0-rc.2），model=deepseek-flash
- 实例：`codex-to-deepseek`（Run `RUN-a590787e-c5cd-42f4-966b-6eaac5e10cef`）

## 1. 结构化状态答案

```json
{"lifecycle":"developing","verification":"partial","delivery":"none"}
```

（三条均来自 `apm feature show FEAT-6cee9a20-f311-448c-8376-5ae57346db15 --json` 的 `lifecycle`/`verification`/`delivery` 字段，不是估计值。）

## 2. 目标、Requirement、required AC 与最近 Handoff

**目标**：Phase 6 让第二个真实 Agent 工具（本地 DeepSeek Harness）按正式 Skill/指南接手同一试点 Feature，保留真实 Run/Handoff/有效 Evidence 链，并用实测数据回答状态、剩余工作与验证/交付依据。

**Requirement**：`REQ-abf206e0-b5a5-42a6-a8bd-5e1eaabde65e`「让不同 Agent 按协议接手并验证真实试点」（confirmed）。其验收为：提供可移植 Skill 和指南；执行可复跑且诚实的 Eval；验证不同工具真实接力并报告证据链。

**required AC（3 个，全部 required）**：

| AC | 描述 | 当前 | 对应 Check |
| --- | --- | --- | --- |
| AC-001 | 试点报告区分确定性 CLI 验证和真实 Agent 观察，记录已知限制和复跑方法 | passed | CHECK-001（`test_phase6`，9 条命名用例） |
| AC-002 | 至少两种不同 Agent 工具在同一 Feature 上实际接力，保留 Run/Handoff/有效 Evidence 链 | not_started | CHECK-002（无 Evidence） |
| AC-003 | 真实接力正确回答状态、剩余工作及验证/交付依据，记录实际恢复时间、补问及冲突 | not_started | CHECK-003（无 Evidence） |

**最近 Handoff**：`HANDOFF-589e065f-6efd-4877-8aaf-31fda59a1d12`（run_ref `RUN-1e068b12-bd23-4fba-860a-514a91e8f157`，Codex，codex-cli 0.159.0-alpha.3，instance `codex-phase6`，status=completed）。它声明 Skill/references/Eval/评分器/指南/报告已实现，264 项 pytest 通过、12 场景合成 Eval 通过、当前 subject 下 44/46 required AC 通过；remaining 为「DeepSeek Harness 本地接手并保存 Run/Handoff/恢复回答/原始会话」和「回传后独立审阅并验收 CHECK-002/CHECK-003」；blocker 为云端无法调用本地 Harness。

**还剩什么、为什么**：AC-002 与 AC-003 的 Check 尚无任何 Evidence，因为真实接力需要本地第二个工具实际执行并回传，云端 Codex 无法代跑。本次接力的实际执行已经开始（本 Run），但审阅与验收必须由 Codex 在收到回传包后完成，不能由执行方自行判定。

## 3. 有效与失效 Evidence

Feature 自身有效 Evidence 只有一条：

- 有效：`EVD-b3bea40c-f622-4a17-9a1e-2a6040cfed54`（CHECK-001 / AC-001，type=test，result=passed，subject=sha256:b73860…b38e0，command=`uv run --frozen pytest tests/test_evals.py tests/test_relay.py --junitxml=.project/artifacts/phase6-checks.xml`，exit 0，note=named_assertions_passed）。CHECK-002、CHECK-003 的 `evidence` 为空，状态 `not_started`。
- 无失效条目：该 Feature 上没有 stale/被替代的历史 Evidence（它的历史全在别处）。当前代码 subject 仍为 `sha256:b738602172b35e6b6a84cd3d5f42ecb2d4b49ecfe06f83f0dfe7de20244b38e0`，与 `EVD-b3bea40c…` 及交接 manifest 一致，因此 CHECK-001 仍有效。

全项目（14 Feature、164 条 Evidence）：44 条有效、120 条失效。截至本次恢复，唯一未通过的是本试点 Feature（44/46 required AC）。失效条目的实际原因来自 `apm status --json`：`stale_code`、`stale_subject`、`superseded`，部分还带 `stale_check` 与 `command_mismatch`（Check 定义/命令变更后旧证据不再绑定当前 subject，属于规则推导出的正常失效，不是新失败）。当前 status 中 `claims` 为空、`conflicts` 为空。

**Commit / merge 不能证明功能验收**：本仓库 HEAD 仍是最初骨架提交 `03f3934`，全部 Phase 1–6 代码与事实都是未提交的工作树变更；`delivery=records:[]`、`delivery_gate=merged`。`git` 提交只表示 committed，MR 审查产物也不等于 required AC 通过；`EVD-…`（commit_is_not_delivery 场景）明确记录 committed 不等于交付。没有 merged 记录前 delivery 保持 `none`。

## 4. 活跃 Claim 与冲突

- 恢复开始时：无活跃 Claim、无冲突；Codex 的 `RUN-1e068b12…` 已 completed，其 Claim 已释放。四个历史 Run 全部终态。
- 同步：`.project/transactions` 为空，`doctor --json` ok=true、errors/warnings 为空、recovered_transactions 为空 → 无未完成事务，无需 `doctor --recover`。
- 本次接手动作：已用 `--agent deepseek-harness --instance codex-to-deepseek --scope path:.project/` 建立自己的真实 Run `RUN-a590787e-c5cd-42f4-966b-6eaac5e10cef`，当前持有该 Feature 的 Claim；结束时会 finish 并释放。

## 5. 本次实际执行（合成 Eval 与观测）

- 隔离 CLI Eval 重新执行到新目录：`uv run --frozen python -m evals.run --output .project/artifacts/eval-deepseek-1`，退出码 0，suite_id `3e897781-000d-4178-8f2f-72bcca658b7f`，12/12 场景 passed、0 failed、0 skipped，`cli_suite_elapsed_ms=127730.911`，`cross_agent.status=not_run`、`metrics.tokens=null`。这是**合成程序验收**，其 protocol-harness 角色不是外部 Agent，不能替代真实接力，也不能作为 AC-002/AC-003 的 Evidence。
- 只读 `apm verify FEAT-6cee9a20-… --json` 返回退出码 5、`required_passed=false`、`verification=partial`，并给出 `verification_not_passed`。按指南这是预期结果，保留 5，不改成通过。

## 6. 为什么现在不能宣称整个 Phase 6 通过

1. AC-002 要求的「两种不同 Agent 工具真实接力」在执行侧只完成了一半：Codex Run 已完成，DeepSeek Harness 侧的执行正在进行，但**独立审阅**尚未发生。执行方自己的回答与自建 Run 不能自证接力成功。
2. AC-003 要求真实恢复回答及实测时间/补问/冲突被记录并审阅。本目录提供了这些数据，但它们目前是**待审阅输入**，不是已验收 Evidence。
3. 本 Feature 的 CHECK-002/CHECK-003 仍为 `not_started`，`verification=partial`、`delivery=none`；`apm verify` 明确返回未通过。
4. 合成 Eval（12/12）只覆盖确定性 CLI 协议行为，其角色是 `protocol-harness` 测试数据；`report.json` 自身写明 `cross_agent.status=not_run`。把它当作 Phase 6 通过属于伪造证据。
5. 因此按规则不能登记这两个 Check 的 PASS，也不能把 Phase 6 或 V1 跨 Agent 试点标记完成；`docs/pilot-report.md` 与 `docs/decisions/0004-phase6-skill-eval.md` 已明确同一边界。

## 7. 下一步

1. 本次 Run 结束（finish）并释放 Claim 后，导出结果包：`uv run --frozen python -m evals.relay --project . --feature FEAT-6cee9a20-f311-448c-8376-5ae57346db15 --output .project/artifacts/relay/deepseek-result.zip`，记录实际 SHA-256。
2. 用户回传 `deepseek-result.zip`；Codex 独立审阅同一 Feature、同一代码 subject、两个真实工具、Run/Handoff 三组数组、终态 Claim、有效 Evidence 与实测数据。
3. 审阅通过后才登记试点 CHECK-002/CHECK-003 的 Evidence；未通过则保留 failed/not_verified，不迁移旧 PASS。
4. 无配对 baseline 时不声明 Skill 带来效率提升；本次无 token 计数，填 null。

## 8. 测量与限制说明

- `elapsed_ms` 只用文件与 transcript 中可核实的真实时间戳计算，不用 CLI 耗时代替恢复时间。
- 本 Harness 未暴露计费 token 计数 → `token_usage=null`；真实接力未发生向用户的补问 → `clarifications=0`（若按“未决歧义数”计则见 observation JSON 的 `conflicts`）。
- 恢复回答与观测数据是审阅输入，不是 PASS Evidence。

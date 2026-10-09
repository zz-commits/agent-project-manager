# CLI 命令协议初稿

`apm` 是 Python console script。Phase 1–5 已实现模型与状态查询、Run/Claim/Handoff、验证与交付关联、source list/show/add/sync 和 requirement list/show/decompose。第 3 节 project config、Requirement create/update、Feature create/update 与 next 等仍为拟议协议。CLI 不依赖 LLM，不自动拆需求、不自动编程。资源命令使用 `apm <resource> <action>`。

## 1. 通用输入输出

- `--project <path>` 显式指定项目；省略时从当前目录向上定位唯一 `.project/project.yaml`，找不到退出 4。
- 查询默认输出文本，所有命令支持 `--json`。JSON 模式 stdout 只输出一个完整对象，日志走 stderr。
- 写操作支持 `--dry-run`，校验并给出差异，但不修改事实、cache 或 generated。读操作不隐式运行测试。
- 创建/更新推荐 `--file <yaml-or-json>`，参数不完整时退出 2，不弹交互输入阻塞 Agent。
- 更新必须检查 `--expected-revision N`；Registry 等集合文件使用 `--expected-digest <sha256>`。前置条件失败退出 3。
- 批量导入先输出带输入摘要的 proposal，再由 `--apply <proposal-file>` 应用；基础文件已变化则拒绝过期提案。
- 默认不覆盖现有文件，不隐式提交、推送、发布或部署。涉及多个实体先完整校验，写入失败须回滚或保留可恢复事务记录并返回失败。
- `rebuild` 只更新派生视图，使用临时输出后整体替换；固定输入、规则版本和评估时间应得到相同结果。

JSON 外壳（所有字段稳定，data 随命令变化）：

```json
{
  "protocol_version": 1,
  "ok": true,
  "command": "feature.show",
  "data": {"id": "FEAT-EXAMPLE-001", "lifecycle": "ready", "example": true},
  "warnings": [],
  "errors": []
}
```

失败时 ok=false，data 可为 null，errors 每项含 code、message、entity_ref、field（后两项可为 null）。文本与 JSON 的退出码一致。结果字段应区分 stored facts、derived state 和 warnings；不把示例混入真实状态统计。

| 退出码 | 含义 |
| --- | --- |
| 0 | 操作成功；verify 时仅 required 验证全部通过 |
| 1 | IO、执行器或未知运行错误 |
| 2 | 参数、Schema 或引用校验错误 |
| 3 | Claim、修订号或提案冲突 |
| 4 | 项目、实体或引用目标不存在 |
| 5 | 前置条件阻塞，或 required 验证未通过/未验证 |

`status` 返回查询成功不等于所有 Feature 完成；`doctor` 优先报告结构错误 2，再报告冲突 3，环境阻塞 5；JSON 可包含全部问题。

## 2. 最小闭环命令（第一轮实现）

| 命令 | 行为 |
| --- | --- |
| `apm project init --name NAME` | 创建 managed 模式空事实目录；存在时拒绝覆盖 |
| `apm feature list [--state ready] [--domain NAME] [--ready]` | 返回事实源推导的 Feature 列表 |
| `apm feature show ID` | Requirement、AC、四维状态、原因、依赖、有效 Claim、最近 Handoff |
| `apm run start FEATURE --agent TYPE --instance ID --scope component:backend` | 检查前置条件与冲突，创建 Run；可选 `--scope feature:ID` 或 `path:src/**` |
| `apm run finish RUN --expected-revision N [--handoff-file FILE]` | 校验遗留事项交接，结束 Run、释放 Claim |
| `apm status` | 总量、生命周期分布、AC 覆盖、未验证实现、活跃 Run、冲突 |
| `apm rebuild` | 由事实生成 status/features/claims/graph JSON |
| `apm doctor` | 检查结构、ID、引用、AC、依赖环、证据、Claim 和交付核实情况 |

`--ready` 除 lifecycle=ready 外还要求没有冲突 Claim。active Claim 本身不表示已开发，只有 implementation 事实推进后才 developing。示例数据需 Project.mode=example，输出必须显示 example=true。

## 3. V1 后续命令

表中 source list/add/sync 和 requirement list/show/decompose 已于 Phase 5 实现；create/update、project config、next 仍待实现。

| 资源 | 拟议命令 | 输入与写入边界 |
| --- | --- | --- |
| project | show / config | config 查询默认只读；更改用 `--file` 与 revision |
| source | list / show / add / sync | add 用文件与 Registry expected-digest；sync 默认生成提案，`--dry-run` 查看差异，`--apply FILE` 应用 |
| requirement | list / show / create / update | update 用文件及 revision；影响已确认需求时设 changed |
| requirement | decompose ID --file FILE | Agent 提供完整 Feature 拆分计划，CLI 校验/展示；`--apply FILE` 才创建 Feature，不内置 LLM |
| feature | create / update / validate | create/update 用文件；拒绝写派生字段；validate 单 Feature 及相关引用 |
| feature | link-commit ID SHA --run-id RUN --expected-revision N | 解析并保存完整 SHA，核实关联，仅表示提交事实 |
| feature | link-mr ID --file FILE --run-id RUN --expected-revision N | 保存有出处的 MR 审查与 Evidence；V1 不自动连接托管平台 |
| run | show / update / abort | show 支持 ID/current；update 指定 revision；abort 必须 reason，有遗留则提供 Handoff |
| verify | FEATURE | 只评估已有 Evidence，不执行命令；无结果返回 not_verified、退出 5 |
| verify | FEATURE --run --run-id RUN --expected-revision N | 执行 Check.command_ref 指向的项目命令，保存真实结果和 Evidence |
| verify | FEATURE --record FILE --run-id RUN --expected-revision N | 导入已有测试或人工 Evidence，完整校验后关联 Check |
| next | 无资源参数 | 确定性推荐 ready、依赖已满足且无冲突的工作 |

`next` 排序为 priority（P0 优先）、可解锁依赖数量（多优先）、created_at、ID；只推荐不自动 Claim。无候选时成功返回空数组和原因。

首轮 Run.current 使用 `run show current --instance ID` 从事实匹配 active Run，不依赖 cache 指针；未指定实例或指针歧义必须要求明确 Run ID。不能默认选择“最近一次”。

`run start --override-conflict --reason TEXT` 仅绕过协作性 Claim 冲突，记录理由；不能绕过 Schema、revision、事务完整性等硬约束。跨机器未同步 Claim 的局限必须在输出中可见。

## 4. 验证执行约定

命令使用 argv/cwd，默认不拼接 shell 字符串。运行结果记录命令、退出码、subject、需求版本、日志/报告地址；超时或环境缺失记 not_verified。配置通过验收解析方式后才能建立 passed Evidence，不能仅凭退出码 0 覆盖所有 AC。

人工记录需 reviewer、范围、方法、结论和依据；Project 可禁止人工通过 required Check。Evidence 保存成功、Feature 引用更新成功后才报告命令成功。验证不修改 Requirement，不自动发布。

## 5. 一次完整操作示意

以下仅展示未来协议，文件名代表需要准备的真实输入：

```text
apm project init --name demo
apm source add --file source.yaml
apm requirement create --file requirement.yaml
apm feature create --file feature.yaml
apm feature show FEAT-001 --json
apm run start FEAT-001 --agent codex --instance worker-a --scope component:backend
apm feature update FEAT-001 --file feature-update.yaml --expected-revision 1
apm verify FEAT-001 --run --run-id RUN-001
apm feature link-commit FEAT-001 HEAD --expected-revision 3
apm run finish RUN-001 --expected-revision 1 --handoff-file handoff.yaml
apm rebuild
apm status --json
```

示例 revision 仅演示语法，实际调用必须用上一步返回值；Run ID 也使用 start 返回值。代码修改、Git commit、MR merge 在框架外按授权执行。link-commit 不能跳过 required AC 和交付门槛。

## 6. 后续保留协议

`apm project migrate --dry-run/--apply FILE`、自动 MR/CI 同步和更多 Adapter 放 V2；V1 对未知 version 直接报错。暂不提供 `apm run commit` 自动提交封装，也不引入独立 delivery/claim/handoff 顶层命令，避免同一动作多入口。

## 7. 首轮可执行约定

- doctor --recover 在锁内验证并完成未结束事务；只读 doctor 报告未完成日志，退出 5。恢复前拒绝新写入和派生查询。
- 通用 --project、--json、--dry-run、--at RFC3339 可放在子命令前后。--at 用于确定性状态和重建。
- run update RUN --expected-revision N --file FILE 接受部分更新对象，只允许 goal/work/files_touched/commit_refs/heartbeat_at；work 如提供须完整，revision 自动递增。
- run abort RUN --expected-revision N --reason TEXT [--handoff-file FILE] 与 finish 共用交接和事务规则。
- run start --override-conflict --reason TEXT 同时需要开关与非空理由；被覆盖重叠保留为 warning。
- 只读命令不执行 Project.commands；Phase 4 verify --run 显式执行命名 Check。Evidence 可经 --record 导入。

## 8. Phase 4 可执行约定

见 [Phase 4 决定](decisions/0002-phase4-verification.md)。verify --run/--record 必须带 producing Run 和 expected Feature revision。--check 可选子集，退出 0 仍要求完整 required 汇总 passed；导入用 check_ref 绑定，不接受 --check。--at 只用于只读 verify。写入 dry-run 不执行或保存，verify dry-run 返回 5。

--record 文件是完整 Evidence 对象或非空列表。link-mr 文件为 {record, evidence}，record.kind=mr，evidence 为完整 delivery Evidence 列表，关联的 ID 集合必须一致。更新同一 MR 必须显式 supersedes 旧记录的证据。返回 record 与当前 delivery/lifecycle，不把写入成功当作已交付。

## 9. Phase 5 可执行约定

见 [Phase 5 决定](decisions/0003-phase5-sources.md)。source list/show 返回 sources 与 Registry 原始字节 digest（64 位小写 SHA-256）；source add --file FILE --expected-digest DIGEST --run-id RUN 添加完整 Source，拒绝覆盖。可以登记其他来源类型，但实际读取只支持本地 Markdown 和 manual Adapter 的 Agent 文件。

source sync ID [--file AGENT_INPUT] 返回 data.proposal，只读；Markdown 使用 apm-requirement fenced block，Agent 文件使用 {requirements: [{key,title,description,acceptance}]}。requirement list 返回 requirements，show 返回 facts 与反查 feature_refs。requirement decompose ID --file PLAN 读取 {features: [完整初始 Feature]} 并返回 data.proposal。

应用统一使用 source sync ID --apply FILE 或 requirement decompose ID --apply FILE，另须 --run-id RUN --reviewer NAME --note TEXT。FILE 可是完整成功 CLI JSON 响应或其 data.proposal 对象。应用自动检查提案内的基础摘要和输入 SHA，不另要求 expected-revision；任何事实/输入变化或候选篡改均须重新生成，冲突退出 3。没有变更退出 5。返回 changes、conflicts、review_artifact 与 dry_run，不声称需求已确认。

提案含完整候选 records、前后差异与来源冲突；确认变化转 changed，冲突 blocked，删除保留需求。review.json 与 Registry/Requirement/新 Feature 同事务保存。--dry-run 不写锁/事实/产物，--at 不适用于生成或应用提案。输入路径为仓库相对路径，远程地址不会被读取；没有网络调用、LLM、代码或项目命令执行。

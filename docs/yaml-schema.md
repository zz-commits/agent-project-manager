# YAML Schema 初稿

版本：1，首轮核心协议已冻结。机器结构约束见 schemas/v1；补充规则以 [V1 core 决定](decisions/0001-v1-core.md) 为准。

七类虚构示例位于 `examples/design/.project/`，根 `.project/` 为真实 managed 项目。虚构示例的 Project.mode 为 example，不能作为实际项目进度或测试证据。路径均相对项目根目录。

## 1. 通用规则

- 每个 YAML 根必须有 `version: 1`。单实体具有稳定 `id`；Registry 根是 `version + sources`。
- 可变实体 Project、Requirement、Feature、Run 含正整数 `revision`，每次成功修改递增，用于乐观并发。Evidence/Handoff 创建后不可变，更正新建记录并引用旧 ID。
- ID 非空、类型前缀明确且在项目内唯一。示例使用 EXAMPLE 后缀；生产 ID 建议类型前缀加碰撞难度足够的随机标识，不用无协调的递增计数。managed ID 使用类型前缀加 canonical UUIDv4。
- 时间为带时区、加引号的 RFC3339 字符串；枚举使用小写 snake_case。空列表写 `[]`，缺值只在注明允许时写 `null`。
- 引用必须能解析；AC ID 在 Feature 内唯一，Check ID 同样在 Feature 内唯一。路径不能越出仓库，URL 与本地路径分开记录。
- 未知字段原则上拒绝；扩展放 `extensions` 对象。未来版本不能被旧工具静默重写。YAML 解析应拒绝重复键与可执行自定义标签。
- R=必需，O=可选。表中标 R 的对象，其下标 R 字段也必需。实现阶段再补严格长度、格式和条件验证。

## 2. Project

示例：[project.yaml](../examples/design/.project/project.yaml)。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id, revision | integer/string/integer，R | version=1；id 为 PROJ-* |
| name, description | string，R | 名称与目标 |
| mode | enum，R | example / managed；example 不计入真实完成统计 |
| stack | object，O | language、runtime 可为 null，表示未决定 |
| commands | map，R | 命令名→{argv: string[], cwd: string}；可选 timeout_seconds(0,3600] 与 result={kind:junit,path} |
| components | map，R | component→相对目录数组；允许空 map |
| git | object，R | default_branch: string/null |
| policies | object，R | delivery_gate、dependency_gate、allow_manual_evidence |
| policies.delivery_gate | enum，R | committed / merged / released / deployed；默认 merged |
| policies.dependency_gate | enum，R | verified / delivered；默认 delivered，deployed 满足 delivered |
| policies.allow_manual_evidence | boolean，R | 人工 Evidence 是否可满足 required Check |
| metadata | object，R | created_at、updated_at，均为时间字符串 |

commands 为空时验证执行返回未配置，不猜测测试命令。组件名不等同天然互斥路径。

## 3. Source（Registry 内的实体）

示例：[registry.yaml](../examples/design/.project/sources/registry.yaml)。Registry 根为 version 与 sources 数组；Source 本身也有 version，以便以后独立导出。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id | integer/string，R | version=1；SRC-* |
| type | enum，R | markdown / axure / document / spreadsheet / issue / conversation / code / other |
| name | string，R | 可读名称 |
| location | object，R | path 或 url，且恰好一个 |
| authority | enum，R | primary / secondary / reference / inferred |
| adapter | object，R | name: string；markdown 为本地结构化块，manual 支持 Agent 结构化需求输入；其他 Adapter 待实现 |
| revision | string，R | 来源快照标识；V1 可先为人工标记，自动同步采用摘要 |
| captured_at | timestamp，R | 登记来源版本的时间 |

Registry 修改以整个文件摘要作并发前置条件。来源版本和实体并发 revision 不同：这里是外部内容标识字符串。

Phase 5 接入格式见 [来源决定](decisions/0003-phase5-sources.md)。自动同步 revision 为 sha256:原始文件摘要；locator 为 block:<稳定 key>。输入不含确认或实现字段。

## 4. Requirement

示例：[REQ-EXAMPLE-001.yaml](../examples/design/.project/requirements/REQ-EXAMPLE-001.yaml)。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id, revision | 通用，R | REQ-* |
| title, description | string，R | 业务需要，不描述执行历史 |
| status | enum，R | draft / confirmed / changed / blocked |
| sources | object[]，R | 非空；source_ref、source_revision、locator 均必需 |
| acceptance | string[]，R | 需求级能力列表，非空 |
| blockers | string[]，R | 无则空数组 |
| metadata | object，R | created_at、updated_at |

confirmed 必须有可追溯来源；inferred 来源需有人工确认说明才能确认，字段为 confirmation={reviewer,note,confirmed_at}。不存开发进度，不存 feature_refs；从 Feature.requirement_refs 反向生成。

显式提案应用：新增 draft；confirmed 变化后 changed 并清除 confirmation；其他 primary 冲突保留旧内容并 blocked，blockers 使用 source_conflict:<SRC>。来源删除保留需求与引用，设 changed 并增加 source_missing:<SRC>:<key>。这些修改递增 Requirement revision，旧 Evidence 需重新验收。其他人工/来源阻塞项不得被同步静默清除。

proposal 是经过 proposal.json 校验的操作文档，含 UUIDv4 id、kind、target、base_digest、inputs、payload、changes（前后快照）、conflicts、created_at 和 digest。基础摘要覆盖 Project/Registry/所有 Requirement 与 Feature，inputs 绑定本次读取文件；source_sync 的 payload 保留完整 records 与新 ID 分配，decompose 保留计划路径。应用重新生成候选并比对，防止手改状态或写入路径。

## 5. Feature

示例：[FEAT-EXAMPLE-001.yaml](../examples/design/.project/features/example/FEAT-EXAMPLE-001.yaml)。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id, revision | 通用，R | FEAT-* |
| title, domain | string，R | domain 对应目录名 |
| requirement_refs | string[]，R | 至少一个有效 REQ ID |
| priority | enum，R | P0/P1/P2/P3，P0 最高 |
| size | enum，O | XS/S/M/L/XL，仅供规划 |
| depends_on | string[]，R | 不含自身，不能成环 |
| blockers | string[]，R | 显式未解决阻塞 |
| acceptance_revision | integer，R | 正整数，AC 语义变化必须递增 |
| acceptance | object[]，R | id、description、required 必需；至少一条 required=true |
| implementation | object，R | 见下表 |
| verification | object，R | checks: object[] 必需；每个 required AC 至少一个 Check |
| delivery | object，R | records: object[]，允许空数组 |
| metadata | object，R | created_at、updated_at |

Implementation 字段：state（not_started/in_progress/complete/blocked）、evidence_level（declared/observed/verified）、components（组件到文件列表的 map）、completed/remaining（string[]）、evidence_refs（string[]）、subject（object/null）均必需。not_started 可为 null subject，其余验证前必须明确 subject。

subject = `{kind: commit | working_tree | example, value: string}`。example 仅允许 Project.mode=example，不参与真实认证。working_tree 指纹规则见 V1 core 决定；排除根 .project 元数据，验证与交付使用同一算法。

Check 字段：id、acceptance_ref、required:boolean、activity（idle/running/blocked）、evidence_refs:string[] 均必需；command_ref:string 可选。证据绑定 Check，不能把一个测试成功泛化成所有 AC 成功。Check 不手写 passed 字段。Phase 4 可选 testcase_refs:string[]（非空且唯一），记录完整 JUnit classname.name；自动通过要求实际命名断言。

Delivery record 字段：kind（commit/mr/release/deployment）、ref:string、state（committed/mr_open/merged/released/deployed）、subject、evidence_refs:string[] 均必需。kind/state 必须相容；同一事实的快照随核实更新，完整历史在证据中保存。只有证据可核实且覆盖当前 subject 才用于推导；单个 URL 或 SHA 字符串不是完成证明。

禁止存 lifecycle、claims、verification.state、delivery.state。关联 Requirement 的状态同样实时读取。变更 Check/AC 或 subject 应立即重新评估全部 Evidence。

## 6. Run 与内嵌 Claim

示例：[RUN-EXAMPLE-001.yaml](../examples/design/.project/runs/RUN-EXAMPLE-001.yaml)。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id, revision | 通用，R | RUN-* |
| agent | object，R | type、version、instance_id:string；未知版本用 unknown |
| feature_refs | string[]，R | 至少一个 Feature |
| goal | string，R | 本次执行目标 |
| status | enum，R | active / completed / aborted |
| started_at | timestamp，R | 开始时间 |
| ended_at | timestamp/null，R | active 必须 null；终态必须有值 |
| heartbeat_at | timestamp，O | 提示疑似遗留，不构成租约自动到期 |
| claims | object[]，R | Claim 结构见下文 |
| work | object，R | completed、remaining、blockers:string[] |
| files_touched, commit_refs | string[]，R | 无则空数组；不据此判断验收 |
| handoff_ref | string/null，R | 有 remaining/blockers 的终态 Run 必须关联 Handoff |
| finish_reason | string，O | aborted 时必需；记录中止原因 |

Claim：feature_ref:string、scope:{type,value}、claimed_at 必需。目录以 / 结尾或使用 /**；不支持其他 glob，根目录使用 .。type 为 feature/component/path；feature 范围 value 为对应 Feature ID，component 为 Project 中组件名，path 为规范化相对路径或受限 glob。override_reason:string 可选，仅在明确协商覆盖冲突时记录。

claims 保留在终态 Run 中作为历史，只有 active Run 的 Claim 有效。不复制到 Feature；不因 Git commit 自动终止 Run。

## 7. Evidence

示例：[EVD-EXAMPLE-001.yaml](../examples/design/.project/evidence/FEAT-EXAMPLE-001/EVD-EXAMPLE-001.yaml)。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id | 通用，R | EVD-*，记录不可变 |
| feature_ref | string，R | 有效 Feature |
| check_ref | string，O | 用作验证证据时必需 |
| type | enum，R | test / api_response / screenshot / code_reference / manual_review / ci_result / delivery |
| produced_by | object，R | run_ref:string；reviewer:string 可选，人工验收时必需 |
| result | enum，R | passed / failed / not_verified |
| acceptance_revision | integer，R | 被验证 AC 版本 |
| requirement_revisions | map，R | 所有关联 REQ ID→被验证 revision |
| subject | object，R | 同 Feature.subject 结构 |
| check_digest | string，条件必需 | 用于验证且 passed 时必需；sha256: 加 Check 定义摘要，含存在时的 testcase_refs |
| delivery_ref, delivery_state | string/enum，条件字段 | delivery Evidence 与 MR/Commit 记录的精确绑定，两个字段成对出现 |
| delivery_observation | object，O | 本地 Git 自动观察 {kind:git_commit,commit:完整SHA,tree:完整SHA}，不伪造 reviewer |
| command | object/null，R | argv:string[]、cwd:string、exit_code:integer/null |
| artifacts | object[]，R | 每项 path 或 url 二选一，可选 sha256、expires_at |
| note | string，R | 方法、范围与限制 |
| supersedes | string[]，R | 替代的旧 Evidence ID，无则空 |
| created_at | timestamp，R | 证据产生时间 |

真实 passed 的自动测试需要实际执行结果和可读取产物；退出码为 0 仍需符合 Check 指定断言。manual_review 的 passed 要有 reviewer、方法、结论及可检查记录，并符合 Project 策略。超时、环境缺失、未执行都不是 passed。code_reference 不能独立满足行为验收。

V1 不自动信任外部内容中的命令；执行只读取 Project 明确配置的命令。保存日志需避免凭据等敏感内容。示例中 result=not_verified，并明确命令未执行。

## 8. Handoff

示例：[HANDOFF-EXAMPLE-001.yaml](../examples/design/.project/handoffs/HANDOFF-EXAMPLE-001.yaml)。

| 字段 | 类型 / 必需性 | 约束 |
| --- | --- | --- |
| version, id | 通用，R | HANDOFF-*，创建后不可变 |
| run_ref | string，R | 来源 Run |
| feature_refs | string[]，R | 必须属于 Run.feature_refs |
| summary | string，R | 简明交接背景 |
| completed, remaining, blockers | string[]，R | 明确未完成事项 |
| recommended_next | string[]，R | 可执行的后续工作建议 |
| evidence_refs | string[]，R | 可为空，不虚构证据 |
| context_refs | string[]，R | 仓库相对路径或来源引用 |
| created_at | timestamp，R | 创建时间 |

终态 Run 与关联 Handoff 的 completed/remaining/blockers 必须一致。后继 Run 仍须回查事实与证据；Handoff 是恢复入口，不覆盖新的需求版本或当前 Claim。

## 9. 跨模型校验清单

唯一 ID、版本、必填字段、枚举、类型、时间、引用完整性、domain 与路径一致、依赖无环、AC/Check 覆盖、Evidence/Check/Feature 对应、revision 匹配、subject 匹配、终态 Run 交接、Claim 范围冲突、产物存在性、交付引用可核实性。

结构错误和冲突不能静默修复。未核实证据可以被保存为 not_verified，但不能充当通过证据。样例仅校验结构与关联，不做真实 Git、命令或行为认证。

## 10. Phase 4 字段与产物

[执行与导入规则](decisions/0002-phase4-verification.md) 冻结了 JUnit、timeout、命名断言与交付绑定。自动 Git 观察只能是 delivery 类型、commit subject、committed 状态；人工 MR 仍须 reviewer。二进制/文本产物与 Evidence/Feature 经统一事务保存；恢复日志携带摘要与内容编码，不把产物 JSON 当实体加载。

## 日常维护写入

七模型保持 V1。Requirement/Feature CLI 生成受保护字段、修改 AC 时递增 acceptance_revision，并保留历史 Evidence/交付引用；CI Evidence 使用既有 ci_result 类型，command 记录实际远程 argv/cwd/exit_code 且须精确匹配配置。审阅提案和快照清单是操作/交接产物，不是新增事实模型或 PASS Evidence；详见 [日常维护 CLI](usability-cli.md)。

# 总体设计与目标

版本：V1 设计基线，2026-09-30。2026-10-08 首轮由 [V1 core 决定](decisions/0001-v1-core.md) 冻结；其他扩展目标不代表已实现功能。

## 1. 定位与目标

为 Codex、Claude、Cursor、DSH、OpenCode 等 Coding Agent 提供通用项目协议。只依赖读取 Markdown、YAML/JSON、执行 CLI 和访问代码/Git 的能力，不绑定某个 Agent 或模型服务。

解决六个问题：需求来源分散、Feature 生命周期不清楚、进度不可见、Agent 上下文难接续、验收证据不足、交付不可追溯。新 Agent 应能快速回答“做什么、来自哪里、做到哪里、谁在做、如何验证、是否交付、下一步是什么”。

框架不替代 Jira 等组织级平台。Skill 描述如何工作；`.project/` 保存具体项目事实；CLI 完成确定性校验、索引、冲突检测和状态计算。需求理解与代码编写属于 Agent，不属于 CLI 的内置智能。

核心原则：项目状态由事实和证据推导，而不是依赖 Agent 记忆。

## 2. 核心模型

```text
Source → Requirement → Feature → Development → Verification → Delivery
                          ↑            │             │            │
                    Project Context    Run        Evidence    Git / MR
                                       │
                                    Handoff

事实文件 → 确定性规则 → generated/ 中的状态、索引、Claim 与关系视图
```

| 模型 | 职责 | 不承担的职责 |
| --- | --- | --- |
| Source | 来源地址、定位、版本、权威等级和 Adapter 配置 | 自动裁决所有需求冲突 |
| Requirement | 为什么做、需要什么、来源和确认状态 | 开发进度 |
| Feature | 可独立验收的能力、AC、当前实现事实及证据关联 | 所有执行历史 |
| Development | Feature 的 implementation 维度及 Run 工作记录 | 单凭声明认定通过验收 |
| Verification | 按 AC 组织 Check，引用 Evidence 推导结果 | 与需求脱节的“通过率” |
| Delivery | 关联 Commit、MR/PR、Release、Deployment | 将本地提交等同已部署 |
| Run | 一次 Agent 执行、工作范围、过程和 Claim | 决定 Feature 完成 |
| Evidence | 验证方法、结果、产物、代码与需求版本 | 仅凭截图自动证明全部 AC |
| Handoff | 已完成、剩余、阻塞、下一步及必要上下文 | 替代事实与证据 |

Project Context 包含命令、路径约定、交付门槛和长期参考。Decision 在 V1 预留目录，重大决定先用 Markdown 保存；结构化 Decision Schema 后续演进。

## 3. Feature 粒度

Feature 是可独立实现、验收和交付的最小用户或业务价值单元，按四问判断：

1. 用户或业务能否感知该能力？
2. 是否有明确 Acceptance Criteria（AC）？
3. 是否能独立判断完成或未完成？
4. 是否通常可由一个 MR 或少量 Commit 交付？

例如“用户管理”是 Requirement，可拆为列表、新增、编辑、删除、导入、导出等 Feature。“添加 Controller 方法”“写 SQL”是 Task，应放在 Run 的工作计划中。

推荐每个 Feature 3–8 条 AC；15–30 条时建议拆分。`size` 为 XS/S/M/L/XL，XL 默认提示拆分；大小只用于规划，不参与状态推导。少于 3 条不是非法，必须至少有一条 required AC。基础设施能力可以面向内部使用者定义价值与可验证结果。

## 4. 来源、事实与历史

Source 支持 Markdown、Axure、Word/PDF、Excel、Issue、会议纪要、用户输入和代码推断等类型；V1 实际 Adapter 范围见实施计划。来源权威等级使用 primary、secondary、reference、inferred，不用数字评分自动覆盖。

同级权威来源冲突需记录并阻塞确认。代码反推只能是 inferred；不能自动升级为 confirmed。同步遵循读取、提取、差异提案、显式应用，不直接覆盖已确认需求。

事实源：project.yaml、sources、requirements、features、runs、evidence、handoffs，以及人工维护的 decisions/refs。`generated/`、`cache/` 可删除再建。Feature 是当前快照，Run/Evidence/Handoff 保存历史，不使用无限增长的 Feature.history。

关系只存一个方向：Feature.requirement_refs 是需求关联事实，Requirement 的 Feature 列表由工具反查；Run.claims 是 Claim 唯一来源。状态汇总不能回写成第二份人工状态。

## 5. 状态推导原则

### 5.1 四维状态

| 维度 | 状态 | 来源 |
| --- | --- | --- |
| requirement | draft / confirmed / changed / blocked | 关联 Requirement 的确认事实 |
| implementation | not_started / in_progress / complete / blocked | Feature 当前实现记录与证据等级 |
| verification | not_started / in_progress / partial / passed / failed / blocked | 当前有效的 AC Check 与 Evidence |
| delivery | none / committed / mr_open / merged / released / deployed | 可核实交付记录的汇总 |

证据等级：declared 是人或 Agent 的声明；observed 是实际观察到代码或行为；verified 是在指定条件下验证通过。实现 complete 不等于 Verification passed。

Feature 不保存人工 lifecycle、verification.state 或 delivery.state。Check 保存证据引用和运行中/受阻的事实；工具计算汇总。`implementation.state` 仍是 V1 可编辑事实，并显示证据等级，不能伪装成自动代码证明。

### 5.2 推导顺序（上方优先）

输入先进行结构及引用校验。非法输入返回 validation error，不强行统计为 ready 或 delivered。

| 顺序 | 条件 | lifecycle |
| --- | --- | --- |
| 1 | Requirement/Implementation/Check 显式阻塞，Feature blockers 非空，或依赖未达门槛 | blocked |
| 2 | 任一关联 Requirement 为 draft 或 changed | draft |
| 3 | 已确认且 implementation = not_started | ready |
| 4 | 已确认且 implementation = in_progress | developing |
| 5 | implementation = complete，但 required AC 尚未全部有效通过 | verifying |
| 6 | 实现完成、required AC 全通过，但未达到交付门槛 | verified |
| 7 | 满足上述条件并达到交付门槛 | delivered |
| 8 | 满足上述条件，且有当前交付版本的有效部署记录 | deployed |

第 8 条是第 7 条的更具体展示。V1 默认交付门槛为 merged；依赖默认要求 delivered 或 deployed。仅 committed、仅 Run completed、零条 required AC 均不能推出 delivered。

Verification：必需 Check 有 blocked 则 blocked；任一有效失败则 failed；仍在执行则 in_progress；全部 required AC 有有效通过证据才 passed；部分通过为 partial；无有效结果为 not_started。每条 AC 可关联多个必需 Check，全部通过才算该 AC 通过。可选 AC 单独展示，不稀释必需项覆盖率。

### 5.3 证据新鲜度与交付可信度

证据绑定 acceptance_revision、Requirement revisions 及 subject（被测代码版本/工作树标识）。版本不匹配标记 stale 并重新验证，不能沿用旧 PASS。V1 采用保守的精确 subject 匹配；后续可做变更影响分析来减少重测。

同一 Check 有多次记录时，以显式 supersedes 形成替代链；两个未裁决且结果冲突的记录不能按“最新时间”静默通过。证据产物丢失、不可读取或无法核实必须展示原因，不能升级为通过。

交付记录需可核实且覆盖当前 subject；合并到无关代码分支不能算交付。V1 允许有出处的人工审查记录，必须保留 reviewer、时间与 Evidence；自动远程 MR 查询在 V2。删除或变更证据、需求或 subject 后，状态允许退回。

## 6. 多 Agent 协作、Claim 与 Handoff

Claim 存在 `Run.claims`，由 active Run 生成 `generated/claims.json`，不创建独立 Claim 文件。Scope 可以是整个 Feature、component 或仓库相对路径；component 路径来自 Project。路径重叠跨 Feature 也可能冲突。

V1 Claim 是协作提示，不是文件系统权限或分布式锁。CLI 对已知重叠返回 conflict；经协商可用显式 override 和理由继续，并记录在 Run。无法判断路径交集时保守提示。离线分支、不同机器只能看到各自已同步事实，不能承诺全局互斥。

推荐流程：加载上下文 → 找 Feature → 看依赖/Claim/Handoff → 建立 Run 和 Claim → 计划与实现 → 验证 → 关联交付 → Handoff → 结束 Run → 重建视图。

并发策略：按领域和 Feature 分片；每个 Run/Handoff 单独文件；不让 Agent 编辑聚合视图。即使 Scope 不同，对同一 Feature YAML 的写入也须 revision 比较和短时写锁、临时文件原子替换。共享文件（如 Source Registry）同样适用。多文件事务需要失败恢复，不允许半写入后报告成功。

Run 终态 completed/aborted 释放 Claim；completed 仅表示这次工作结束。心跳过期只能标为疑似遗留，不能自动认定可抢占；人工 abort 需理由。有 remaining 或 blockers 时结束 Run 必須留下 Handoff。Handoff 写入成功后再终止 Run，避免无交接即释放。

`current run` 是本地便利指针，不是事实源。按 agent-instance 标识放在 cache/current-runs/ 下；多个 Agent 共享工作区时不能共用一个 current-run 文件。自动化优先显式传 Run ID。

## 7. 推荐目录与提交策略

根目录树见 README。`.project/features/<domain>/FEAT-*.yaml` 每个 Feature 一文件；Evidence 位于 `.project/evidence/<feature-id>/`；Run/Handoff 各自按 ID 命名。

事实、轻量证据元数据和文档纳入版本管理。generated/cache 忽略，仅保留目录占位；大测试产物可在外部保存，但记录稳定地址、摘要和保留期限。refs 保存架构、开发、测试约定。根 `.project/` 为 managed，example 隔离于 examples/design/.project。

## 8. V1 范围与非目标

V1 包含七类 YAML 协议、校验、生命周期计算、基础 CLI、Run/Claim/Handoff、索引、AC 证据关联、最小本地验证执行和 Markdown 需求提案。实现顺序见实施计划。

V1 明确不做：完整 Event Sourcing、中央数据库、Web 管理后台、实时分布式锁、复杂权限系统、Agent 中央调度、Jira/GitLab 双向同步、自动修改已确认 Requirement、全自动 Feature 拆分或验收、内置 LLM、全量文档格式解析、自动提交/推送/发布/部署。

V2 可增加关键事件、结构化 Decision、Axure 等 Adapter、Git/MR/CI 集成和增量失效。V3 再评估工作队列、知识图谱、调度、可视化和发布规划；事件完全重建不是预先承诺。

## 9. 本次收敛与待决项

沿用最后一轮讨论：Session→Run、index→generated、references→refs，Evidence 独立文件，语义权威等级，CLI 不依赖 LLM。

本次补充为待评审的设计建议：删除 Feature.claims 与 Requirement.feature_refs 双写；验证/交付汇总只派生；revision 乐观并发；本地 current-run 按实例隔离；证据绑定版本；默认 merged 门槛；明确 CLI 冲突与人工覆盖边界。

Phase 0 首轮决定见 docs/decisions/0001-v1-core.md：Python、本地分发、UUIDv4、代码指纹、受限路径、人工与离线证据。跨平台与外部试点仍未验证，不宣称生产兼容性。

## 10. 首轮实施补充

Check 摘要绑定验证方法，方法变更使旧 Evidence stale。可选 AC/Check 不影响 required 汇总。未裁决的有效通过/失败冲突显示 blocked。恢复日志位于独立 transactions，不可作为 cache 删除。run show current 从事实精确匹配实例的 active Run；零个返回不存在、多个要求显式 ID，不依赖缓存指针。

## 11. Phase 4 实施补充

见 [验证与交付决定](decisions/0002-phase4-verification.md)。命名 JUnit 断言绑定 Check，退出码不单独产生 PASS；产物独立保存。执行在锁外进行、结果在锁内检查完整上下文后提交。自动 Git 对象观察与人工 MR 审查明确区分，只有覆盖当前 subject 的证据参与当前交付汇总。

## 12. Phase 5 实施补充

见 [来源与提案决定](decisions/0003-phase5-sources.md)。只提取具有稳定 key 的结构化 Markdown 块；Agent 输入也只提供结构化候选。提案绑定完整基础事实和输入文件摘要，应用在锁内重新生成并完整比对；不能靠修改摘要或候选字段突破确认保护。已有 confirmed 变化后 changed，其他 primary 冲突保留旧内容并 blocked，删除块保留需求与引用。拆分计划只创建未实现、未验证的新 Feature。审查记录与事实同事务保存，属于操作出处，不能代替行为 Evidence。

## 13. Phase 6 实施补充

见 [Skill/Eval 决定](decisions/0004-phase6-skill-eval.md)。Skill 独立于厂商目录，按需读取 references；确定性 CLI 场景与真实 Agent 观察分离。评分绑定套件和 transcript 摘要，不认证工具身份、不自动验收真实接力。顺序跨机器交接使用代码/事实 snapshot 与既有 HEAD bundle，bootstrap 校验同一代码 subject；它不提供分布式锁。Codex → 本地 DeepSeek Harness 真实试点已回传并完成独立审阅，结果与测量口径见 [试点报告](pilot-report.md)。

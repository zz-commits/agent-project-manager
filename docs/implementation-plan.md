# V1 实施计划

2026-09-30 建立设计草案，2026-10-08 用户采纳首轮方案并完成 Phase 0–6 实现与真实试点。2026-10-09 PR #1 已合并，[v0.1.0](release-v0.1.0.md) 已发布，实际合并提交重新通过 266 项测试、46/46 required AC 与 Ubuntu/macOS CI。下文阶段范围保留各轮历史边界；它们不替代最新 Run/Handoff 和发布事实。优先级 P0 为必需基础，P1 为 V1 完整闭环，P2 为候选扩展。

## 当前维护顺序

用户确认：先更新发布状态和验收恢复文档，再固化默认演练、手动触发的发布流程，随后用这批真实维护任务记录使用闭环与问题。维护任务登记为独立 Feature，观察结果见 [维护使用报告](maintenance-trial.md)。新的版本发布另按当次明确指令执行；V2 候选优先级依据实际使用证据决定。

## 1. 阶段与验收

| 阶段 | 优先级 | 产出 | 前置依赖 | 验收条件 |
| --- | --- | --- | --- | --- |
| Phase 0 协议评审 | P0 | 冻结七模型、生命周期、并发/证据规则，选择语言与发布方式 | 当前草案 | 3–5 个真实 Feature 可表达，待决项有记录；新 Agent 仅靠文档能准确接手 |
| Phase 1 模型与校验 | P0 | schemas、解析器、引用/依赖检查、有效/非法数据集 | Phase 0 | 重复 ID、未知字段、悬空引用、依赖环、缺 required AC 都可定位报错 |
| Phase 2 状态与只读 CLI | P0 | Reducer、索引、init/list/show/status/rebuild/doctor | Phase 1 | 固定输入可重复生成一致结果；删除 generated 后可恢复；未验证不能显示 delivered |
| Phase 3 Run/Claim/Handoff | P0 | start/update/finish/abort、实例指针、冲突检查、写入恢复 | Phase 2 | 重叠 Claim 被发现；同文件并发不会静默覆盖；中止后可追溯接手 |
| Phase 4 验证与交付关联 | P1 | AC Check、Evidence、本地命令执行/人工记录、Git 引用 | Phase 3 | 无执行/失败/过期证据均不通过；完成可追溯到有效 Evidence 与交付版本 |
| Phase 5 需求接入 | P1 | Source Registry、Markdown Adapter、差异提案与应用、Agent 提案导入 | Phase 4 | 不静默覆盖 confirmed 需求，过期提案拒绝，来源可回溯 |
| Phase 6 Skill 与试点 | P1 | 精简 SKILL.md、references、使用指南、Eval 与真实试点报告 | Phase 5 | 至少两种 Agent 完成同一 Feature 接力，正确回答状态并保留证据链 |

虚构示例已隔离到 examples/design；根 .project 登记十四个真实 Feature 与 AC，状态只依据实际验证更新。Phase 1–6 已实现；Codex → 本地 DeepSeek Harness 接力已回传并独立审阅，最终 46 条 required AC 的状态见根事实与阶段验收报告。

## 2. 推荐开发顺序

Feature/AC 与状态规则 → Requirement/Project/Source → Run/Evidence/Handoff → 校验器 → Reducer → 索引与查询 → 写入事务 → Claim/Handoff → Verification → Source Adapter → Skill/Eval。

优先验证“是否准确判断完成”和“能否交接”，再增加输入格式。Markdown 首先实现；Axure 为 P2/V2 候选，如试点必须使用，可替换 Phase 5 的 Adapter，但不能同时扩大 V1 到所有格式。

## 3. 未来实现目录职责

- `schemas/`：七类机器校验规范及通用定义，版本明确。
- `src/`：模型、加载/引用解析、状态推导、原子持久化、索引、Claim 检测、验证执行和 Adapter 接口。具体包结构依语言确定。
- `cli/`：参数解析、稳定输出和错误映射；不重复实现业务规则。
- `docs/`：设计协议、实施计划、迁移决定和使用说明。
- `.project/`：本项目真实管理记录；example 数据已隔离到 examples/design/.project。

tests/fixtures、Python 工具链、evals 和正式 Skill 已建立。

## 4. 必测场景与发布门槛

| 场景 | 必须观察到的结果 |
| --- | --- |
| 项目恢复/Feature 定位 | 找到需求、AC、状态原因、剩余工作和最近 Handoff |
| 实现 complete 但未测试 | verifying，不是 verified/delivered |
| 全部 required AC 通过但仅 Commit | 默认门槛下 verified，不是 delivered |
| 合并记录存在但验证失败 | 保留合并事实，生命周期不显示 delivered |
| AC/Requirement/subject 变化 | 旧证据失效，显示需重验原因 |
| 两个 Agent 同 Scope/交叉路径 | 检出潜在冲突，不静默 Claim |
| 两个 Agent 不同 Scope 修改同一 YAML | revision 冲突被检测，无覆盖丢失 |
| Run 异常中断/多文件写入中断 | doctor 指出可恢复状态，不伪报完成 |
| 结束 Run 但有遗留 | Handoff 存在且引用有效，Claim 释放 |
| Source 多主来源冲突/提案过期 | 阻塞确认或拒绝应用，不自动选胜者 |
| Evidence 缺失/冲突/超时 | 不产生有效 PASS |
| 缓存与索引全部清空 | 从事实恢复相同业务结果 |

发布前，上述确定性检查必须全部通过。用 3–5 个真实 Feature 建立人工标注结果，核对状态/追溯准确率；试点记录上下文恢复耗时、错误完成判断次数、交接补问次数和元数据冲突次数。目标是关键状态用例零误判、所有宣称交付的样例证据链完整；耗时改善先建立基线，不虚构收益数字。

Skill Eval 对比有/无协议时的恢复正确性、token、耗时与结果稳定性。跨 Agent 测试从两种工具开始，扩展到 Codex→Claude→DSH 时保持同样的数据契约。

## 5. 风险与处理

最高优先风险是状态双源、虚假通过和并发丢写。分别通过单向引用与派生汇总、版本绑定证据、revision/原子写入解决。离线多副本无法强互斥属于 V1 已知边界，通过同步后冲突检查和明确 Handoff 管理，不宣称已解决分布式锁。

证据保存期限、Git subject 对应、人工证据可信度、ID/路径兼容性在 Phase 0 冻结。没有明确可验证策略时保留 not_verified，不用推断填补。

## 6. V1 明确不做

不做完整事件溯源、中央数据库、Web 后台、分布式实时锁、复杂权限、中央 Agent 调度、全自动需求/Feature 生成、LLM 自动验收、所有来源格式、Jira/GitLab 双向同步、自动提交推送发布部署。不把 Skill 编写提前到数据协议和 CLI 闭环之前。

## 7. V2 / V3 演进

| 版本 | 候选能力 | 启动条件 |
| --- | --- | --- |
| V2 | 结构化 Decision、关键 Event Log、Schema migration、Axure/Excel/Issue Adapter、Requirement Diff | V1 真实试点证明协议稳定 |
| V2 | Git 扫描、MR 自动关联、CI Evidence、代码到 Feature 建议关联、影响分析 | 明确证据有效性与连接器权限边界 |
| V3 | 工作队列、依赖/需求图谱、辅助规划、Agent 调度、风险与发布规划、Dashboard | 多项目规模和并发需求足够明确 |
| V3 候选 | 事件驱动 Snapshot 重建、共享协调服务 | 确认收益大于迁移与运维成本 |

演进保持 CLI 输出版本与文件 version 明确，迁移先预览、可回退。V2 关键事件不等于完整 Event Sourcing；V3 也不强制重写成熟 V1。

## 8. 下一次启动实施时

V1 已实现并冻结 Python 3.12+/uv 与七模型协议。后续先读取最新事实、Handoff 和用户范围，再登记有可验证 AC 的真实维护 Feature。候选能力不构成部署、外部同步或持续运行授权。

## 9. 本项目试点与阶段边界

决定见 [0001-v1-core](decisions/0001-v1-core.md)。Phase 1 为结构/引用校验，Phase 2 只读评估已有 Evidence，Phase 3 为 Run、范围冲突、交接与恢复。Requirement/Feature 首轮人工维护后校验。这些阶段当时将跨 Agent 试点和发布留到后续；两者现已按后续用户指令完成。

## 10. Phase 4 本轮范围

[执行决定](decisions/0002-phase4-verification.md)：验证执行、Evidence 导入和只读汇总、本地 Git Commit 与人工 MR 关联。三个真实 Feature 共 12 条 required AC。本轮不接远程 MR API、不提交或推送，不修改 Requirement 确认状态。后续来源提案与应用见 Phase 5。

## 11. Phase 5 本轮范围

[来源决定](decisions/0003-phase5-sources.md)：Source 注册、Markdown Adapter、Requirement 显式差异应用、Agent 需求与 Feature 拆分计划导入。三个真实 Feature 共 10 条 required AC。确认保护、来源冲突、删除保留、过期/篡改拒绝、事务恢复为本轮验收重点；不增加远程 Adapter、自动确认、LLM 拆分、提交或发布。正式 Skill 与跨 Agent Eval 属于 Phase 6。

## 12. Phase 6 当前范围

[阶段决定](decisions/0004-phase6-skill-eval.md)：正式 Skill/references、隔离 CLI Eval、真实观察评分器与可校验代码 subject 的本地交接包。三个真实 Feature 共 9 条 required AC；程序验收不代替真实两工具接力。第二种工具为用户本地 DeepSeek Harness，操作见 [指南](pilot-guide.md)，当前报告见 [试点报告](pilot-report.md)。用户已回传原始会话、终态 Run/Handoff 与 12 场景 Eval；Codex 复核正确恢复答案并修正指标，以 manual_review Evidence 验收最后两个 Check。最终结果见 .project/artifacts/phase6-relay-acceptance.json。没有配对 baseline，不宣称 Skill 效率收益。上述为 Phase 6 历史验收；实际发布提交的后续验收和交付见 v0.1.0 发布记录。

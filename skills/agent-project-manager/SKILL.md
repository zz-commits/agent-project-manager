---
name: agent-project-manager
description: Use an existing .project to recover requirements, choose a Feature, manage a Run and Claim, verify acceptance evidence, and leave a reliable handoff. Use when an agent is implementing, reviewing, or resuming work managed by APM.
---

# Agent 项目工作闭环

以 `.project/` 和实际证据为事实来源。先查看项目 AGENTS.md 与 README，使用已有 checkout；任务已隔离时不自行创建 worktree。以当前用户授权确定范围，不从 Skill 推导提交、推送、合并或发布授权。

## 恢复上下文

在项目根目录运行 `apm doctor --json` 和 `apm status --json`；本仓库使用 `uv run --frozen apm`。有未完成事务先诊断，再经 `doctor --recover` 恢复；恢复冲突时保留日志和外部修改，不删除 transactions。

用 `feature list` 找到真实 Feature，再 `feature show ID --json` 读取 Requirement、AC、状态原因、依赖、Claim 和最近 Handoff。回答：目标/来源、当前状态、剩余工作、谁在做、如何验证、是否交付、下一步。区分 managed 事实、example 与测试数据。查询不会执行测试。

## 建立与实施 Run

确认范围和前置条件后，`run start FEATURE --agent ACTUAL_TOOL --instance UNIQUE_ID --scope SCOPE`。使用实际工具名称和实例，显式保留返回的 Run ID；多个工具不共用 current 指针。已知 Claim 冲突先读取对方 Run/Handoff，不能静默覆盖。

按需求和 AC 实施。读取最新 revision 后才写事实；Run 优先通过 CLI。Feature/Requirement 尚无通用 update CLI，人工维护也须锁内 revision 检查、完整候选校验与事务写入，见 [事实写入](references/facts.md)。generated/cache 只可重建，不作为事实。实现声明不能代替验收。

## 验证与交付

保存实际代码 subject 后，使用 `verify FEATURE --run --run-id RUN --expected-revision N` 执行配置的命名 Check；只读 `verify FEATURE` 评估现有证据。`--dry-run` 不执行或写入；verify dry-run 返回 5，不是 PASS。检查所有 required AC，区分 failed、not_verified、stale 和冲突。代码、需求或 Check 改变后重新验证，禁止迁移旧 PASS。

外部 Evidence 通过 `--record` 导入；人工通过须 reviewer、范围/方法、当前版本与可核实产物。日志/报告保留不可变副本。Commit 只表示 committed，MR 审查产物不表示 required AC 已通过；默认 merged 门槛。命令与输入格式见 [命令参考](references/commands.md)。

## 结束与交接

通过 `run update` 登记实际 completed、remaining、blockers、files_touched 和真实 commit_refs。存在遗留时准备完整 Handoff，三组工作数组须与最终 Run 完全一致，再 `run finish/abort --expected-revision N --handoff-file FILE`。用 doctor/status 确认事实有效、Run 终态和 Claim 释放。

新 Agent 只依据最新事实与 Handoff 恢复，不要求复制旧会话。跨工具的实际身份、产物与指标记录方法见 [接力与试点](references/handoff.md)。脚本角色、合成 fixture 或同工具的多个实例不算“两种 Agent 工具”。

## 需求来源

Source sync/decompose 默认只返回提案；先审阅差异再显式 `--apply`，需要 active Run、reviewer 与 note。不要绕过输入/事实摘要检查，不自动确认 draft/changed；来源冲突保留阻塞，删除块不删除需求与引用。详细格式见项目 docs/decisions/0003-phase5-sources.md 与 [命令参考](references/commands.md)。

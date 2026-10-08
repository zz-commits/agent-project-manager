# 状态恢复问题

针对 OUTPUT/contexts/CASE-REPETITION 中的独立合成项目，读取该项目 .project 和代码，通过 apm --project PATH 查询。不要使用 OUTPUT/report.json 的标准答案或其他场景答案。无需改写事实或实施功能。

1. 当前 Feature 的生命周期、verification、delivery 分别是什么？用三个字符串返回。
2. 目标、Requirement、required AC 与最近 Handoff 是什么？当前还剩什么，为什么？
3. 哪些 Evidence 有效或失效？指出 ID、Check 和失效原因；Commit 或 merge 能否证明功能验收？
4. 是否有活跃 Claim 或冲突？接手前应做什么，下一条实际可执行命令是什么？

保留完整实际回答和执行 transcript。状态答案使用 `{"lifecycle":"...","verification":"...","delivery":"..."}`。不用估计 token 或时间。工具没有提供的数据记录 null。

有 Skill 条件：先读取 skills/agent-project-manager/SKILL.md，按需读 references。
无 Skill 条件：只提供项目事实、代码及上述问题，不提供该 Skill。两种条件采用独立会话、相同问题与输入快照，审查者保存实际会话与实验配对标识。

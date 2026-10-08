# 接力与试点

前一个 Agent 经 run update 登记实际 work，生成 Handoff（新 HANDOFF-UUIDv4），再 finish/abort。Handoff 字段为 version/id/run_ref/feature_refs/summary/completed/remaining/blockers/recommended_next/evidence_refs/context_refs/created_at；三组工作数组须与最终 Run.work 逐项一致。context_refs 是仓库相对路径或 Source ID，不能引用临时文件作为永久必要上下文。

接手工具先读 AGENTS/README、doctor/status、feature show 和最近 Handoff；回答目标/来源、AC、状态原因、剩余/阻塞、活跃 Claim、有效证据与下一步，再建立自己的实际工具 Run。当前实例指针不共享；Run terminal 后 Claim 才释放。发现未完成事务或仍活跃的旧 Claim 要先处理，不用心跳过期推断可以抢占。

真实接力登记前后 tool/version/instance、同一 Feature ID、两个 Run、Handoff、有效 Evidence、原始 transcript 和本地产物 SHA。不要把脚本角色或填入的 tool 字段当作实际工具执行证明。审查者核对真实运行后登记 reviewer/note；自动评分只比较提交的答案和可检查文件，不认证供应商身份。

用于比较 Skill 效果时：固定同一输入快照和问题，分别以有/无 Skill 条件运行实际 Agent；记录工具/模型版本、实际耗时、计费 token（工具未提供则 null）、补问数及冲突数。无匹配 baseline 不报告改善幅度。问题与填写格式见仓库 evals/README.md 和 docs/pilot-guide.md。

根 .project 只记录真实任务和真实证据。Eval 的 synthetic workspace 和 protocol-harness Run 均隔离，不混入项目活跃 Agent 或真实交付统计。

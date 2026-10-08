# Phase 6：正式 Skill、Eval 与试点

2026-10-08，用户确认云环境配置完成，要求开始下一阶段。范围为可移植 Skill、按需 references、使用指南、可重跑的确定性 CLI Eval、真实 Agent 结果评分及试点报告。已有环境与依赖继续使用，不重复环境发布流程。

## Skill 分发

skills/agent-project-manager/SKILL.md 采用通用 name/description frontmatter，正文只保留工作闭环和证据边界；详细命令、模板与接力操作放 references。独立于特定模型、工具及厂商目录。通过读取目录或在工具支持的用户 Skill 目录安装完整目录使用；不能只复制 SKILL.md 而丢失 references。本项目 AGENTS.md 指向该目录，不自动安装到主机或修改其他 Agent 配置。

## Eval 的测量边界

uv run --frozen python -m evals.run --output OUTPUT 执行隔离、明确标记为 synthetic 的 CLI 场景，保存各次命令/退出码/脱敏输出、有效事实、实际耗时、结果 JSON 与 JUnit。测量状态判断、证据失效、Claim/revision 冲突、交接恢复、需求确认保护和事务恢复。脚本中的角色统一为 protocol-harness，不作为真实 Agent 或两种工具接力。零场景、跳过、错误或缺失结果不能称通过。

默认只写新 OUTPUT；拒绝覆盖、非法输出路径。场景不修改根项目事实，不产生真实提交、合并、部署或 Agent 运行证据。固定评估时间/输入及规则的判断应一致；时间指标只表示 CLI 执行耗时，不是 Agent 恢复耗时。未运行 LLM 时 token、补问数、有/无协议效果比较为 null 或 not_run，不用估计值填充。

evals.score 接收同一 Eval 套件的外部 Agent 观察记录：case/repetition、condition、tool/version/instance、结构化答案、真实 transcript 路径及 SHA、reviewer/note、可选实测 elapsed_ms/token_usage/clarifications。绑定套件摘要，拒绝未知/重复记录和缺失产物；按独立预期结果评分。记录的 Agent 身份属于审查者声明，不把任意文件或 tool 标签视为自动验证过的 Agent 执行。没有观察记录不能输出 PASS，缺少同条件完整覆盖或配对 baseline 不显示比较收益。

## 真实接力门槛

本项目三个 Feature 分别交付 Skill、Eval/评分器及试点。真实接力要求至少两个不同工具，在同一 Feature 上有实际 Run/Handoff/Evidence 链，恢复正确并保留检查产物。测试中合成的工具名、同工具的两个脚本角色或子 Agent 不满足“两种工具”。用户确认第二种工具为本地运行的 DeepSeek Harness，云端无法调用其进程；先完成独立验收和 Codex Handoff，将试点保留未完成以便本地 Run 接手，真实接力两个 Check 保持未验证，回传真实执行产物后继续验收。

报告必须区分本地程序验收、真实 Agent 评分及接力门槛。Phase 6 的全部验收条件未满足时不宣称 V1 已完成跨 Agent 试点。没有自动提交、推送、发布或部署授权。

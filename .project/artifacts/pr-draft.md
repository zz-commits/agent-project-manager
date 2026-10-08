原仓库只有设计骨架，无法执行项目事实校验、验收或 Agent 交接。此 PR 实现 Python 3.12+ 的 V1 `apm` CLI，让状态依据版本绑定的事实和证据推导，并完成 Codex → 本地 DeepSeek Harness 的实际接力审阅。

- 实现七模型 Schema、确定性状态查询、Run/Claim/Handoff、修订检查、可恢复事务、命名断言验证及 Git/人工交付关联。
- 实现 Markdown/Agent 来源的只读提案与显式应用、正式 Skill、隔离 CLI Eval、离线评分和跨机器快照校验；加入 Linux/macOS CI。
- 保存 4 个 Requirement、14 个 Feature、210 条历史 Evidence 和选定验收产物。源码/测试/文档与事实/验收材料分别提交，便于分别审阅。

干净检出验证：测试夹具显式创建 Evidence 目录，避免 Git 不保存空目录导致测试失败；CI 矩阵关闭快速取消，分别检查 Linux/macOS。修正后干净检出的 264 项 pytest 通过，0 失败/错误/跳过；真实项目和设计示例的 doctor 通过；wheel 构建及 `git diff --check` 通过。提交前命令、退出码和被测 subject 见 `.project/artifacts/pr-preflight.json`；干净检出的复现与修正报告见 `.project/artifacts/pr-ci-review.json`。GitHub CI/macOS 的实际结果仍待确认。

Phase 6 的 46/46 是清单内 working_tree subject 的历史验收。提交改变当前 subject，因此新 checkout 将旧证据标为 stale，不能视作当前版本已通过全部 AC。原始会话、ZIP 和完整快照保存在独立私有归档，保存清单记录每项 SHA-256；4 个原始 manual_review artifact 引用未进入 Git，新 checkout 会显示 missing_artifact。历史 Evidence 的内容、摘要及 subject 均不改写。恢复和重新验证步骤见 `.project/artifacts/README.md`。

不自动认证提供者身份，也不宣称 Skill 效率收益。默认交付门槛为 merged；此 PR 不发布或部署。

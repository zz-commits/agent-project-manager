# v0.1.0 发布准备

发布候选为 PR #1 审阅与验收包所绑定的完整 Commit SHA，版本来自 pyproject.toml 的 0.1.0。该说明是待执行安排，不是已合并或已发布的记录。

## 发布内容

V1 包含确定性的七模型校验、状态查询、Run/Claim/Handoff、事务恢复、命名断言验证与 Evidence 导入、本地 Git/人工交付关联、Markdown/Agent 来源提案、正式 Skill、CLI Eval 与可校验快照。代码 subject 检查实际文件内容和执行位；快照包含 Git 属性文件并正确恢复暂存删除。

需要 Python 3.12+。核心 CLI 通过 wheel/sdist 分发；Skill/Eval 和完整指南从源码仓库读取。包不包含原始 Agent 会话、私有回传 ZIP 或独立验收包。无内置远程来源服务、数据库或自动发布器。

## 执行顺序

1. 核对 PR 最终 HEAD、CI、正式验收清单、包的独立安装检查和 SHA256SUMS；出现新提交则重新验证。
2. 完成 PR 审阅后再合并。观察实际合并 SHA，不把 committed 或 PR 存在写作 merged。
3. 固定实际发布对象，重新验证该对象的 subject/验收状态；建立 v0.1.0 标签和 GitHub Release，附 wheel、sdist、SHA256SUMS 和发布说明。原始私有记录继续独立保存。
4. 发布后重新读取标签、Release 状态与资产摘要，记录真实交付出处。首次发布默认 GitHub Release；PyPI 需单独确定目标与凭据。

候选产物在 dist/，安装检查与摘要在 `.project/artifacts/release/`。正式发布会修改远程 main/标签并公开资产，须在可审阅结果完成后按用户最终指令执行。

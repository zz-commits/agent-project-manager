# V1 PR 审阅

2026-10-09，审阅对象为 [PR #1](https://github.com/zz-commits/agent-project-manager/pull/1)。范围包括协议/引用校验、代码 subject、命名 Check 与导入 Evidence、事务恢复、Run/Handoff、来源提案、交付关联、快照恢复和 Python 包。

## 已修复的阻断问题

1. `current_subject` 原先依据 `git diff` 判定干净代码。`assume-unchanged` 或 `core.filemode=false` 可隐藏实际内容/执行位变化，使旧 Commit subject 被错误保留。现在逐文件比较实际类型、内容与 HEAD blob；Git 忽略的变化仍产生新的 working_tree subject。新增两个回归场景已在修正前失败、修正后通过。
2. 交接导出白名单缺少已纳入仓库的 `.gitattributes`，导致当前项目无法导出。暂存删除的文件也会从 Git index 路径集合消失，恢复时与原 subject 不一致。现在包含 `.gitattributes` 与 HEAD 路径/删除标记；恢复测试覆盖属性文件、暂存删除、执行位、既有 HEAD 和原 subject。

3. 默认 sdist 会带入根 `.project` 的真实事实 YAML。源码包现显式限定源码、Schema、测试、文档、Skill/Eval、隔离示例和构建文件，排除本项目运行事实；构建检查同时验证 wheel 与 sdist 边界，并从 sdist 重建 wheel。

上述修正落实既有精确代码绑定、可恢复交接和发布包边界，不改变 Schema、AC、交付门槛或来源确认流程。本轮没有发现其他可复现的阻断项；这不构成对未覆盖平台或全部输入的保证。

## 验收和保存

先提交修正及本说明，固定完整 Commit SHA，再执行全量 pytest、配置的 required Check、真实接力材料的独立复核与 wheel 安装检查。新的 Evidence 由本轮 Run 产生，明确替代旧 Check 证据；历史记录保留原 subject，不迁移旧 PASS。实际命令、退出码和完整提交绑定保存在 `.project/artifacts/v1-formal-acceptance.json`。

两个真实接力 Check 复核用户已回传的原生会话、Run/Handoff、恢复回答与测量锚点；这是对历史真实执行的重新独立审阅，不宣称 DeepSeek 在本轮修正提交上重新运行。当前快照恢复行为另有本轮程序验证。

V1 的精确 subject 包含 Git HEAD。将新 Evidence 再提交到 Git 会改变 HEAD，使该批证据失效。因此本轮最终代码提交固定后，新事实及不可变产物保存在独立可校验的验收包，包内附同一 HEAD 的 Git bundle；恢复后检查实际 subject 与 46 条 required AC。PR 保存源码修正和审阅说明，验收包另行保存。合并产生新 SHA 时须针对实际发布对象重新评估，不能把 PR 的 PASS 自动迁移过去。

事务日志在原工作区保留，未完成事务阻止导出；原生会话和私有 ZIP 不公开上传。生产者身份来自用户提供的原始记录与审阅，不宣称提供者自动认证，也不推算费用或 Skill 效率收益。发布安排见 [v0.1.0 准备](release-v0.1.0.md)。

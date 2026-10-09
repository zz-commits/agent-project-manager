# 本项目真实管理记录

根目录为 managed 项目：用户采纳的首轮方案是来源，第一个 Requirement 对应校验、状态、重建、Claim、交接五个 Feature；第二个 Requirement 对应 Phase 4 执行验证、Evidence 导入、Git/人工交付三个 Feature。状态只依据实际工作与验证更新。

第三个 Requirement 对应 Phase 5 来源注册/读取、差异应用与 Agent 提案三个 Feature；第四个 Requirement 对应 Phase 6 Skill、Eval 和真实试点三个 Feature，共十四个 Feature。真实状态与验收见最近 Handoff 和 artifacts 下的阶段验收清单。DeepSeek 本地执行已回传并完成独立审阅；历史 Phase 6 subject 验收为 46/46，当前状态仍须按实际代码版本和可用产物推导。

事实位于 sources、requirements、features、runs、evidence、handoffs。Feature 不保存推导状态；Claim 只在 Run 中。代码存在、Run completed、测试结束均不自动代表交付。

generated/cache 可重建；transactions 保存未完成写入恢复记录，不能随意删除。代码 subject 排除根 .project，事实版本和 Check 定义独立绑定 Evidence。

虚构样例在 [examples/design/.project](../examples/design/.project/README.md)，不代表真实进度、Agent 或 PASS。

artifacts 保存验收映射、命令报告和 UUID 目录下的不可变副本；evidence 下的 YAML/JSON 专用于 Evidence 实体。历史测试 XML 保留，新增报告写入 artifacts。Git 只保存选定产物；原始会话与 ZIP 在独立归档中，摘要及恢复步骤见 artifacts/README.md 和 retention-manifest.json。缺失的原始文件保留其事实引用，不创建占位文件或迁移旧 PASS。

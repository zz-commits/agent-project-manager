# Agent 工作约定

## 当前任务边界

本项目目前只包含设计、计划和示例。没有用户后续实施指令时，不创建业务代码、CLI 实现、依赖清单、可执行 Schema 校验器或自动化服务。

先读 README.md、docs/design.md、docs/implementation-plan.md。修改模型时同步检查 docs/yaml-schema.md、docs/cli-protocol.md 与 .project 示例的一致性。

## 数据约定

- `.project/` 目前全部为设计示例，不得当作真实完成记录、测试结果或正在工作的 Agent。
- Feature 是可独立验收的价值单元；技术任务记录在 Run 中。
- Requirement 记录需求确认状态，不记录开发进度。
- Feature 保留当前事实与证据引用；不堆积完整历史。
- 生命周期和验证汇总由规则推导；不手写 `done` 或聚合状态。
- Claim 只存在于 Run；不在 Feature 或独立 Claim 文件中重复维护。
- `generated/` 与 `cache/` 不是真实状态来源，不提交生成内容。
- 不把代码存在、Agent 声明、Run 结束或 Commit 存在当成验收通过。
- 不伪造测试、SHA、MR、发布或部署证据；无法验证就保留未验证。

## 后续实现阶段

CLI 尚未实现，不能把文档示例当成可运行命令。实现后优先经 CLI 写入事实文件；必要的直接编辑必须经过校验。

开始工作前：读取项目上下文、Requirement、Feature、依赖、Claim 与最近 Handoff。建立 Run 并声明范围。共享 Feature 元数据写入需要修订号检查和短时原子写入，Scope 不同不代表可以无条件覆盖同一 YAML。

结束工作前：记录已完成与剩余事项、真实验证结果和交付引用；有遗留事项就创建 Handoff，最后终止 Run 并释放 Claim。提交、推送、发布按当次用户授权执行。

源码的具体模块、语言、测试框架在协议评审后确定。上层项目的只读来源约束继续适用。

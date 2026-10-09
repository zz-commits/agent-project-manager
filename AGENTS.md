# Agent 工作约定

## 当前任务边界

用户于 2026-10-08 采纳 V1 core 建议，以本项目为真实试点。Phase 1–6 和真实 DeepSeek 回传审阅已完成。2026-10-09 用户明确授权合并和发布，PR #1 已合并，v0.1.0 标签指向 eec67f2a246c94192e7bf35f1be611e76881fa23；实际合并提交的 266 项测试、46/46 required AC 和 Ubuntu/macOS CI 通过。真实发布及交付记录随私有发布验收包保存，见 docs/release-v0.1.0.md。

当前用户授权按顺序更新发布/恢复文档、固化手动发布流程，再用这些维护任务评估真实使用闭环。本轮不自动发布新版本。历史逐 Check 记录保留原 subject；提交和新 checkout 改变 subject，历史 PASS 不自动代表当前验收通过。产物保存范围见 .project/artifacts/README.md。

先读 README.md、docs/design.md、docs/implementation-plan.md。修改模型时同步检查 docs/yaml-schema.md、docs/cli-protocol.md 与 .project 示例的一致性。

管理本项目工作时读取 [正式 Skill](skills/agent-project-manager/SKILL.md)，按需读取其 references；接力操作见 [本地指南](docs/pilot-guide.md)。Eval 的 protocol-harness 角色是合成数据，不充当真实第二种工具，Agent 指标缺失填 null。离线评分不认证工具身份，也不自动通过真实试点。

## 数据约定

- 根 `.project/` 为真实事实，虚构示例隔离到 examples/design/.project，示例不得当作真实完成记录、测试结果或正在工作的 Agent。
- Feature 是可独立验收的价值单元；技术任务记录在 Run 中。
- Requirement 记录需求确认状态，不记录开发进度。
- Feature 保留当前事实与证据引用；不堆积完整历史。
- 生命周期和验证汇总由规则推导；不手写 `done` 或聚合状态。
- Claim 只存在于 Run；不在 Feature 或独立 Claim 文件中重复维护。
- `generated/` 与 `cache/` 不是真实状态来源，不提交生成内容。
- 不把代码存在、Agent 声明、Run 结束或 Commit 存在当成验收通过。
- 不伪造测试、SHA、MR、发布或部署证据；无法验证就保留未验证。

## 后续实现阶段

可运行与拟议命令以 README 和 docs/cli-protocol.md 区分。优先经 CLI 写 Run；首轮 Feature/Requirement 人工维护后必须运行 uv run --frozen apm doctor --json。

开始工作前：读取项目上下文、Requirement、Feature、依赖、Claim 与最近 Handoff。建立 Run 并声明范围。共享 Feature 元数据写入需要修订号检查和短时原子写入，Scope 不同不代表可以无条件覆盖同一 YAML。

结束工作前：记录已完成与剩余事项、真实验证结果和交付引用；有遗留事项就创建 Handoff，最后终止 Run 并释放 Claim。提交、推送、发布按当次用户授权执行。

Python 3.12+、uv 锁文件、JSON Schema、ruamel.yaml、argparse、pytest。执行 uv sync --frozen 与 uv run --frozen pytest。云任务已隔离，使用现有 checkout，除非用户明确要求不创建 Git worktree。上层项目的只读来源约束继续适用。

写入在锁内检查 revision。未完成事务先用 doctor --recover 处理，transactions 不是可删除缓存。只记录真实验证，未提交/合并时 delivery.records 保持为空。

Phase 4 使用 verify --run/--record 和 feature link-commit/link-mr；写入必须带 active Run 与当前 Feature revision。Check 命名断言、超时和 JUnit 配置见 docs/decisions/0002-phase4-verification.md。保存新 subject 后重新执行相关验证，禁止把先前 subject 的 PASS 直接迁移为当前结果。

Phase 5 source sync 和 requirement decompose 默认只生成只读提案；应用须 --apply、active Run、reviewer 与 note。不得手改提案摘要、跳过来源/事实快照检查，或自动确认 changed/draft 需求。来源删除不删除 Requirement，冲突不自动选胜者。应用审查产物是操作出处，不是 PASS Evidence。格式与边界见 docs/decisions/0003-phase5-sources.md。

# agent-project-manager

面向 Coding Agent 的项目事实、状态与交接 CLI。Phase 1–6 已实现，包含真实 Codex → 本地 DeepSeek Harness 接力及独立审阅。[v0.1.0](https://github.com/zz-commits/agent-project-manager/releases/tag/v0.1.0) 已于 2026-10-09 发布，标签和 main 合并提交为 `eec67f2a246c94192e7bf35f1be611e76881fa23`。该提交重新通过 266 项测试、46/46 required AC 与 Ubuntu/macOS CI；原始会话仍私有保存。远程来源接入尚未实现。

发布的 wheel、源码包和 SHA256SUMS 可从 Release 下载；需要 Python 3.12+。安装示例：`python -m pip install ./agent_project_manager-0.1.0-py3-none-any.whl`，随后运行 `apm --version`。发布事实、历史阶段证据与私有验收包恢复步骤见 [v0.1.0 发布与恢复](docs/release-v0.1.0.md)。

## 开发与使用

需要 Python 3.12+ 和 uv，在仓库根目录执行：

```bash
uv sync --frozen
uv run --frozen pytest
uv run --frozen apm doctor --json
uv run --frozen apm status --json
uv run --frozen apm feature list --domain core --json
uv run --frozen apm rebuild --at 2026-10-08T00:00:00Z
```

--project PATH 指定项目目录，省略时从当前目录向上定位最近的 .project/project.yaml。通用参数可放在子命令前后。--json 输出包含协议版本、成功标记、数据、警告和错误。状态查询不会执行测试。

```bash
uv run --frozen apm project init --name demo --project /tmp/apm-demo
uv run --frozen apm --project examples/design doctor --json
```

新项目为空是合法状态。首轮 Requirement/Feature 人工维护 YAML，并运行 doctor。Run 支持 start/show/update/finish/abort；update 文件是 goal/work/files_touched/commit_refs/heartbeat_at 中部分字段的对象，work 如提供须完整。

写入支持 --dry-run，不创建锁、记录、缓存或派生文件。写入中断后先运行 doctor，再用 doctor --recover 在锁内恢复。恢复日志位于 .project/transactions，不可当普通缓存删除。

## 目录与文档

- [总体设计](docs/design.md)、[字段契约](docs/yaml-schema.md)、[CLI 协议](docs/cli-protocol.md)、[实施计划](docs/implementation-plan.md)、[Agent 约定](AGENTS.md)。
- src/apm：加载、结构/引用校验、状态推导、事务及命令入口。
- schemas/v1：七模型 JSON Schema 及共享定义，随 Python wheel 打包。
- .project：本项目真实 Requirement、Feature、Run、Evidence 与 Handoff；新增维护任务也使用这些事实。
- [正式 Skill](skills/agent-project-manager/SKILL.md)、[Eval 使用说明](evals/README.md)、[DeepSeek 本地接力指南](docs/pilot-guide.md)、[试点报告](docs/pilot-report.md)。
- [隔离的设计示例](examples/design/.project/README.md)：虚构数据与原始基线，不代表真实执行。
- tests：合法项目数据、非法输入、状态、CLI、并发与恢复测试。

完整 pytest 在 Linux 与 macOS GitHub CI 上实际执行通过，具体提交和任务结果见 [PR #1](https://github.com/zz-commits/agent-project-manager/pull/1)。DeepSeek Harness 回传了 Windows 上 12 个 CLI Eval 场景的执行记录。没有常驻服务、数据库或必要外部业务凭据。默认 merged 交付门槛；测试通过与本地代码存在均不表示已经交付。

## 验收记录与提交范围

Git 保存源码、锁文件、测试、文档、真实项目事实及经选择的不可变验收产物。原始 Agent 会话、回传 ZIP 和完整快照保留为独立归档，不自动提交；保存范围、摘要和恢复说明见 [.project/artifacts/README.md](.project/artifacts/README.md) 与 [保存清单](.project/artifacts/retention-manifest.json)。

Phase 6 的 46/46 对应历史 working_tree subject；v0.1.0 又针对实际合并提交生成了新的 46 条验收证据，并登记真实 merged/released 出处。新事实随私有发布验收包保存，避免额外 Git 提交改变被验收 HEAD。只检出 Git 时，历史证据仍可能显示 stale/missing_artifact；按发布指南在新目录恢复验收包，才得到该发布提交的完整事实。doctor 校验结构与引用，不等于当前 required AC 已通过。后续代码提交仍须重新验证，不能迁移旧 PASS；发布也不代表部署。

## 验证与交付关联

协议细节见 [Phase 4 决定](docs/decisions/0002-phase4-verification.md)。Project.commands 配置 argv/cwd、timeout_seconds 和 result={kind: junit, path: 仓库相对路径}；Check.testcase_refs 指定完整 classname.name（参数化用例包含参数后缀）。没有对应命名断言时，退出 0 也不会生成 PASS。

以下 FEATURE_ID、RUN_ID、N 为需要替换的当前真实 ID 和 revision：

```text
apm verify FEATURE_ID
apm verify FEATURE_ID --run --run-id RUN_ID --expected-revision N
apm verify FEATURE_ID --record evidence.yaml --run-id RUN_ID --expected-revision N
apm feature link-commit FEATURE_ID HEAD --run-id RUN_ID --expected-revision N
apm feature link-mr FEATURE_ID --file mr.yaml --run-id RUN_ID --expected-revision N
```

verify 默认只读。写入要求 active Run 包含 Feature；执行前 Feature.subject 必须是当前代码。成功执行/导入后 Feature revision 递增，返回 new_evidence、required_passed 和各 Check 结果。退出 5 明确区分未通过或未执行；--dry-run 不执行/写入，verify dry-run 也返回 5，不能当作通过。

自动执行中同一个命令只运行一次，并按各 Check 的命名用例判断；零测试、缺失、重复、跳过、旧报告、超时均不能通过。报告与日志保存为独立带摘要副本；敏感环境绑定值在日志和文本产物中脱敏。新 Evidence 显式替代该 Check 的旧证据，不复活旧 PASS。

--record 接受完整 Evidence 或非空列表，保留声明的版本、subject 和 producing Run。人工 passed 需要 manual_review 类型、reviewer 与本地产物；截图/API 响应/代码引用不能独立产生验证通过；测试 passed 导入需要匹配的 JUnit 命名断言。MR 文件格式为 {record, evidence}；Evidence 绑定 delivery_ref/delivery_state 并要求 reviewer。本地 Git 关联只读观察已有对象，不创建提交；committed 不满足默认 merged 门槛。

执行器只支持 UTF-8 JUnit XML，不解析 DTD/实体、不下载远程产物。新产物在 .project/artifacts 下独立 UUID 目录，与事实引用通过同一可恢复事务提交。verify 不改变 Requirement 确认状态，也不自动标记 implementation complete。

## 来源与需求提案

见 [Phase 5 决定](docs/decisions/0003-phase5-sources.md)。Markdown 来源注册为 adapter.name=markdown、type=markdown、location.path=仓库相对路径。文件最多 2 MiB，只提取下面这种专用代码块，其他正文不会自动变成需求：

````markdown
```apm-requirement
key: login
title: 用户登录
description: 验证用户凭据
acceptance:
  - 有效凭据可以登录
```
````

key 在一个来源中必须唯一且稳定。source list/show 返回 Registry SHA-256；source add 使用完整 Source 文件、active Run 与该 expected-digest。以下 ID、DIGEST 和输入文件均须替换为真实值：

```text
apm source list --json
apm source add --file source.yaml --expected-digest DIGEST --run-id RUN_ID
apm source sync SOURCE_ID --json > /tmp/source-proposal.json
apm source sync SOURCE_ID --apply /tmp/source-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "已审阅差异"
apm requirement list --json
apm requirement show REQUIREMENT_ID --json
apm requirement decompose REQUIREMENT_ID --file .project/artifacts/feature-plan.json --json > /tmp/feature-proposal.json
apm requirement decompose REQUIREMENT_ID --apply /tmp/feature-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "已审阅拆分计划"
```

sync/decompose 默认只读，返回的 JSON 可直接供 --apply 使用。它同时显示完整候选、差异、输入摘要及来源冲突；应用前重新检查事实/文件快照和生成规则。新需求为 draft，已有 confirmed 变化后为 changed，并移除旧 confirmation；不会自动确认。其他 primary 来源不同意时保留旧内容、标 blocked；删除块保留需求和 Feature 引用并登记 source_missing blocker。Requirement 修订改变会使旧验收证据 stale。

Agent 需求输入为 {requirements: [{key,title,description,acceptance}]}，使用 manual Adapter 的 source sync --file 仓库相对路径。拆分计划为 {features: [完整 Feature]}，只能创建绑定该 confirmed Requirement 的初始 Feature，不能注入实现完成、Evidence 或交付事实。应用审查记录位于 .project/artifacts/<UUID>/review.json，保留完整提案、前后快照、Run/reviewer/note；该记录不代表功能验收通过。--dry-run 不写事实、审查记录或锁。

# 日常维护 CLI

本轮按用户确认的顺序合并 PR #2，再完善事实写入、验收包恢复与 CI Evidence 导入。以下新增命令属于当前源码变更，公开 v0.1.0 的旧 wheel 不包含这些命令。原 v0.1.0 的发布提交保持不变；新的维护合并提交为 b25b6bd36c39c6f9167bd254a14786bcd7704448，Ubuntu/macOS CI 已通过。

## Requirement / Feature 写入

`requirement create/update/confirm` 与 `feature create/update` 默认生成只读提案，输出完整 candidate、before、输入与事实摘要。新增输入只需业务字段，ID、revision、时间、初始状态由工具生成；不需要内部 Python API。

Requirement 新增字段：title、description、sources、acceptance，可选 blockers/extensions。新需求总是 draft。Feature 新增字段：title、domain、requirement_refs、acceptance，可选 priority/size/depends_on/blockers/verification/extensions。AC 形式与七模型一致；省略 verification 时按 AC 生成尚无 Evidence 的 Check。新 Feature 实现为 not_started、交付为空。初始空项目仍需已有指南中的最小事实引导；这些写入服务于有 active Run 的项目，不绕过 Run 前置条件。

```text
apm requirement create --file requirement-input.json --json > requirement-proposal.json
apm requirement create --apply requirement-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "已审阅新增需求"
apm requirement update REQ_ID --expected-revision N --file requirement-patch.json --json > requirement-proposal.json
apm requirement update REQ_ID --expected-revision N --apply requirement-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "已审阅修改"
apm requirement confirm REQ_ID --expected-revision N --json > confirm-proposal.json
apm requirement confirm REQ_ID --expected-revision N --apply confirm-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "明确确认需求及来源"
apm feature create --file feature-input.json --json > feature-proposal.json
apm feature create --apply feature-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "已审阅新增 Feature"
apm feature update FEAT_ID --expected-revision N --file feature-patch.json --json > feature-proposal.json
apm feature update FEAT_ID --expected-revision N --apply feature-proposal.json --run-id RUN_ID --reviewer REVIEWER --note "已审阅修改"
```

参数中的 ID/revision/reviewer 必须替换。CLI 的完整 JSON 输出可以直接作为 --apply 输入；普通 data/proposal 包装也可读取。应用须重新核对事实快照、提案摘要、命令的目标/revision，重算候选并完整校验；锁内同时写事实与不可变审阅记录。任何事实变化使提案过期，须重新预览；`--dry-run` 的应用只检查不写入。

需求内容或来源变化撤销旧 confirmation，confirmed 变为 changed。确认必须显式执行 confirm，有当前 primary 来源且没有 blocker；Markdown 原文、版本或其他 primary 来源冲突须先经来源同步/人工解决，CLI 不自动裁决。

Feature update 支持 title/priority/size/depends_on/blockers/acceptance/verification/implementation/extensions；domain 和 requirement_refs 保持不变。implementation 只接受 state、declared/observed evidence_level、components、completed、remaining，subject 由工具计算；不能注入 verified 声明、Evidence 或交付。修改 AC 递增 acceptance_revision；Check 修改保留已有 evidence_refs/activity，不能删除旧 Check。已有 Evidence/交付引用始终保留，规则根据新版本判断它们是否过期。审阅 JSON 不表示 Check PASS。

例如实现进度输入：

```json
{"implementation":{"state":"in_progress","completed":["已实现命令接口"],"remaining":["执行配置 Check"]}}
```

状态由规则推导，输入不能写 lifecycle、verification.state 或 delivery.state。新 Feature 应用时同时加入创建它的 Run.feature_refs 并递增 Run revision，既有 Claim 不变；Feature 更新要求该 Feature 属于指定 active Run。创建和 Requirement 维护要求实际 active Run，并遵守用户授权与协作范围。

## 验收包检查与安全恢复

`apm snapshot` 不要求当前目录有 `.project`。只接受已知 V1 验收包格式和从可信交付记录取得的完整 SHA-256；摘要不是工具身份认证。

```text
apm snapshot inspect acceptance.zip --sha256 TRUSTED_SHA256 --json
apm snapshot restore acceptance.zip --sha256 TRUSTED_SHA256 --destination NEW_DIRECTORY --dry-run --json
apm snapshot restore acceptance.zip --sha256 TRUSTED_SHA256 --destination NEW_DIRECTORY --json
```

inspect 校验整个 ZIP、清单版本、文件摘要、模式、路径和资源限制，不解压或运行脚本。restore 在临时目录恢复文件，使用内置 Git 操作恢复 bundle 基线，重新核对 subject、事实结构和 Claim 冲突，成功后安装到新目录。已有目录、软链接、重复路径、越界路径、未知文件范围、特殊文件、错误摘要和非法模型均拒绝；失败清理本次临时目录，保留已有内容。新目录的父目录须存在。

工具不执行归档中的 bootstrap.py，不安装依赖、运行归档内程序或恢复远程/凭据配置。若继续开发，在恢复目录明确配置 Git origin 并按源码说明安装依赖。输出区分“归档检查通过”和“恢复后的派生状态”，包含完整 subject、目标 Feature 与验收汇总；doctor 或恢复成功不表示所有历史 AC 在其他提交有效。

本轮实际用新 CLI 恢复上一轮维护验收包，得到原提交 6bd0ea89c1b7e109f34c52b8746714fa7bc776d8、3 verified、10 条有效 AC、0 active Run。该包的其余十四个 Feature 对这个提交保留过期的历史证据。

## 显式 GitHub Actions Evidence 导入

本轮支持 GitHub Actions，使用现有 `gh` 认证进行只读 API/产物下载，不读出或保存密钥。项目必须有 GitHub origin、干净的完整 commit subject、匹配的 Feature subject 和 active Run。

```text
apm verify FEAT_ID --ci-run ACTIONS_RUN_ID --ci-artifact apm-junit-ubuntu-latest --check CHECK_ID --run-id RUN_ID --expected-revision N --reviewer REVIEWER --note "已审阅提交和命名断言" --json
apm verify FEAT_ID --ci-run ACTIONS_RUN_ID --ci-artifact apm-junit-ubuntu-latest --check CHECK_ID --run-id RUN_ID --expected-revision N --reviewer REVIEWER --note "明确导入该 Check 的 CI 结果" --apply-ci --json
```

`--ci-run` 也可为同一仓库的完整 Actions run URL。必须显式选择产物与 Check；多个 Check 可重复提供 --check。默认只预览，返回 would_record 和 ci_preview_checks，不创建 Evidence；与 verify --dry-run 一样退出 5，不能当作当前验收 PASS。--apply-ci 才写入；若仅部分 required Check 完成，仍退出 5 并保留真实新 Evidence。--dry-run 与 --apply-ci 同时使用也不写入。

导入要求原仓库的成功、已完成运行和准确的 head_sha。产物必须未过期，原生 API 摘要须与下载的 ZIP 完全一致，ZIP 只能含 ci-tests.xml 和 ci-context.json。context v1 绑定 repository、run_id/run_attempt、实际源码 subject、report/report_sha256，以及实际 command={argv,cwd,exit_code}。Check 对应的 Project.commands 必须与这个实际命令精确一致，且配置 JUnit result 与命名 testcase_refs；不能把执行全部测试的命令伪装成另一个本地子集命令。

仓库 CI 现在保存上述两文件的 `apm-junit-ubuntu-latest` / `apm-junit-macos-latest` 产物，保留 14 天。实际命令是 `uv run --frozen pytest --junitxml=.project/artifacts/ci-tests.xml`、cwd 为 `.`。Project 可为该命令配置独立 command_ref，再让目标 Check 引用它。CI 在 pytest 真实返回 0 后才生成 context；导入另解析选中的命名断言，缺失、重复、跳过、失败、零测试或与当前版本不符都拒绝。PR 默认测试合并预览提交；若它与当前 Feature 的准确 subject 不同，则不能导入，应选择对应 push 运行。

证据以 ci_result 保存实际远程命令、原始 ZIP、XML、context 与带 reviewer/note 的出处审阅，并绑定当前 acceptance_revision、Requirement revisions 和 Check digest。收集期间事实、修订号或代码变化会拒绝应用；通过同一事务写事实和不可变副本。导入不改变 Requirement 确认、实现完成或交付状态，不自动合并、发布或部署。

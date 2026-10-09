# 验收产物保存约定

## 已发布版本的完整快照

2026-10-09 v0.1.0 已发布。完整发布快照为 `.project/artifacts/relay/v0.1.0-published-acceptance.zip`，SHA-256 `ca0373e83ff66dd17fd086468900beb8d15e6d54a7769938bcbd7995bc9bc0ec`。它包含 eec67f2a246c94192e7bf35f1be611e76881fa23 的 Git bundle、重新生成的 46 条验收证据和 14 个 Feature 的 merged/released 记录；不公开上传。摘要与全新目录恢复步骤见 [发布指南](../../docs/release-v0.1.0.md)。早期独立审计归档与该可恢复发布快照用途不同；下文保留早期材料的保存边界。

## 历史材料

Git 显式保存 Evidence 引用的命令记录、测试日志/JUnit、独立审阅摘要与历史验收清单。artifacts 默认被忽略，不可变产物使用 .gitattributes 禁止行尾转换，保留摘要；新增文件须审阅后显式选择；不能用 git add -f 整个目录。

原始 Agent 会话、回传 ZIP、Git bundle、完整接力快照和临时 Eval 项目存入独立私有归档 agent-project-manager-v1-private-records.zip。SHA-256、文件大小及逐文件路径/摘要见 retention-manifest.json。归档当前保存在用户工作区，尚未上传其他存储；环境销毁前应另行下载保存。既有 phase6-complete.zip 也保留，不能假定链接或云工作区是永久存储。

原始 observation.json 含主机路径，亦保留在私有归档；历史 Handoff.context_refs 仍指向其原路径。四个历史 manual_review artifact 路径对应原始 ZIP/native 会话副本，未进入 Git。Evidence 的 path/SHA/subject 不改写，也不以占位文件替代；只从 Git checkout 时 missing_artifact 是准确状态。审阅报告仍可定位原始归档及相应记录。

如需恢复：先校验归档 SHA-256 和每项文件 SHA；只恢复清单中 storage=private_archive 的 .project/artifacts 文件到对应路径，遇到已有不同字节文件停止。不要覆盖当前事实、恢复日志或锁。私有 ZIP 里的历史事实/transactions 只作审计，不自动覆盖当前项目。

Phase 6 的 46/46 和 264 项 pytest 对应清单中的历史 working_tree subject。Git 提交或文档变动后，必须重新保存实际 subject 并执行 Check；旧 Evidence 保留但可能 stale。doctor 通过只表示模型、引用与恢复状态有效，不表示新 checkout 已通过 required AC。CI 执行 pytest、两个 doctor 和 wheel 构建；macOS 与 GitHub CI 结果单独记录。

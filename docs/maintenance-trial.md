# 发布后维护的真实使用验证

2026-10-09 按用户确认的顺序，先更新发布/恢复文档并实现手动发布工作流，再以这些结果评估 APM 的日常使用。实际执行工具为 Codex；本轮没有新的 DeepSeek 执行，也没有发布新版本。

## 真实输入与工作链

本轮登记一个来自用户明确指令的 confirmed Requirement，拆为三个可独立验收的 Feature，而将测试、构建、查询等技术工作写入 Run。

| 对象 | ID / 范围 |
| --- | --- |
| Source | SRC-d3af91a3-0252-4e28-8438-433e0baac73f；用户确认的三步维护顺序 |
| Requirement | REQ-026652db-7d1a-406a-b92f-09686223c0c5 |
| 发布/恢复文档 | FEAT-4950322b-03b9-41fc-b45e-c0d34422e45f；3 条 required AC |
| 手动发布流程 | FEAT-25002e5a-7ab3-4165-a5fc-3501b5ef9621；4 条 required AC |
| 使用评估 | FEAT-9359c3c1-5ec7-49ca-a6cf-085483d75c3a；3 条 required AC |
| 第 1/2 步 Run | RUN-fee5f496-dee0-4b00-928a-1aebfaa87e02 |
| 阶段 Handoff | HANDOFF-181a9fd1-3e7e-429c-bf0e-d7ca6de54ff9 |
| 使用评估 Run | RUN-2a428d16-f44e-4e35-88d5-77168fff3ba4 |

第一个 Run 写入已完成、剩余和阻塞事项，创建同内容的 Handoff 后结束，实际 active Claim 归零。随后查询 doctor/status、三个 Feature show 和第一个 Run show，读取持久化的目标、AC、证据位置与待办，再启动使用评估 Run。这是同一 Codex 会话中两个实际工作阶段的文件恢复验证，不是新 Agent 的隔离测评或跨工具接力。

查询时看到 17 个真实 Feature、56 条 required AC，其中本轮范围为 3 个/10 条。当时新维护 Feature 尚无正式 Check Evidence，前两个状态为 verifying，第三个为 ready；历史十四个 Feature 的证据因源码变化而过期。总览显示 0/56，并没有把已有代码、成功 CI、结束 Run 或旧版本 PASS 当成当前验收通过。后续固定源码 subject 后执行本轮配置 Check 和人工复核，最终状态、Evidence、Handoff、审阅 PR 与源码 SHA 保存到私有 `maintenance-acceptance.json`。本轮验收范围是 10 条，不声明当前源码通过历史全部 56 条。

## 实际运行结果

- 逐字执行 [v0.1.0 恢复文档](release-v0.1.0.md) 的 bash 代码块：先校验私有 ZIP 摘要，再在新目录恢复。实际得到发布提交 eec67f2a246c94192e7bf35f1be611e76881fa23、14 个 released、46/46 required AC、0 active Run。该历史验收包保持原样。
- 首个维护提交 aac19128350ea3bb9770d2b5cd7e8cb295c82cd1 在本地通过 294 项测试，包括 28 项发布控制测试；[Ubuntu/macOS CI](https://github.com/zz-commits/agent-project-manager/actions/runs/37878095985) 两项 job 都通过。
- [真实手动演练](https://github.com/zz-commits/agent-project-manager/actions/runs/37878305914) 使用 `workflow_dispatch`、`dry_run=true`，验证 job 通过，publish job 为 skipped。候选报告记录 294 passed、0 failed/errors/skipped、wheel 独立安装/初始化/诊断及 sdist 重建通过。这里的 skipped 是未请求执行的发布 job，不是跳过测试。
- 实际下载候选 artifact 并检查计划：`mode=read_only_preview`、`published=false`、`publish_eligible=false`。三个 blocker 分别为目标不等于 main、已有标签指向其他提交、已有公开版本不能替换；这与用维护分支和已发布 v0.1.0 做演练的输入一致。
- 演练后重新读取远程 main/tag、公开 Release 和三个资产 SHA-256：仍是原发布提交与原始字节。28 项隔离测试验证实际发布函数的拒绝、草稿续传、下载不一致时保持草稿等行为；新的工作流 publish job 的真实远程写入效果留待后续获授权的新版本发布观察。

六个文件查询进程合计 9.795 秒，输出和逐命令时长保存在恢复回执。这只测量命令进程用时，不能表示 Agent 阅读、思考或任务总时长。没有对照任务、完整 token/计费数据或新增第二种工具测量；相关指标为 null，不计算效率提升。

## 使用问题与下一阶段建议

| 实际观察 | 使用影响 | 建议与验收方向 |
| --- | --- | --- |
| 创建 Requirement/Feature、修改 implementation 和多 Feature Run 范围需要锁、revision、完整候选校验及事务脚本 | 常规维护仍需了解内部 Python API，操作成本集中在录入与更新，而非查询 | P1：补齐受保护的 Requirement/Feature 写入 CLI；显式 reviewer、预览差异、旧 revision 拒绝、原子写入、保留 Evidence/交付引用 |
| 首次登记时把 Source 的说明 Markdown 放入事实事务，被拒绝；改为先保存说明文件、事务只写支持的事实后成功，拒绝未留下部分事实 | “来源文档”和“事实文件”的写入边界不够直观 | 纳入上述 P1：CLI 区分来源输入与事实输出，并给出可操作错误；不扩大事务可写路径来绕过边界 |
| 新提交会使历史 Evidence stale；干净 Git checkout 与恢复后的私有事实状态不同 | 查看总览时容易把版本历史与本轮待验收范围混在一起 | P1：提供验收包检查/安全恢复入口与 subject、版本、范围摘要；本轮先用明确文档和私有回执解决 |
| 实际 CI 与候选 artifact 可下载，但转成版本绑定的 Check Evidence 仍需人工整理；查询本身不会执行测试或认证 CI | 正确保留未验证状态，但验收步骤重复 | P2：设计显式 CI Evidence 导入，绑定完整 SHA、Check、原始结果与 artifact 摘要；失败、过期或仅成功链接不得自动 PASS |

优先完成 Requirement/Feature 写入 CLI，再做验收恢复入口，然后评估 CI Evidence 导入。新功能仍按独立 Feature、明确 AC 和实际验证推进。当前观察不足以支持先扩展 Web 控制台、更多来源格式或 Agent 调度平台。

## 保留与复核

真实原始记录位于 `.project/artifacts/maintenance-20261009`：`context.json`、`documented-restore-receipt.json`、`manual-preview-{run,jobs}.json`、候选 `release-validation.json`、`public-release-after-preview.json`、`file-recovery-*.json` 与 `file-recovery-receipt.json`。最终验收另保存新提交的测试、工作流和逐 Check 复核；早期执行继续绑定原始提交，不能改写或迁移为最终提交 PASS。

正式源码和本轮需求/Feature 定义供 PR 审阅；最终 subject 对应的运行事实与 Evidence 保存在私有维护验收包中，避免再次提交证据改变它所验收的 HEAD。维护 ZIP、真实 Agent 原始会话、v0.1.0 私有验收包不上传公开 Release。

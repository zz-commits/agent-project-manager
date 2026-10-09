# v0.1.0 发布与正式验收恢复

2026-10-09 用户授权合并和发布，[PR #1](https://github.com/zz-commits/agent-project-manager/pull/1) 已合并，[v0.1.0 GitHub Release](https://github.com/zz-commits/agent-project-manager/releases/tag/v0.1.0) 已公开发布。标签指向实际合并提交 `eec67f2a246c94192e7bf35f1be611e76881fa23`。未部署或发布到 PyPI。

## 发布内容和实际验证

V1 提供七模型校验、状态查询、Run/Claim/Handoff、事务恢复、命名断言验证及 Evidence 导入、Git/人工交付关联、Markdown/Agent 来源提案、正式 Skill、CLI Eval 与可恢复快照。需要 Python 3.12+。

针对实际合并提交重新执行了 266 项 pytest、44 个配置 Check 和 2 个对原始真实接力材料的独立审阅，46/46 required AC 有效；[Ubuntu/macOS CI](https://github.com/zz-commits/agent-project-manager/actions/runs/37875041272)、wheel 独立安装/初始化/诊断及 sdist 重建通过。两个手工 Check 审阅历史 Codex → DeepSeek 执行，不声明 DeepSeek 在发布提交重跑。

Release 包含以下三个资产，均在上传后下载核验；自动生成的 GitHub 源码归档另由 GitHub 提供。

| 文件 | SHA-256 |
| --- | --- |
| agent_project_manager-0.1.0-py3-none-any.whl | 5a5305b8031f79800f4a25bb681ffde87bd14b855cae1dcc3c0c790e955102d5 |
| agent_project_manager-0.1.0.tar.gz | 6171ca1cb78009792654ad33e2c18d96c5122f5dc23e334a72a76095d49a05ba |
| SHA256SUMS | 169cc1a4cfedb182055c62d75fa9f0240a471b62cba0ee1ddd37503e2b5e128d |

安装 wheel 后运行 `apm --version`，结果应为 `0.1.0`。Skill/Eval、文档和隔离示例可从源码包或仓库读取。公开包不包含根运行事实、原始 Agent 会话和私有验收包。

## 为什么 Git checkout 与正式验收包的状态不同

Git 中保留历史事实和经选择的历史产物。精确 subject 包含 HEAD；将当前验收事实再次提交，会改变其绑定的版本。因此发布提交的新验收与真实 merged/released 记录保存在独立私有快照中，而不追加到发布提交。只检出 Git 时出现 stale/missing_artifact 是准确结果，doctor 通过也不代表当前全部 AC 通过。

发布快照 `v0.1.0-published-acceptance.zip` 共 16460498 字节，SHA-256 为 `ca0373e83ff66dd17fd086468900beb8d15e6d54a7769938bcbd7995bc9bc0ec`。它包含同一 HEAD 的 Git bundle、最终事实及不可变产物，已在新目录实际恢复：14 个 Feature 的 delivery 为 released、46/46 required AC、0 活跃 Claim。发布与恢复回执分别位于包内 `.project/artifacts/release-v0.1.0/release-acceptance.json` 和原工作区 `.project/artifacts/relay/v0.1.0-restoration-receipt.json`；后者生成在快照导出之后，不递归放入该 ZIP。

这是私有备份，不在公开 Release 中；请从原任务工作区下载并独立保存。工作区链接不是永久保存保证。不要用更早的 Phase 6 或 PR 验收包代替本发布包。

## 在全新目录恢复

取得可信发布快照后先核对摘要，再在新目录解压。以下命令从下载 ZIP 所在目录执行；`mkdir` 遇到已有目录会停止。不要覆盖现有 checkout、事实、锁或事务日志。

```bash
set -e
python -c "from pathlib import Path; import hashlib; p=Path('v0.1.0-published-acceptance.zip'); assert hashlib.sha256(p.read_bytes()).hexdigest() == 'ca0373e83ff66dd17fd086468900beb8d15e6d54a7769938bcbd7995bc9bc0ec'"
mkdir v0.1.0-acceptance
python -m zipfile -e v0.1.0-published-acceptance.zip v0.1.0-acceptance
cd v0.1.0-acceptance
uv sync --frozen
uv run --frozen python .project/artifacts/relay/bootstrap.py
git rev-parse HEAD
uv run --frozen apm doctor --json
uv run --frozen apm status --json
```

bootstrap 校验逐文件摘要、Git bundle、文件模式和实际 subject，仅在新解压目录恢复基线。预期 HEAD/subject 为上述完整合并 SHA；status 的 required_ac/passed_ac 均为 46，active_runs 为 0，14 个 Feature 为 delivered/released。有未完成事务先诊断并按 `doctor --recover` 恢复，不删除日志。修改代码后旧证据会失效，须重新验证；不要把快照状态迁移到其他提交。

## 后续发布

v0.1.0 曾使用一次临时 GitHub Actions 上传任务解决云端上传接口认证问题，临时分支已清理。后续的手动发布与演练规则见 [可重复发布流程](release-workflow.md)。该流程不扩大 `apm` CLI 的自动交付权限，也不自动改写 `.project` 的验收状态。

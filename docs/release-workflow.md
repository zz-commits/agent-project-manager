# 手动发布与默认演练

仓库的 `Validate and manually release` 工作流用于验证候选包与发布到 GitHub Releases。`apm` 的事实和交付 CLI 保持既有边界，工作流不自动确认 Requirement、创建 PASS Evidence、回写 `.project` 或部署。

## 操作方式

工作流合并到默认分支后，在 GitHub Actions 选择 `Validate and manually release` → Run workflow。输入：

- `tag`：稳定版 `vMAJOR.MINOR.PATCH`，必须与 pyproject.toml 的 version 一致；为空时从版本推导。
- `target_sha`：完整 40 位提交 SHA；为空时使用所选工作流 ref 的提交。正式发布要求它等于当时远程 main。
- `dry_run`：默认为 true，测试、构建、独立安装和保存候选 artifact，完全不修改标签或 Release。只有手动显式选择 false 才进入写入 job。

```bash
gh workflow run release.yml --ref main -f tag=v0.1.1 -f target_sha=实际完整提交SHA -F dry_run=true
```

示例参数须替换为实际版本与 SHA。下一版本应先在独立变更中更新 pyproject.toml 和 src/apm/__init__.py，通过审阅与 main CI，再演练。v0.1.0 已公开发布，流程会拒绝用新字节覆盖它；本轮维护没有发布新版本。默认分支入口在合并后使用。本轮已通过 CLI 在维护分支完成真实手动演练，记录见维护使用报告；临时的维护分支 push 触发器已移除，长期保留手动入口和 PR 只读验证。

## 验证与发布顺序

验证 job 只有 contents:read 权限。它检出指定提交，使用 Python 3.12/uv 0.12.19 和冻结锁文件，运行全部 pytest、真实项目/设计示例 doctor、wheel/sdist 构建，再从 wheel 在独立环境初始化和诊断项目，并从 sdist 重建 wheel。零测试、失败、错误或跳过阻止发布。候选文件仅包含两个公开包、SHA256SUMS 与 release-validation.json；保留 14 天，请及时下载。新提交、版本或字节变化都须重新生成候选。

演练成功表示上述程序检查通过。计划会单独显示 publish_eligible 与 publish_blockers：例如目标还不是 main、公开版本已存在，均可在只读演练中发现；它们不被改写成“可发布”。请求实际发布时，任何 blocker 都使验证 job 失败。

发布 job 仅接受本次运行产生的候选，并再次核对真实源码 subject、版本、资产摘要和远程 main/tag/Release。它具有 contents:write 权限，使用 GitHub Actions 的仓库令牌，不需要把密钥交给 Agent 或写入文件。

1. 对不存在的版本创建指向完整 SHA 的草稿；同一版本和提交的草稿可续传。
2. 已公开版本、其他提交的草稿、指向其他提交的标签或不一致资产一律拒绝；不删除、覆盖资产或移动标签。
3. 先下载并验证既有资产，只上传缺失文件。全部三个资产再下载核对后，才把草稿公开。
4. 重新读取发布状态和实际标签，保存 publication-receipt.json。上传失败保留草稿；修复后以同一版本与提交重新手动运行。

整条工作流串行执行发布候选任务，减少同版本操作冲突；远程状态仍会在公开前重新检查。PR 事件只能运行演练，不进入发布 job。

## 证据与权限边界

pytest/doctor/安装日志和 Actions 结果证明本次程序行为；doctor 不是全部 Feature 已验收的证明。版本绑定的 `.project` Check、原始材料独立复核和真实交付登记仍由项目工作闭环完成，不能把 CI 成功或脚本角色当作另一个真实 Agent，也不能将旧 subject 的 PASS 迁移到发布提交。

本轮真实演练与使用观察见 [维护使用报告](maintenance-trial.md)。实际公开发布路径的远程效果须在后续获授权的新版本发布时观察；隔离测试覆盖拒绝条件、草稿续传和下载失败，测试 fixture 不是真实发布记录。

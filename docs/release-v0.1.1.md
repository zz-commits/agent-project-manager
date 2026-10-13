# v0.1.1 发布准备

本页描述 v0.1.1 候选。公开版本仍为 v0.1.0；发布事实以 GitHub Release、准确标签提交和下载产物为准，版本号变更或发布预演不表示已发布。

## 版本内容

- Requirement/Feature 新增与更新默认生成只读提案；应用须 active Run、reviewer/note、正确 revision 和事实快照。需求内容变化撤销旧确认，确认须显式执行。
- `snapshot inspect/restore` 以可信完整 SHA-256 检查验收包。恢复只写新目录，拒绝不安全路径、文件模式和资源超限，不执行包内脚本。
- `verify --ci-run` 显式选择 GitHub Actions 运行、产物和 Check。默认预览，`--apply-ci` 才记录；原生仓库、提交、摘要、实际命令和 JUnit 命名断言必须匹配。
- 手动发布流程默认只读预演，验证冻结依赖、测试、包、独立安装与源码包重建；正式发布要求当前 main，并拒绝覆盖公开版本或不同提交的标签。

Python 3.12+、七模型 V1、CLI JSON 协议版本与运行时依赖范围保持兼容。初始空项目仍需最小事实引导后建立 Run。CI 导入支持约定的 GitHub Actions 产物，准确 commit 和配置命令必须一致；PR 合并预览的 subject 不能迁移。来源远程 Adapter 尚未实现。

## 安装候选

在独立 Python 3.12+ 环境中，先核对候选包与 SHA256SUMS，再安装：

```bash
python -m pip install ./agent_project_manager-0.1.1-py3-none-any.whl
apm --version
apm project init --name demo --project ./demo
apm --project ./demo doctor --json
```

版本应为 `0.1.1`。新增命令输入与安全规则见 [日常维护 CLI](usability-cli.md)。开发验证用 `uv sync --frozen`，不从源码 checkout 的导入成功推断 wheel 安装成功。

## 发布预演与正式发布

通过 `.github/workflows/release.yml` 的 `workflow_dispatch` 显式选择版本分支和完整 `target_sha`，`tag=v0.1.1`、`dry_run=true`。预演运行实际测试、检查结构、构建 wheel/源码包，独立安装 wheel 并重建源码包，保存 `release-candidate` 产物和 `release-validation.json`。

版本 PR 尚未合并时，`publish_eligible=false` 且理由为目标不是当前 main，这是发布门槛。预演成功只验证所选提交的候选，合并后须针对新的准确提交重新运行 CI、验收与预演。

正式发布使用当前 main 的完整 SHA，显式 `dry_run=false`；流程检查既有标签/Release，创建或恢复匹配草稿、上传三份资产，再下载比对后公开。发布后核对标签、Release 和下载摘要，进行真实独立安装回归。候选构建与正式构建的摘要分别记录，不假设不同构建的字节相同。

原始 Agent 会话、根 `.project` 完整事实和私有验收包不进入公开 wheel/源码包。验收按准确 subject 保存；旧记录不因新版本号自动通过，也不表示部署。历史 v0.1.0 的发布与恢复见 [原发布记录](release-v0.1.0.md)。

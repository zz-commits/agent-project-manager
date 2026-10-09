# 可运行命令

项目根目录：已安装 apm 可直接调用；本仓库用 `uv run --frozen apm`。下列 ID/N/PATH 均须替换为真实值，不执行占位符。

```text
apm doctor --json
apm status --json
apm feature list --json
apm feature show FEATURE_ID --json
apm run start FEATURE_ID --agent TOOL --instance INSTANCE --scope path:src/
apm run show RUN_ID --json
apm run show current --instance INSTANCE --json
apm run update RUN_ID --expected-revision N --file update.json
apm verify FEATURE_ID
apm verify FEATURE_ID --run --run-id RUN_ID --expected-revision N
apm verify FEATURE_ID --record evidence.json --run-id RUN_ID --expected-revision N
apm feature link-commit FEATURE_ID SHA --run-id RUN_ID --expected-revision N
apm feature link-mr FEATURE_ID --file mr.json --run-id RUN_ID --expected-revision N
apm run finish RUN_ID --expected-revision N --handoff-file handoff.json
apm run abort RUN_ID --expected-revision N --reason REASON --handoff-file handoff.json
apm rebuild
```

Scope 支持 feature:ID、component:NAME、path:仓库相对路径。Claim 是协作事实，不是权限或跨机器分布式锁。override-conflict 必须有理由，只适用于已授权的协作冲突处理，不能绕过 revision、Schema 或事务约束。

--project PATH 可显式定位；--json 在 stdout 返回完整外壳。退出 0 表示操作成功，verify 还要求全部 required 通过；1 IO/运行错误，2 参数/Schema/引用错误，3 并发/修订/提案冲突，4 不存在，5 前置条件阻塞或验证未通过。不要把 status 的退出 0 当作功能完成。

Check 引用 Project.commands 的 argv/cwd、timeout_seconds 和 JUnit result.path。testcase_refs 为完整 classname.name，含参数后缀；零测试、跳过、缺失、重复、旧报告、超时均不能 PASS。成功写入递增 Feature revision，使用返回或最新 show 的值。

来源操作：

```text
apm source list --json
apm source show SOURCE_ID --json
apm source add --file source.json --expected-digest DIGEST --run-id RUN_ID
apm source sync SOURCE_ID --json
apm source sync SOURCE_ID --file agent-input.json --json
apm source sync SOURCE_ID --apply proposal.json --run-id RUN_ID --reviewer NAME --note NOTE
apm requirement list --json
apm requirement show REQUIREMENT_ID --json
apm requirement decompose REQUIREMENT_ID --file plan.json --json
apm requirement decompose REQUIREMENT_ID --apply proposal.json --run-id RUN_ID --reviewer NAME --note NOTE
```

source add 的 expected-digest 来自 source list 的 Registry 原始 SHA-256。Markdown adapter 只提取 apm-requirement 块（key/title/description/acceptance）；manual adapter 输入为 {requirements: [...] }。拆分为 {features: [完整初始 Feature]}，只创建未实现/未验证的 Feature。提案 JSON 完整响应可直接供 --apply 使用。输入文件必须是仓库相对路径；产物 review.json 属于审查出处，不是 PASS。

未实现的 next、project config、requirement create/update、feature create/update 不能当作可执行命令。详情以项目 README 和 docs/cli-protocol.md 为准。

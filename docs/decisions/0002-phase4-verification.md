# Phase 4：验证执行与交付关联

2026-10-08，用户要求继续既定计划。Phase 1–3 已完成；本轮范围为 Check 执行、Evidence 导入、只读 verify、本地 Git 提交引用及有出处的人工 MR 记录。需求 Adapter、远程 MR API、提交/推送/部署不属于本轮。

## 执行与验收

Project.commands 可增加 timeout_seconds（默认 60，最多 3600）和 result={kind: junit, path: 仓库相对路径}。Check.testcase_refs 指定完整 JUnit classname.name；参数化用例名称包括参数后缀。声明的每个用例必须在本次报告中唯一出现且实际通过；零测试、缺失、重复、跳过、报告过旧或格式错误不产生 PASS。进程非零退出或命名断言失败显示 failed，超时或环境缺失显示 not_verified。同一次 verify 中共用 command_ref 的 Check 只执行一次。

verify 默认只读，不执行命令。--run/--record 都必须指定 active Run、Feature 当前 revision；Run 必须包含目标 Feature。--check 可选择子集，但退出 0 仍要求整个 Feature 的 required 验证有效通过。Check/命令定义摘要包含 testcase_refs（存在时）；不能把退出 0 泛化为全部 AC 通过。

执行前要求 Feature.subject 等于当前代码。进程在锁外运行，结束后锁内重新校验 Feature/Project/Requirement/Run 快照；并发事实变化返回冲突，不覆盖。执行中代码变化保留 not_verified 结果。timeout 终止本次启动的进程组。日志截取最多 1 MiB，按敏感变量绑定值脱敏；报告保存独立副本，后续覆盖原报告不会改变历史证据。

新 Evidence、不可变产物与 Feature 引用通过同一事务保存。每次执行的记录替代该 Check 已关联的旧证据，不会因新结果失败/失效恢复旧 PASS。dry-run 不启动命令或创建任何文件。--at 仅用于只读评估，不伪造执行时间。

## 导入

--record 接受完整 Evidence 对象或非空列表；produced_by.run_ref 必须等于指定 active Run，Feature/Check 必须匹配。不改写声明的历史版本与 subject。ID 不得重复；supersedes 显式指定，不能静默裁决冲突。人工 passed 必须有 reviewer、本地可检查产物并符合 Project 策略。导入的 passed test/ci_result 须按对应命名 JUnit 断言核实；截图/API 响应/代码引用只作为观察材料，必须使用显式 manual_review 才可人工满足 Check，不能绕过人工策略；本地文件保存不可变副本并记录摘要。远程产物不下载、不视为已核实。

## Git 与人工交付

link-commit 只运行只读 Git 命令解析并观察本地对象，记录完整 SHA 与 tree。自动观察通过 Evidence.delivery_observation={kind: git_commit, commit, tree} 表达，无需伪造人工 reviewer。状态评估时重新核实 Git 对象。该记录只表示 committed，且必须覆盖当前 subject 才进入当前交付汇总。

link-mr 接受 {record, evidence}，其中 record.kind=mr，evidence 为完整 delivery Evidence 列表。人工证据要求 reviewer、note 和可检查本地产物，并绑定 delivery_ref/delivery_state；不把旧提交证据用于另一条合并记录。不查询远程 API、不声称完成实际合并。已有验证失败、过期或未覆盖当前代码时，合并事实仍保留，但生命周期不得显示 delivered。

本轮不修改 Requirement 确认状态；代码存在、Run 结束、测试退出码或 Commit 都不能单独证明交付。跨平台 CI 和外部 Agent 试点仍需要实际运行。

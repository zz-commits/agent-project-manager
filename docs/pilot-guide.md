# Codex → 本地 DeepSeek Harness 接力

目标 Feature：`FEAT-6cee9a20-f311-448c-8376-5ae57346db15`。本指南保留实际接力时使用的任务和命令，该次回传已由 Codex 独立审阅，结果见试点报告及 .project/artifacts/phase6-relay-acceptance.json。重复试点须用新的目录、Run、实例与输出路径，并确认当前 Feature 状态。无需开放本地服务或在聊天中提供密钥。

## 本地准备

下载 `.project/artifacts/relay/codex-to-deepseek.zip`，解压到一个新目录，终端进入解压后的项目根目录。需 Python 3.12+、Git、uv；可由 uv 使用本地已有 Python。不要覆盖自己的现有 checkout。交接包含未提交代码、项目事实、已保存的报告、Skill 及既有 HEAD 的 Git bundle；不携带云端 Git 配置、模型认证或虚拟环境。

```bash
uv sync --frozen
uv run --frozen python .project/artifacts/relay/bootstrap.py
uv run --frozen apm doctor --json
uv run --frozen apm feature show FEAT-6cee9a20-f311-448c-8376-5ae57346db15 --json
```

bootstrap 校验文件摘要并还原既有 Git HEAD/index，保留交接包的工作树，校验代码 subject 与云端相同。它只为新解压目录初始化 Git；现有 HEAD 不一致会停止，绝不 reset 现有 checkout。先 bootstrap 再判断旧 Evidence 是否有效。后续修改事实后不要重复运行旧 manifest 校验。

## 给 DeepSeek Harness 的任务

将下面的文本交给正在本地运行的 Harness，并允许它使用项目目录内的文件与终端工具：

> 请接手本仓库 Feature FEAT-6cee9a20-f311-448c-8376-5ae57346db15。先读 AGENTS.md、README.md、skills/agent-project-manager/SKILL.md 和本指南。读取 doctor/status、该 Feature、Requirement、最近 Codex Handoff 及当前有效 Evidence，仅凭文件恢复上下文。记录实际 Harness/模型版本、实例和原始会话 transcript；从提供任务到首次结构化回答计时，工具无 token 计数则填 null。
>
> 回答目标、required AC、生命周期/verification/delivery、已完成/剩余/阻塞、Claim、有效及失效 Evidence 和下一步，解释为什么当前不能宣称整个 Phase 6 通过。再以 agent=deepseek-harness、唯一 instance、scope=path:.project/ 建立自己的真实 Run。重新运行隔离 CLI Eval 到新的 .project/artifacts/eval-deepseek-1，保存实际命令和结果；它是合成程序验收，另行保存你自己的真实恢复回答和操作 transcript。不要复制 report.json 作为你的答案。只读评估根 Feature 的证据；真实接力的 required Check 仍待 Codex 回收审查，不自行伪造 PASS。
>
> 将恢复回答、实测时间/补问数/冲突数、tool/模型版本和 transcript 保存到 .project/artifacts/deepseek-observation/。把 Run.work 更新为实际完成与剩余工作；剩余至少保留“回传 Codex 独立审阅真实接力证据”。生成与最终 Run.work 三组数组完全一致的新 Handoff，然后 finish Run，确认 Claim 释放、doctor 通过。按本指南导出结果包交给用户回传。保持代码和需求内容不变；不提交、推送、合并或部署。

工具若不能自动保存 transcript，由用户导出真实会话并放在 `.project/artifacts/deepseek-observation/` 后再导出结果包；不能只用模型编造的对话代替。保留命令、退出码、回答、工具版本、起止时间和失败/冲突记录。过滤密钥后计算实际文件 SHA；审查者注明过滤方法。

实际命令参考（INSTANCE 与 RUN_ID/N 必须用实际值）：

```text
uv run --frozen apm run start FEAT-6cee9a20-f311-448c-8376-5ae57346db15 --agent deepseek-harness --instance INSTANCE --scope path:.project/
uv run --frozen python -m evals.run --output .project/artifacts/eval-deepseek-1
uv run --frozen apm verify FEAT-6cee9a20-f311-448c-8376-5ae57346db15 --json
uv run --frozen apm run update RUN_ID --expected-revision N --file .project/artifacts/deepseek-observation/update.json
uv run --frozen apm run finish RUN_ID --expected-revision N --handoff-file .project/artifacts/deepseek-observation/handoff.json
uv run --frozen apm doctor --json
```

只读 verify 返回 5 是当前未全部验收的预期结果，应保留，不改成 0。Run update/finish 修订号逐次读取返回值。Handoff 完整字段见 [参考](../skills/agent-project-manager/references/handoff.md)，新 ID 使用 UUIDv4。观测 JSON 至少包含 feature_id、Codex/DeepSeek Run、Codex/DeepSeek Handoff、actual_tool/version/model/instance、三个状态答案、有效 Evidence ID、remaining、测量方法、elapsed_ms/token_usage/clarifications/conflicts（不可得则 null）和 transcript 路径/SHA；这是审阅输入，不能当作已通过 Evidence。

## 回传与验收

所有 Run 终止后执行：

```bash
uv run --frozen python -m evals.relay --project . --feature FEAT-6cee9a20-f311-448c-8376-5ae57346db15 --output .project/artifacts/relay/deepseek-result.zip
```

回传 `deepseek-result.zip` 及导出命令的实际 SHA-256。`.project/artifacts/relay/` 为包本身的临时目录，不纳入新包，真实 transcript/观测必须保存在上面指定的另一目录。合成 Eval 内部的 .git 和缓存不会打包；重新执行 Eval 才创建可查询的本地场景。结果包含新的事实、Handoff、报告与真实会话。

Codex 收到后核对同一 Feature、代码 subject、两个不同实际工具的执行、Run/Handoff 数组、终态 Claim、有效 Evidence、恢复答案与实测数据，审查通过后才登记两个真实试点 Check 的 Evidence 并完成 Phase 6。无配对 baseline 时不声明 Skill 带来效率提升；无本地结果时保持未验证。通过阅文件或填写工具名无法自动认证提供者身份，真实 transcript 仍需审阅。

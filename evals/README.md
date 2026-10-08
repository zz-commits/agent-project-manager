# 协议 Eval 与实际 Agent 观察

在仓库根目录执行，Python 3.12+、Git、uv；沿用 `uv sync --frozen` 的依赖，无模型 SDK。

```bash
uv run --frozen python -m evals.run --output .project/artifacts/eval-local-1
```

OUTPUT 必须不存在。十二个隔离场景各执行一次，`--repetitions 3` 可重复三次。保存 `report.json`、`junit.xml`、`transcripts/` 和 `contexts/`。只会修改 OUTPUT 下的合成项目；合成 Git 提交不是根项目提交。命令退出 0 要求非零场景且全部通过，错误/零场景返回 1，参数/输出冲突返回 2。每条 transcript 保留真实 argv、退出码、CLI 毫秒耗时和脱敏输出。

场景覆盖 ready、无证据的 complete、有效 PASS、失败、改码后旧证据失效、commit 不等于交付、无验证的 merge、Claim/revision 冲突、接力、confirmed→changed 与中断事务恢复。脚本中的 protocol-harness 角色均属于测试数据，不算两个 Agent。JUnit 中的场景数不计入根项目 pytest 测试数。

## 实际观察和对照

使用 [恢复问题](prompts/recover.md) 给实际 Agent 同一套上下文。工具支持 Skill 时读取完整 `skills/agent-project-manager/`；否则直接读 SKILL.md 和需要的 references。要比较有/无 Skill，使用独立会话、相同输入快照和全部场景，保存是否提供 Skill；同一 instance_id 指实验配对标识，原始会话 ID 在 transcript 中记录。无 Skill 条件不提供 SKILL.md。真实试点操作见 [本地接力指南](../docs/pilot-guide.md)。

提交 JSON 格式（字段均必填；计量不可得则 null）：

```json
{
  "version": 1,
  "suite_id": "report.json 中的实际 suite_id",
  "suite_sha256": "report.json 原始字节的实际 SHA-256",
  "observations": [{
    "case_id": "ready", "repetition": 1, "condition": "with_skill",
    "agent": {"tool": "实际工具名", "version": "实际版本", "instance_id": "实验配对标识"},
    "answers": {"lifecycle": "ready", "verification": "not_started", "delivery": "none"},
    "transcript": {"path": "transcript.txt", "sha256": "实际 transcript SHA-256"},
    "reviewer": "实际审查者", "note": "会话来源与运行方法",
    "elapsed_ms": null, "token_usage": null, "clarifications": null
  }]
}
```

transcript 为提交文件目录下的真实非空文件；不要把模板、标准答案或脚本输出伪装成 Agent 回答。不要提交密钥或完整主机环境。token_usage 若可得为 `{ "input": 实测整数, "output": 实测整数 }`。elapsed_ms 测从提供上下文到返回答案的墙钟时间；clarifications 记录实际补问数。不要用 CLI 耗时替代恢复时间。

```bash
uv run --frozen python -m evals.score --suite .project/artifacts/eval-local-1/report.json --submission .project/artifacts/observations/submission.json --output .project/artifacts/observations/score.json
```

输出路径必须不存在。套件和 transcript 的摘要均需一致；拒绝重复/未知 case、空观察、缺失产物和无效数字。错误绑定返回 2；错答或不完整条件返回 5；完整覆盖且全部答案正确返回 0。单个 ready 正确不代表完整 Eval 通过。评分只比较结构化状态答案；解释、证据引用、真实身份与跨工具接力另由审查者检查。任何评分均为 `cross_agent_handoff: not_assessed`。

只有同一工具/版本/实验配对标识的完整 with_skill/without_skill 且答案正确、实测时间齐全才显示耗时对照；不从不完整数据推断收益。默认报告的 token、Agent 恢复耗时、补问数为 null，对照和真实跨工具执行为 not_run。

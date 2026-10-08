# development

运行 uv sync --frozen。Run 优先经 CLI；Feature/Requirement 手工维护后运行 doctor。

## 当前开发事实

Phase 1–6 实现及真实跨工具试点已验收。46/46 required AC 通过，14 个 Feature verified，无活跃 Claim；delivery 为 none。最终记录见 ../artifacts/phase6-relay-acceptance.json 与 ../handoffs/HANDOFF-54c1b513-15d5-4eb7-86f5-63bff109a64d.yaml。

DeepSeek 回传的原始观察与终态 Run/Handoff 保留不改。首次结构化回答经原始日志复核为 361143 ms；补问 0，Claim/revision 冲突 0。Token 依据 provider usage 分离非缓存输入/缓存读取/输出，费用与完整会话耗时未知；没有配对 baseline，不声明效率收益。

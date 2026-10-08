# V1 JSON Schema

v1/protocol.json 保存共享定义；project、registry、requirement、feature、run、evidence、handoff 七个入口 Schema 使用本地注册 urn 引用，无需联网获取 Schema。

proposal.json 校验 Phase 5 操作文档，不增加核心事实模型。source_record 校验专用 Markdown 块或 Agent 候选需求；提案完整性、输入新鲜度与状态保护由 sources.py 检查。

采用 Draft 2020-12，拒绝未知字段并支持 extensions。字段说明见 [yaml-schema.md](../docs/yaml-schema.md)，跨模型规则见 [V1 core 决定](../docs/decisions/0001-v1-core.md)。

引用、UUIDv4、domain、required AC/Check、依赖环、subject、Claim 和 Evidence/Run/Handoff 关系由核心校验器检查。版本不一致是新鲜度问题，保留记录并标记 stale。

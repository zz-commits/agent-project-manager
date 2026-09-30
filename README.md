# agent-project-manager

面向 Coding Agent 的项目生命周期协议与工具集：让需求、开发、验证、交付和交接可读取、可验证、可追溯。

**当前状态：设计草案与项目骨架，尚未开始编码。** 文档中的 `apm` 命令均为拟议协议，当前不可执行；未选择实现语言、发布渠道或安装方式。

## 文档入口

- [总体设计](docs/design.md)：目标、核心模型、Feature 粒度、状态推导、协作和版本边界。
- [YAML Schema 初稿](docs/yaml-schema.md)：七类模型的字段、约束和示例位置。
- [CLI 命令协议](docs/cli-protocol.md)：命令、输入输出、错误码和写入约定。
- [实施计划](docs/implementation-plan.md)：V1 阶段、优先级、验收条件与 V2/V3 演进。
- [Agent 工作约定](AGENTS.md)：本项目当前阶段及后续协作规则。
- [.project 示例](.project/README.md)：完整关联的虚构示例，不代表框架已实现。

## 目录

```text
agent-project-manager/
├── README.md
├── AGENTS.md
├── .gitignore
├── docs/
│   ├── design.md
│   ├── yaml-schema.md
│   ├── cli-protocol.md
│   └── implementation-plan.md
├── .project/
│   ├── project.yaml
│   ├── sources/registry.yaml
│   ├── requirements/
│   ├── features/example/
│   ├── runs/
│   ├── evidence/
│   ├── handoffs/
│   ├── decisions/
│   ├── refs/
│   ├── generated/
│   └── cache/
├── schemas/       # 未来机器可校验的 Schema
├── cli/           # 未来命令入口
└── src/           # 未来确定性核心逻辑
```

本目录是独立项目文件夹，远程仓库为 [zz-commits/agent-project-manager](https://github.com/zz-commits/agent-project-manager)。尚未自动注册为 Codex 侧栏中的独立项目。

## 设计来源

整理自 2026-09-30 的[“分析Skill架构”讨论](chatgpt-conversation://6abccdbd-49ec-83ea-8e93-27419284c391)。以后续目录、Schema、CLI 讨论为基线；本次补充的约束与待决项见设计文档。上层 `sources/` 为同步的只读参考，未修改。

下一步是评审并冻结协议，补齐真实 Feature 场景，再选择技术栈；本次不包含该阶段的代码实现。

# Phase 5：来源接入与显式提案

2026-10-08，用户要求开始下一阶段。范围为 Source 注册、Markdown 提取、Requirement 差异提案及显式应用、Agent 需求提案与 Feature 拆分计划导入。Phase 6、远程来源、自动提交/发布另行推进。

## 来源与 Markdown

source list/show 返回 Registry 原始字节 SHA-256，source add 需要 expected-digest 和 active Run。保留已有 Registry extensions；不覆盖已有 ID。来源仍只读，不展开链接、不执行代码。

Markdown Adapter 名为 markdown，限仓库内 UTF-8 本地文件，最多 2 MiB。用独立 fenced block `apm-requirement` 表达对象：key、title、description、acceptance（非空字符串数组）。key 为稳定 ASCII 标识；同一来源不可重复。普通 Markdown 和其他代码块不推测为需求；未闭合或非法的专用块报错。无专用块不得初始化需求，但已有来源块全部删除时生成缺失提案。Requirement.sources.locator 使用 block:<key>，ID 首次提案分配 UUIDv4，后续通过来源及 locator 匹配。原始文件 SHA-256 为来源 revision。

manual Adapter 的 Agent 需求输入为 {requirements: [上述对象]}，输入文件同样是仓库内可追溯快照。没有内置 LLM；Agent 不能在该输入中写确认状态、Evidence、实现进度或交付记录。

## 提案与应用

默认 source sync（含 Agent --file 输入）与 requirement decompose 只返回 proposal，不写锁、事实或缓存。proposal 是操作文档，不增加核心事实模型；其 Schema 随 wheel 打包。提案保留完整候选 records、差异和冲突，绑定完整 Project/Registry/Requirement/Feature 基础快照摘要和读取的来源/Agent 文件 SHA，应用前重新计算。proposal digest 绑定完整内容，修改提案须重新生成。应用须 --apply、active Run、reviewer 与 note；不会自动确认需求。

已有 confirmed 内容或来源版本变化后设 changed，清除旧 confirmation；draft 保持 draft。来源删除仅产生 changed 与 source_missing blocker，保留内容、ID 及 Feature 引用。其他 primary 来源不同意候选内容或无法核实，保留原内容并设 blocked，记录 source_conflict blocker，不按权威数字自动选择。重新生成时重新检查这些条件，不能靠手改 proposal 解除保护。需要确认仍人工维护事实后 doctor，不在本轮增加自动确认命令。

应用在锁内检查快照、Run、输入和完整候选。Requirement 修订递增，使旧 Evidence 自动 stale；不迁移 PASS，不修改 Feature 状态。Registry、需求和包含完整提案/前后快照及操作出处的审查产物，经同一可恢复事务写入。重复应用、过期输入、事实并发变化均拒绝。dry-run 不写入或执行项目命令。

## Agent 拆分计划

requirement decompose ID --file PLAN 读取 {features: [完整 Feature 文档]}；每个新 Feature 必须只绑定该 Requirement，revision/acceptance_revision=1，初始 not_started、declared、subject=null，无 Evidence/交付记录。验证结构、AC、依赖及引用，拒绝现存 ID。--apply 导入所审阅提案，仍检查基础快照和计划文件；需求须 confirmed，primary 已登记版本必须与确认快照一致，且其本地 Markdown 原始文件摘要可核实时必须匹配。CLI 不生成 Feature、代码或验收证据。该提案只能创建 Feature，不修改或删除已存在的 Feature。

默认输出的 data.proposal 可保存为独立 JSON；--apply 同时支持完整 source.sync / requirement.decompose JSON 响应，方便直接重定向。操作产物保存在 .project/artifacts/<UUID>/review.json，绝不能作为行为通过证据。

拆分前，还检查 primary Markdown 的定位块存在且内容与 confirmed Requirement 一致；仅手改版本摘要或确认状态不能绕过来源冲突。

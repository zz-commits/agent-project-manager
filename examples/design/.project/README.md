# .project 协议示例

这里是**虚构的设计样例**，Project.mode=example。样例说明如何记录“导出 Feature 状态清单”能力，未实现该功能、未运行测试、未提交或部署。

关联链：SRC-EXAMPLE-001 → REQ-EXAMPLE-001 → FEAT-EXAMPLE-001 → RUN-EXAMPLE-001 → EVD-EXAMPLE-001 / HANDOFF-EXAMPLE-001。

Run 已结束只表示示例中的一次规划工作结束。Feature implementation=not_started，没有有效验证和交付，按草案规则应为 ready；示例的 not_verified Evidence 不产生 PASS。

```text
.project/
├── project.yaml
├── sources/registry.yaml
├── requirements/REQ-EXAMPLE-001.yaml
├── features/example/FEAT-EXAMPLE-001.yaml
├── runs/RUN-EXAMPLE-001.yaml
├── evidence/FEAT-EXAMPLE-001/EVD-EXAMPLE-001.yaml
├── handoffs/HANDOFF-EXAMPLE-001.yaml
├── decisions/README.md
├── refs/{architecture,development,testing}.md
├── generated/.gitkeep
└── cache/.gitkeep
```

未来 generated 输出 status.json、features.json、claims.json、graph.json；当前不手工伪造生成结果。cache 保存本地实例指针及临时事务数据，不是事实源。采用真实自管理时应隔离这组 example 数据，不能把 mode 改为 managed 就当作真实记录。

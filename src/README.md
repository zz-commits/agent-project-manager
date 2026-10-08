# 核心实现

apm/facts.py 加载与校验，state.py 推导状态、subject 与 Claim 重叠，storage.py 实现本地事务，operations.py 提供经过完整候选校验的写 API，cli.py 实现 JSON 与退出码。

结构约束唯一来源为 schemas/v1；跨文件规则由 facts 检查。

verification.py 实现命名 JUnit Check 执行与 Evidence 导入；delivery.py 只读观察 Git 对象并保存人工 MR 记录。sources.py 实现本地 Markdown/Agent 输入、Registry 摘要、只读提案、受保护应用及拆分计划导入。

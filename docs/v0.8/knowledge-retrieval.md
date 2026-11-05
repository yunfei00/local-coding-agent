# 工程检索与轻量 RAG

knowledge_search 通过原工具注册表提供文件名、内容、符号检索；返回实际路径、行号范围、片段、匹配原因和索引版本。无需 Embedding、向量数据库或本地模型。

支持 md/txt/py/ts/tsx/js/jsx/json/yaml/yml/toml/log。SQLite project_knowledge_files 保存派生内容和符号；每次检索检查文件摘要，增量更新、清理删除项。校验内容摘要、符号行号和元数据，损坏的派生索引重新生成。

默认上限为单文件 256 KiB、2500 文件、总计 16 MiB，截断状态通过索引元数据暴露。遵守根目录及嵌套 .gitignore 和 .lca/exclude，忽略 node_modules/.venv/.git/dist/build 等生成目录。拒绝越界路径、符号链接、二进制、凭据文件和已知密钥内容。搜索结果再次读取实际文件，不信任旧索引中的过期行号。

自动工程读取先注入少量相关记忆和最多 3 条检索片段，进一步读取仍走原工具及权限；不会把全部仓库发送模型。显式 Pinned Files、MCP 和原 SearchFiles 继续保留。

依赖构建的 `.egg-info` / `.dist-info` 元数据不作为工程知识或自动源码变更；显式文件修改仍由原工具执行账本记录。自动检索查询最多使用原始目标的 500 字符，避免旧编排长反馈超限；用户目标本身不截断。

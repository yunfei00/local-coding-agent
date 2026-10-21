# 独立验证

验证由程序调用原 `run_command` 工具，经过 PermissionPolicy 和 Approval，不需要一次模型调用。Task 面板可逐行指定命令，或在工程根目录创建 `.lca/verification.json`：

```json
{"commands":["uv run pytest","npm run build","git diff --check"]}
```

只填写本工程实际可执行的命令。未配置时检查 `package.json` 中的 test/typecheck/build；Python 检查 tests 目录和 pyproject 中的 pytest 配置，否则运行 unittest；发现可用验证命令且为 Git 工程时补充 `git diff --check`。不会对每个工程执行固定列表，也不会自动安装缺失依赖。没有可用命令、发现零项测试或配置无效时不能验收通过。

在模型执行前解析并持久化命令快照，后续修复和恢复继续使用此快照。模型修改 `.lca/verification.json` 或 package scripts 配置不能替换已经选定的命令列表；项目自身测试脚本的内容仍应在最终 Diff 审查中复核。只有用户暂停后显式 Apply configuration to paused task，才重新解析验证配置。

每条命令记录退出码、stdout/stderr、耗时、类别和日志路径。Shell 的内存/实时输出有限，完整流写入应用数据目录 `verification/<plan-id>/<uuid>.log`；单文件上限 64 MiB，超出后明确标记截断且不认定验证通过。模型只收到有限摘要，完整日志留本地。分类为代码错误、断言、环境、权限、网络、超时、配置。分类是基于错误码和输出的启发式，报告保留原始退出码与摘要，用户可据此复核。

每次验证通过内部白名单环境参数设置唯一 `PYTHONPYCACHEPREFIX` 并启用 `PYTHONDONTWRITEBYTECODE`。这避开旧缓存且不生成新缓存，防止自主快速编辑遇到 Python 同一秒、同大小的旧 `.pyc`，不会删除或改写用户缓存。模型工具参数没有开放任意环境变量注入。

测试/代码失败交给本地 Executor；连续失败或相同失败/Diff 无进展时，在许可与预算内请求有限诊断。环境、配置、权限、网络和超时问题先暂停，不用付费模型盲目重试。日志摘要没有实际运行或未通过时绝不标记任务 completed。

验证前后比较非忽略的工作区文件快照；审查和最终接受报告时再次核对，防止在测试后修改未验证文件。快照包括未跟踪文件，最多 10000 文件/100 MiB，超过则暂停整理 Git ignore。测试产生不应纳入代码审查的缓存/构建产物应配置 `.gitignore`；若验证期间工作区变化，整理后重新验证。符号链接到 Workspace 外的文件仍受路径检查限制。

Pause task、Stop task 和主输入区 Stop 均取消活动异步任务，沿用 Windows Job Object / POSIX 进程组终止命令树。恢复须用户确认当前 Worktree 和 Checkpoint；使用原执行证据和成功修改指纹，完成步骤不会被自动重放。最终报告先进入 awaiting_approval；接受仅确认已验证报告，Git commit/push/merge 仍需原显式 Git 流程与审批。

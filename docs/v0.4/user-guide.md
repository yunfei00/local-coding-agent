# 公司电脑部署与使用

详细配置及可复现工程见 [公司验证流程](company-validation.md)。代码版本 0.4.2；正式发布结果以 [验收记录](acceptance.md) 和 README 的 Release 链接为准。

## 项目和会话

侧栏 Projects 右侧文件夹图标 → Create new project 打开居中弹框，填写项目名称并用 Choose… 选择父目录，默认位置为 Windows 文档目录。Create project 创建新文件夹并打开；默认初始化空 Git 仓库，不自动提交或发布。已有同名文件夹不会被覆盖，使用同一菜单的 Add existing folder 打开。各项目右侧写入图标打开空草稿，首次发送内容才保存会话；右键会话支持 Rename、Delete。删除保留代码和任务审计记录，未结束任务需要先取消。自主 Worktree 任务需要先在项目中准备文件和初始提交。

会话右侧悬停显示 `…`，或右键会话 → Rename，在居中弹框中修改名称。Enter 保存、Escape 取消；修改其他项目的会话名不会切换当前项目。正文和聊天输入为 16px，常规控件为 14px。完整说明见 [桌面交互更新](desktop-usability.md)。

## 配置模型

Settings → Models & Routing 添加多个 Ollama/OpenAI Compatible 连接，每个连接分别测试、获取模型或手动添加模型。模型列表跨连接展示，同名模型有独立 ID。

Role Routing 中分别选择 Planner、Executor、Reviewer、Escalation。默认 Local-first，建议前三个本地、升级 API。旧 Provider 页控制普通聊天，不会改动这些绑定。连接配置与模型角色需要在本页点击 Save model configuration。

API Key 用密码框和 Save / clear connection key 保存，随后保存模型配置引用。Windows safeStorage 保护密文；不可用时仅本会话有效。原有单 API Key 保留在原存储，迁移不会复制到 SQLite。换电脑重新配置凭据。

Local-only 保证自主任务不发送 API 请求；绑定冲突会在请求前报错。API-only 需绑定相应 API 模型，所有调用均计入预算。公司 LAN Ollama 按 Ollama 类型视为本地服务。

普通聊天使用 Settings → Provider 的服务和输入框底部 Chat model，不使用 Task 的四角色绑定。v0.4.2 起发送会携带当前可见的模型并同步保存到会话；旧会话模型不在当前服务列表时显示 unavailable，需重新选择。无需删除历史、清空配置或重新填写 API Key。排查细节见 [聊天模型同步修复](chat-model-sync.md)。

## 开始任务与恢复

1. 打开有初始提交的 Git 项目和 Thread，展开 Task，设置目标与验证命令。空验证命令按工程自动发现；不知道如何运行时先确认真实测试命令。
2. 选择策略和角色模型；Task 中选择不自动覆盖已保存默认值。批准隔离 Worktree 后执行，源工作区未提交文件保留原位，不自动带入任务分支。
3. 查看实际角色、Provider、模型、请求账本、API 使用与剩余预算、计划、测试错误分类、升级原因和状态。完整验证日志留在本机，摘要有界。
4. Pause task 暂停；Stop 取消并终止执行中的工具进程树。Reopen / continue 前检查 Worktree 和 Checkpoint。模型配置与账本从任务快照恢复，设置修改不会重路由已有任务。
5. 要改变旧任务，暂停后使用 Apply configuration to paused task 显式刷新角色/地址/命令；Add task budget 显式提高该任务上限，原账本不清零。全局预算默认值对新任务快照生效。
6. 验证通过进入 awaiting_approval。阅读报告、测试和 Diff，再 Accept verified report。接受报告不自动 commit/push/merge；在原 Git 工作流中继续审查与操作。

Git、Context、Logs、Plan 按需打开，不阻断输入框。Enter 发送、Shift+Enter 换行；暂停并不关闭 Thread，旧消息、计划和 Checkpoint 仍可打开。

## 预算与限制

本轮源码对未配置预算的新任务默认提供 200 次 API、1,000 万 Token、请求 120 秒、任务 2 小时、本地修复 3 次；全局默认 2,000 次、1 亿 Token，任务级和全局级同时预检查。旧配置保留，在 Settings/Task 点击 Use long task budget 并保存或应用；旧步骤/工具限制在 Settings → Agent 点击 Use long task execution limits 后保存。模型上下文与最大输出仍受模型能力限制，循环、失败、审批和 Stop 保留。输入按保守字节估算并预留最大输出，真实 Usage 单独显示，未知统计标估算。超时/失败保留预留；无价格时不能保证费用上限，配置价格后才能启用费用硬预留。供应商实际 tokenizer 与收费仍以网关为准。详见 [预算控制](budget-control.md)。

环境依赖、权限、网络、超时和配置问题先暂停，不把它们简单记作代码失败升级。升级只发送有限诊断上下文，无工具执行权；建议交回 Executor，最终必须运行独立测试。公司代码发送到 API 前应确认所选网关获准接收。

真实小模型基础连接与完整复杂修复能力是两个结论；无真实 API 凭据时用自带 Mock 工程验证路由，真实计费集成明确留待公司验收。

# 可复用模板

模板数据位于 `agent/core/workflow_templates.json`，通过同一个 `workflow_template` 工具展开到原 TaskPlanStore。包含 Bug 修复、新功能开发、代码审查、自动测试、环境诊断、Windows 软件操作、文档生成及安装包构建，共 8 项。

每项包含适用范围、步骤、角色、依赖、验收标准、权限需求与失败策略。模板不执行命令，不授予权限，不改变聊天模式。高级设置可展开查看模板。

展开参数仅支持 goal 和 verification_command，都是有界文本；实际命令仍通过原工具审批。加载器可接受最多 20 个经校验的自定义模板，重复 ID、无效图及未知字段会拒绝。当前尚无独立自定义模板编辑界面。

安装包构建模板只准备及构建，不自动创建 Release 或 Tag。本次 v0.9 也不发布 Release/Tag。

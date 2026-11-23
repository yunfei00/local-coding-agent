# Agent Skills 兼容性与安全模型

## 目标

兼容标准 `SKILL.md` YAML frontmatter（至少 name、description），保留旧版 `skill.json` 作为兼容路径。技能资源可包含 scripts/、references/、assets/，但安装技能不会自动执行脚本。

技能发现位置：
- 项目：`.agents/skills/<name>/SKILL.md`、`.agent/skills/<name>/SKILL.md`
- 内置：仓库 `skills/<name>/SKILL.md`
- 用户：由 SkillManager(user=...) 显式指定

同名技能按项目 > 用户 > 内置覆盖，禁用列表保存在项目 `.agent/disabled-skills.json`。

## 安装

`python -m agent.skills.cli --workspace . skills-list`
`python -m agent.skills.cli --workspace . skills-install path/to/skill-folder`
`python -m agent.skills.cli --workspace . skills-install path/to/skill.zip`
`python -m agent.skills.cli --workspace . skills-install-github https://github.com/OWNER/REPO/tree/main/skills/SKILL_NAME`
`python -m agent.skills.cli --workspace . skills-read excel`

在线安装限定公开 GitHub HTTPS 地址；对 ZIP 条目做数量、解压大小、路径穿越、符号链接检查。技能脚本不自动执行，技能内容作为不可信数据，实际工具权限仍由 Agent 统一策略决定。

**安全限制**：当前在线下载器没有提供提交 SHA 锁定、签名验证、完整的供应链审计和 DNS 重绑定防护，不应视为已通过安全审计。GitHub 目录链接对含斜杠的分支名有歧义，可通过明确分支和技能目录处理。

## 能力边界

Skill 本身不提供 MCP 工具或 Python 环境。技能说明中提到的命令只能通过已授权工具执行。第三方技能可能依赖特定宿主环境或外部服务，安装成功不等于其所有功能可用。

当前实现：Skills List/Read Agent 工具、Office 基础工具、Browser Snapshot 工具已注册到 ToolRegistry。完整 GUI 管理、在线市场搜索、浏览器交互、Office 复杂编辑、自动端到端验收仍需进一步开发。

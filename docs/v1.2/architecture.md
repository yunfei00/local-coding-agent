# v1.2 Skills + Office + Browser 架构

本阶段采用 Skills（指令）/ Tools（执行）/ Agent（调度）/ Verifier（验证）分层。

- M1: agent.skills 提供工作区内声明式技能发现、启用禁用、安装卸载；不执行下载或脚本。项目技能优先于用户和内置技能。
- M2: agent.office.engine 提供 xlsx/docx/pptx 后台读写，写入采用同目录临时文件 + 原子替换。
- M3: Office COM 仅 Windows 且安装 Microsoft Office 时可用，提供只读源文件 PDF 导出；复杂 UIA 复用现有 desktop_* 工具，不绕过桌面授权。
- M4: agent.browser.engine 提供受限 Playwright 网页快照，禁用下载、限制同主机请求。此为基础适配器，非完整交互浏览器工具。
- M5: agent.verification.office 提供重新打开产物的结构验证；不能等同于真实 Office 视觉验收。

## 安装依赖
可选安装 openpyxl、python-docx、python-pptx；Windows COM 需要 pywin32；Playwright 需要 playwright 与浏览器二进制。依赖未安装时相应功能明确失败，不影响 Agent 核心启动。

## CLI
在项目 Python 环境中运行 `python -m agent.skills.cli --workspace <工作区> skills-list`。
其他命令：skills-install、skills-enable、skills-disable、skills-uninstall、inspect、verify、create、export-pdf。
create 从工作区 JSON 规格文件生成 Office 产物，所有文件路径限制在工作区。
本 CLI 只能经现有 run_command 和权限策略调用，不能绕过审批。

## 未完成边界
当前实现不含 Skills UI 自动推荐与注入 Agent 提示词、不含完整 Office 复杂编辑、浏览器 DOM 点击/输入/下载、端到端 UI 自动验收。必须在实现并验证后才能宣称 M1–M5 全部完成。

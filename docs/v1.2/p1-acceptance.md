# Local Coding Agent v1.2 P1 — 集成验收

本阶段在 `feature/v1.2.0-agent-skills` 开发，PR #39 保持 Draft，未经人工验收不得合入 main。

## 已接入

- Skills：标准 `SKILL.md` / 旧版 `skill.json` 发现、目录/ZIP/公开 GitHub 安装、启停、卸载、任务匹配、静态安全审查、项目技能备份/本地更新/回滚；设置面板提供中文管理入口。安装和安全审查不执行技能脚本。
- Office：`office_document` 提供 `inspect`、`create`、`edit`、`verify`、`bundle`、`detect`、`uia_list`、`export_pdf`；编辑涵盖 Excel 单元格/公式/样式/列宽/图表、Word 文本和表格、PPT 页面/备注；bundle 一次生成 XLSX、DOCX、PPTX，全部结构验证后交付，失败清理已创建文件。
- Windows：可探测 Office COM 安装、枚举 Office UIA 窗口、使用已安装的 Microsoft Office 导出并验证 PDF 文件头。

## 已知边界

- 静态 Skills 安全审查不能证明脚本安全，第三方技能不得绕过权限或自动执行。
- Word 文本替换基于单个 run，不保证跨 run 匹配；Office 编辑属于结构化文件操作，不是完全复刻 Microsoft Office 的所有排版功能。
- Office COM 需要本机安装 Microsoft Office 和 pywin32；UIA 仅实现发现与诊断，不会自动点击或修改窗口。
- 文件结构验证不等于视觉排版验收；Office 文档复杂模板、图表细节及 Windows 真机回归需要另行验证。
- 浏览器完整交互属于 P2，跨工具自主验证与交付属于 P3，不属于 P1。

## 自动化验收

在 CI 运行 `python -m unittest discover -s tests -p "test_v12_*.py" -v`，同时执行仓库主 CI。Windows 和 Ubuntu 两平台通过才可宣称 P0/P1 基础回归通过。任何红灯都必须定位日志修复；不得仅修改测试来掩盖产品缺陷。

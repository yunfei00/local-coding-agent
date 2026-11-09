# v1.2 P3 自动验收使用说明

## 使用入口
在 Windows 客户端「设置 → 交付自动验收」填写 JSON 验收规则，选择新的 Markdown 报告路径，点击「开始验收并生成报告」。Agent 也可调用 `deliverable_verify` 工具。

示例规则：

```json
{
  "files": [
    {"path": "data.xlsx", "expect": {
      "sheets": ["Data"],
      "cells": [{"sheet": "Data", "address": "B2", "value": "=2+3"}]
    }},
    {"path": "report.docx", "expect": {"contains": ["Summary"]}},
    {"path": "deck.pptx", "expect": {"contains": ["Overview"], "min_items": 1}}
  ]
}
```

## 自动检查
- 所有文件必须在当前项目工作区，最多 30 个文件
- XLSX 检查工作表名称、单元格值与公式字符串
- DOCX 检查正文、表格可读文本
- PPTX 检查幻灯片可读文本
- 每份文件返回结构检查和逐条断言的结果，任一失败则整体不通过
- 报告必须是工作区内不存在的 .md 文件；不覆盖已有文件
- 浏览器 `workflow` 支持 `assert_text` 和 `assert_url` 步骤，可在网页操作后验证页面状态
- 浏览器操作须遵守 Agent 权限策略和网络访问边界

## 自动化 CI
v1.2 专项工作流在 Windows/Ubuntu 上安装 Office 测试依赖、Playwright 和 Chromium，运行 `test_v12_*.py`。实际 Chromium 测试使用本机 HTTP fixture，且仅在测试范围内临时绕过公网 URL 校验；生产代码不放开 localhost。

## 验收边界
当前自动验收仅覆盖结构和内容，不等于真实 Microsoft Office GUI 的视觉验收，也不等于外部网站上传成功。浏览器操作结果必须通过 URL 或页面文本断言验证。GitHub Actions 必须完成并全绿，才能进入 PR 合并阶段。

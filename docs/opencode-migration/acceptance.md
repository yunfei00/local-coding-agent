# 候选验收方式

| 验收对象 | 执行方式 | 证据 |
| --- | --- | --- |
| Python、桌面类型检查、桌面单元、前端构建 | `uv run --no-sync python scripts/validation/check.py` | `validation-reports` 下本次 JSON 和日志 |
| 正式产品 Mock | `node scripts/validation/opencode/desktop-live.cjs --mock` | 原生批准、文件独立读取、下一轮工具输出、重启历史 |
| Ollama | `node scripts/validation/opencode/desktop-live.cjs` | 挑战字串、真实流式完成、重启历史 |
| Ollama 实际写入 | `node scripts/validation/opencode/desktop-live.cjs --project-write` | 隔离文件实际内容、审批和工具完成 |
| OpenCode Task 服务 | `uv run --no-sync python -m unittest discover -s tests -p test_opencode_data_service.py -v` | Git 隔离、真实测试失败并修复、预算拒绝、WinForms 独立断言 |
| 候选无 SDK | `node scripts/validation/packaged_chat_smoke.cjs <exe> <新建隔离目录> --no-sdk` | 两次启动、环回 HTTP、原生文件读取和执行引擎身份 |

按提交记录 PASS、FAIL、PARTIAL、BLOCKED、NOT RUN。真实在线模型另行确认授权和预算。

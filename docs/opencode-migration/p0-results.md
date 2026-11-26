# P0 Windows ?????

**???P0 ???? BLOCKED?** 2026-11-24 ??????? SSH ??????? Ollama ???? Gemma4 ? Windows ??????????MCP ????????????????????? P0 ???

> 2026-11-26 ??????????????????????**?????????? token ???????/?? Token ?????**??????????/Shell/Git/MCP ?????????????????????????????????????


| 检查 | 状态 | 观察 |
| --- | --- | --- |
| 上游版本、Windows x64 二进制、SDK 锁定 | PASS | 归档与官方摘要一致，真实服务返回 2.2.6，独立 SDK 依赖树已锁定。 |
| 隔离服务、鉴权、会话 | PASS | 未认证 401、认证健康 200、新建 200、回查 200 且匹配会话 ID。 |
| SSE 与空闲中断 | PASS | SSE 200，接收首段 83 字节；空闲中断 200 且 `interrupted=false`。 |
| POC 退出 | PASS（限定） | 回收本次启动的进程，根进程退出码为 1。本次采用定向终止，优雅退出和异常恢复尚待验收。 |
| 活动取消、会话恢复 | PASS（限定） | 在网关暂挂真实侧车的请求，取消返回 `interrupted=true` 且连接关闭。重启前后会话均为 `interrupted`，会话处于非活动状态，真实推理为 0。单次强制退出复验窗口内未观测到自动模型请求。 |
| 端口冲突、完整断线事件重放 | 待验 | 端口由系统分配。默认 HTTP sidecar 配置下，测试会话的历史事件流未返回中断事件，持久会话快照保留中断终态。 |
| `gemma4:31b` | PASS（专项） | 问答 1 请求、读写 3 请求、Shell 2 请求、读取失败后恢复 3 请求、写权限撤销 2 请求，共 11 次真实本地请求。 |
| `gpt-oss:20b` | SKIP | 远端 Ollama 实际模型清单中不存在该模型。 |
| 内置工具权限 | PASS（限定） | 目录内指定文件和受限 Echo 通过。运行中 PATCH 撤销返回 204，真实写入报 `permission.rejected`，原文件未变。完整高风险和外部路径矩阵尚待验证。 |
| MCP 授权与取消 | NOT_RUN | 已核对接口，尚无实际 MCP 工具执行证据。 |
| ????????????????? | PARTIAL | ?????????????? token ???????/?? Token ?????????????????????????????????????/??? |

临时 SSH 转发只绑定本机回环地址，未改用户的 Ollama 或产品配置。此前拒绝连接来自原回环端口缺少可用监听。实际 Provider 使用 v2 `providers` 配置及 OpenAI 兼容 `/v1/chat/completions`。探针上下文配置为 8192，网关每次输出上限 512，远端模型加载的实际最大上下文未测。可在已建立的临时转发端口运行：

```powershell
node scripts/validation/opencode/p0-model.cjs <回环端口>
node scripts/validation/opencode/p0-model.cjs <回环端口> --lifecycle-only
node scripts/validation/opencode/p0-model.cjs <回环端口> --crash-only
node scripts/validation/opencode/p0-model.cjs <回环端口> --gate-only
```

通过的批次记录在 `build/opencode-p0/model-ZldMHc/report.json`，取消与重启记录在 `model-eNRrgx/report.json`，强制退出记录在 `model-gq0Puh/report.json`。早期 `model-gWDFVX` 的撤销用例随后触发模型输出上限。最终复验区分权限拒绝与模型收尾，并检查原文件内容。所有模型输入都是合成用例，报告仅输出事件名称、计数、用量及断言状态。

## 回归

| 命令 | 本地结果 |
| --- | --- |
| `uv run --locked python -m unittest discover -s tests -v` | 762 项，758 通过、2 失败、2 跳过。失败为现有 M2 Electron 子进程测试及 M5 Electron 多轮 GUI 测试。 |
| `npm run desktop:typecheck` | PASS |
| `npm run desktop:test` | 102 PASS |
| `npm run desktop:build` | PASS |
| `node scripts/validation/desktop-smoke.cjs` | Windows 56 PASS，0 跳过。含现有 Agent 路径，模型 HTTP 为模拟服务。 |

Python 首轮在调用子进程时遇到主机注入的 Git 环境配置项缺失。表中数字来自只清除当次测试进程所继承 Git 配置变量后的完整重跑。失败记录仍保留，来源见 `build/opencode-p0/python-baseline-clean-env.log`。服务原始报告及生成的 OpenAPI 在 `build/opencode-p0/service-*/`，只读 Ollama 探测在 `build/opencode-p0/ollama-availability.json`。归档、源码快照、会话数据库及本机日志均在本地构建目录。

两个本机 Electron 集成失败的工具记录都出现 `COMMAND_TIMEOUT`，随后启动的进程报告退出码 1。相同产品基线的 [main CI](https://github.com/yunfei00/local-coding-agent/actions/runs/45199993944) 通过。补充证据见 `validation-reports/desktop-smoke.json`、`validation-reports/m2-project-test_electron_real_main_node_python_descendants_stop_and_cancel.json` 和 `validation-reports/m5-debug-test_actual_electron_multiround_http_gui_stop_resume_restart.json`。

P1?P5 ?????????????????????? token ???????/?????????????? MCP ??/??????????????? ?? CI ? (https://github.com/yunfei00/local-coding-agent/actions/runs/45290597976)?

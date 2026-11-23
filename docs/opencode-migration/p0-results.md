# P0 Windows 可行性验收

**结论：BLOCKED。** Windows 固定版本服务的基础检查通过。2026-11-23 的两次 Ollama 模型清单探测均未成功，2026-11-24 复查再次明确返回 `ConnectionRefusedError`。未经授权的付费 API 请求为 0，模型推理请求为 0。

| 检查 | 状态 | 观察 |
| --- | --- | --- |
| 上游版本、Windows x64 二进制、SDK 锁定 | PASS | 归档与官方摘要一致，真实服务返回 2.2.6，独立 SDK 依赖树已锁定。 |
| 隔离服务、鉴权、会话 | PASS | 未认证 401、认证健康 200、新建 200、回查 200 且匹配会话 ID。 |
| SSE 与空闲中断 | PASS | SSE 200，接收首段 83 字节；空闲中断 200 且 `interrupted=false`。 |
| POC 退出 | PASS（限定） | 回收本次启动的进程，根进程退出码为 1。本次采用定向终止，优雅退出和异常恢复尚待验收。 |
| 端口冲突、断线重放、运行中取消与恢复 | NOT_RUN | 基础 POC 使用系统分配的空闲 loopback 端口。 |
| 两个目标 Ollama 模型清单与任务 | BLOCKED | 已有配置的服务拒绝连接，无法判断模型是否存在；问答、文件、终端和失败恢复未执行。 |
| 内置工具约束、动态撤销、MCP 授权与取消 | NOT_RUN | 已核对接口，尚无实际执行轨迹证明约束。 |
| 请求前预算硬闸 | BLOCKED | 找到请求发送前扩展点，各条路径的动态覆盖尚未验证。 |

## 回归

| 命令 | 本地结果 |
| --- | --- |
| `uv run --locked python -m unittest discover -s tests -v` | 762 项，758 通过、2 失败、2 跳过。失败为现有 M2 Electron 子进程测试及 M5 Electron 多轮 GUI 测试。 |
| `npm run desktop:typecheck` | PASS |
| `npm run desktop:test` | 102 PASS |
| `npm run desktop:build` | PASS |

Python 首轮在调用子进程时遇到主机注入的 Git 环境配置项缺失。表中数字来自只清除当次测试进程所继承 Git 配置变量后的完整重跑。失败记录仍保留，来源见 `build/opencode-p0/python-baseline-clean-env.log`。服务原始报告及生成的 OpenAPI 在 `build/opencode-p0/service-*/`，只读 Ollama 探测在 `build/opencode-p0/ollama-availability.json`。归档、源码快照、会话数据库及本机日志均在本地构建目录。

P1–P5 尚未开始。继续阶段开发需要真实 Ollama 验收、工具权限和预算硬闸的动态证据，以及 Windows 与 Ubuntu CI 通过。

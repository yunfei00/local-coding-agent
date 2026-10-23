# M4 自动验收记录

日期：2026-10-23；基线 PR #14。以下区分自动化模型替身与真实付费服务，所有 GUI/文件/进程/构建均使用真实实现。

## 本机百炼配置审计（只读）

已有 Ollama、DeepSeek、Alibaba Bailian 三个连接，全部保留。百炼地址为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，profile 模型 `qwen3.5-plus`。连接 enabled=true，但 credential_reference=null；用户数据目录不存在 model-secrets.json，只有 legacy provider-secrets.json（对应迁移的 OpenAI 连接，不能据此推断内部 key 当前属于哪家服务）。环境没有可用百炼/诊断 API Key。百炼没有 supports_vision 声明，Executor 未绑定该 profile，默认策略仍为 local-first。

没有修改用户数据库、覆盖旧连接或解密/打印 key。CLI 本地诊断：configuration FAIL / API_KEY_MISSING，connection、text、vision、tools 全部 NOT RUN；实际付费 API 请求 0，实际服务 Token 无数据、费用未知（本次无请求产生费用）。不把 Model Studio 文档、旧 DeepSeek 测试、Mock 成功或 models GET 当成百炼实测。

## 自动化范围

| 场景 | 实际验证 |
| --- | --- |
| 默认诊断 | 无模型请求，网络阶段 NOT RUN |
| 视觉支持与不支持 | 真 JPEG 构造/真实 HTTP 传输；模型替身识别结果断言；错误 CHECK 即使 HTTP200 也 FAIL |
| 错模型、无效 key、超时、无 Function Calling | 模型响应替身，错误分类、停止重试/不追加调用 |
| 连接切换/绑定/安全存储 | 独立连接凭据回归、跨连接引用拒绝、实际 Electron Settings 保存/重启/恢复 |
| WebSocket 非阻塞 | 真实 WebSocket 长诊断期间 catalog 请求即时响应、Stop 取消，未继续视觉/工具请求 |
| Windows 自主修复 | 实际 WinForms 编译/启动、UIA 点击/输入/状态等待、PrintWindow、独立断言、两轮修复、Git Diff、进程退出 |
| 独立视觉观察 | Windows 实际 JPEG 进入所选观察模型消息；替身只返回观察，不执行工具 |
| 上传被拒绝 | 实际 M3 审批拒绝，观察请求为零、任务暂停、进程清理 |
| 修复耗尽/自称成功 | 模型声称通过不能绕过失败的真实控件断言 |
| 运行取消 | 实际 GUI 等待取消，GUI 与 worker 清理，不继续操作 |
| Python/React/TS/Electron | 保留并运行 M1/M2/M3 真实工程回归；非 Windows GUI 明确跳过 |

最终完整 `uv run python scripts/validation/check.py`：322 项 Python（Windows 跳过 2）、42 项 Vitest / 12 文件、TypeScript 类型检查与构建全部通过，Errors=0。报告 `validation-reports/20261023-090552-169445.json`。此前首轮为 316 项，新增 HTTP 错误、CLI 只读退出码与契约冻结后进行了完整复验。诊断专项 13 项通过；GUI 专项包含 5 项真实 Windows 场景及 2 项跨平台契约。desktop-smoke 实际 Electron/Renderer/Agent 27 项通过、0 跳过。

[Windows / Ubuntu CI 完整记录](https://github.com/yunfei00/local-coding-agent/actions/runs/39882035101) 两端通过：Windows 实际运行 322 项，跳过 2；Ubuntu 实际运行 322 项，跳过 12（Windows GUI 与 CMD 场景）。两端桌面单元测试、类型检查、构建通过，Windows 另执行 27 项 desktop-smoke。后续敏感契约保存前校验补充了同一跨平台契约测试中的拒绝断言；最终提交门禁以 [PR #15 最新检查](https://github.com/yunfei00/local-coding-agent/pull/15/checks) 为准，全部通过后合并。

凭据/私有产物扫描 305 个受版本控制文本文件，无发现；编译检查、git diff --check 通过。扫描是模式与已知环境密钥检查，不宣称覆盖所有未知凭据格式。原始日志和 JSON 位于忽略的 validation-reports；CI 仅保留受控 fixture JSON，不上传截图或用户配置。阶段性失败已修复，不作为最终通过证据。

## 限制与 M5

真实百炼兼容性尚未验证：需用户主机安全存储中有可用 key 并显式启用 Live Test；完整入口和脚本已实现，无需用户查日志/手工截图。任意应用自然语言任务仍需可检查的独立验收契约，缺失则 GUI NOT RUN。Windows 10 与各种自绘/GPU/多屏组合未逐一实机覆盖，安装包未生成或验证。

M5 的连接诊断、观察器、冻结验收、证据、修复记录和取消接口已具备。可启动后续设计与回归工作，但不能把百炼真实服务验证列为已通过。本次完成后停止，不自动进入 M5；不创建 Tag、Release 或安装包。

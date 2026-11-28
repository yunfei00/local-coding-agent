# v2.0.0 正式交付审计

审计基线为 PR #40 的 `9f4e80c408e49c09f7191e9305c42601c775be1d`。本地与远端开发分支一致。未跟踪的附件和 Python 元数据保留。现有 OpenCode 可执行文件的 SHA256 与锁文件一致，实际运行版本为 v2.2.6。

|级别|基线问题|代码证据与验收要求|
|---|---|---|
|P0|正式会话使用全允许规则，审批请求无法正确回复| `openCodeRuntime.ts` 创建 `*/* allow`，Supervisor 路由未放行回复，负载字段也与上游不一致。需要真实的允许、拒绝和受限模式回归。|
|P0|Task、Plan 和追加消息没有迁移完整| `main.ts` 拒绝 Task start/resume/continue/append，并禁用部分 Plan 操作。聊天参数中的继续执行信息没有传给 Runtime。|
|P0|旧执行入口仍可用| Electron 有旧执行分支，Python WebSocket 的 turn.start 和 TaskService 仍能启动旧循环。需区分生产数据服务与历史回归。|
|P0|请求并发、会话归属与持久化失守| `startOpenCodeTurn` 并行读取当前工程，取不到时使用 cwd。Runtime 每次启动新数据目录，模型配置只按 cwd 判断。跨工程或切模型可能误路由。|
|P0|退出判定和停止存在缺口| `startOpenCodeTurn` 把 idle 作为成功证据。断流/取消没有统一清理路径。|
|P0|正式模型链路没有实际预算门控| `openCodeConfig.ts` 直接把所有连接和凭据交给 Runtime。Ollama 配置缺少 OpenAI 兼容路径。已有预算代理仅用于实验链路。|
|P0|独立升级未实际实现| `openCodeUpdateManager.ts` 不查询上游、不下载二进制，兼容性固定为真，升级成功不切换；Settings 与 Runtime 未连接。|
|P0|正式交付证据不完整| 既有报告只证明历史打包尺寸、协议模拟与独立模型探测。必须重新验收正式 Electron、安装版和便携版。|
|P1|Mock 主要测试替身本身| `test_mock_ollama.py` 未覆盖 Renderer → IPC → Runtime → 模型请求的完整路径。|
|P1|实验切换和无效 IPC 残留| `App.tsx` 有实验引擎选择器。预加载暴露多项无正式实现的实验接口。|
|P1|CI 与新运行时脱节| Windows 桌面 smoke 仍依赖旧链路及脚手架。当前 CI 结论需逐提交核对。|
|P2|免费模型可用性依赖上游| 需核对官方目录、地区、凭据和可用额度。目录列出不表示当前 Runtime 和账号已验证。|

协议依据为锁定提交的 [会话](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/protocol/src/groups/session.ts)、[事件](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/protocol/src/groups/event.ts) 和 [审批](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/protocol/src/groups/permission.ts) 定义。SSE 断开会漏事件。会话 prompt 支持 queue/steer，模型切换通过会话 model 端点，许可回复字段为 decision。

# M5 模型路由

复用 M4 的统一 Connection/Profile 目录。Chat 每 Thread 选择 profile:ID；Task Executor 与可选 Vision Observer 各自绑定 Profile，任务启动解析后冻结。相同 Model ID 不用于推测连接。

M5 自动测试通过本机 aiohttp 兼容接口分别接收 m5-coder 和 m5-vision：编码端返回工具调用决策，观察端只接收真实桌面 JPEG 和观察 Prompt，不接收工具 schema。这证明实际客户端、连接和 HTTP 协议，不证明在线模型智能。

已配置的本地或在线模型可以使用原路由机制；Single Agent 要求在线 Executor，Local-only 不允许在线 Observer。用户改 Settings 不改变已运行任务，暂停任务需明确 Apply configuration。

Mock 测试为多轮工程检查显式使用独立的 100 次请求/100 万 API Token 测试上限；普通执行账本按字节保守预留显式设 600 万（覆盖同一任务多次 Pause/Resume/Stop/拒绝测试），仍保留 64 次普通循环模型请求上限。只限隔离测试环境和临时数据库，不改变生产默认值，也没有真实费用。真实任务按用户原限额执行，预算耗尽暂停，不自动增加，不改换收费模型。本轮真实在线推理 NOT RUN。

# v0.9 综合真实验收记录

总体 **PASS**：2026-11-06 06:18～06:21（北京时间）桌面解锁后补测 G 通过，关闭此前锁屏/低内存阻断。不能以 Mock、旧版历史或模型调用前退出替代真实验收。以下路径相对本机忽略目录 `validation-reports/`，原始日志不提交 GitHub，避免包含用户文件和对话；旧失败/阻断证据不删除。

业务入口为生产认证 HTTP WebSocket，复用 AgentServer.websocket/handle_message/run_tool_turn。runtime_live_bridge.cjs 只从安全存储解密隔离副本凭据，经匿名 stdin 送入自有 Python 子进程，无 BrowserWindow，不是纯 GUI 验收。被测业务由 Agent 修改，外部驱动不代写解决方案。

| 场景 | 真实证据 | 结论 |
| --- | --- | --- |
| A Python | v09-workflow-python-independent/report.json，真实 unittest exit 0、原测试未改、交付存在 | PASS |
| B React | v09-runtime-react-resume-fixed/report.json，真实类型/测试/构建 exit 0；react-dom-result.png，输入 2、3 点击结果 5 | PASS（DOM，非 Windows GUI） |
| C 四角色 | Python/React Planner/Reviewer 为 Qwen，Developer/Tester 为 DeepSeek；独立读取、审查、测试、4/4 完成 | PASS |
| D 两模型切换 | 同任务角色交接实际切换、完成 ID 保留 | PASS；真实额度耗尽故障 NOT RUN，Mock 回退 PASS |
| E 修改后中断 | v09-runtime-continuity/report.json interruption 子项：实际修改后暂停恢复，原 2 个完成步骤保留 | PASS；该历史报告收尾驱动错误不改写 |
| E WebSocket | v09-runtime-websocket-offline/report.json：核对原同 generation 重连运行、真实 unittest 和 Git 契约，没增加模型请求 | PASS（原运行补验，非新在线任务） |
| F 自动修复 | v09-runtime-repair-protected/report.json：真实测试 exit 1→修改→exit 0，原冻结测试字节不变 | PASS |
| F 环境阻断 | v09-runtime-repair-environment/report.json environment 子项：真实 ModuleNotFoundError，environment，暂停 awaiting_user，无无限修复 | PASS（正确阻断）；报告另一 repair 子项 FAIL 保留 |
| G Windows 应用 | v09-gui-unlocked/report.json：在线 Qwen 实际定位/激活、UIA 输入/保存/读取/截图/停止，随机值 GUI-554fdf9f 与磁盘一致；cleanup-check.json 无本次残留 PID | PASS；原锁屏/内存 BLOCKED 证据保留 |
| H Git 交付 | A/B/F 真 Diff/验证/报告/原文件核对；审批、Worktree、私密 origin 有自动化回归 | PASS；未授权业务 commit/push，不执行 |
| I 低内存 | 真实门禁阻止低资源 GUI 启动；调度冲突/GUI 互斥/低内存串行单元通过 | PASS（门禁），非 GUI 功能通过 |

## 失败与修复链

1. v09-kimi-capabilities：真实 HTTP 400，停止，未改写 PASS。
2. v09-workflow-python：Planner 通用终端 Schema 与角色权限不一致。隐藏不允许工具、强化提示及后端限制，有界一次纠正。
3. v09-workflow-python-resume：被测工程完成，驱动误用优惠券契约。核对原已完成任务补验通过，无额外生成；原数据累计 14 请求。
4. v09-runtime-react：Tester 终端权限拒绝；旧日志没有确切命令，不断言最初必为 &&。补充拒绝诊断、每段都安全的有限测试命令链，原审批保留。
5. v09-runtime-react-resume：确认恢复漏掉原 workspace probe，PLAN_RESUME_CONFIRMATION_REQUIRED。修复为先原只读恢复检查再请求模型。原 3 个完成步骤保留，受影响运行补验 PASS，累计 17 请求。
6. v09-runtime-continuity：中断与重连业务通过，收尾变量复用 KeyError。修复驱动；补验先遇 CRLF 契约识别错误、再遇资源门禁，最终离线核对 PASS。原失败报告保留，未重复业务。
7. v09-runtime-repair-environment：实际修复后测试通过，但向明确冻结的原测试追加内容，外部 oracle 正确 FAIL。增加哈希/写前保护、间接修改最终检查和 Windows 路径规范化。新隔离任务 v09-runtime-repair-protected 原文件不变、真实验证通过，12 请求、167,588 实际 Token。不降低冻结断言，不用 Git 覆盖用户文件。

## 调用与边界

原轮次去重：continuity 24、React 17、repair/environment 25、protected repair 12、Python 14，共 92；能力另 5。新增 GUI 17，共 114 模型请求，另 1 目录 GET。已知实际 1,329,344 Token，一次取消与一次 HTTP 400 无准确 Usage，保留预留/估算，费用 UNKNOWN。见[验收报告](acceptance-report.md)。

最新原生 pending 调整、全局配置、额度回退跨角色快照为自动化集成 PASS，没有再发在线请求声称全部分支都真实覆盖。没有无限预算、未知副作用重放或额外聊天模式。

本机大测试及模型串行；锁屏/资源不足时未反复启动。解锁后只启动一组受控桌面验收（产品控制器与目标测试应用），未并行启动其他浏览器或 GUI 用例，结束核对 9 个自有 PID 全部退出，不结束无关用户程序。CI Mock Provider 桌面 Smoke、实际 M5 工具与 G 在线 Windows 操作分别计数。

GUI 补测没有改源码；保留了权限系统对两次目录越界和一次缺风险确认点击的拒绝。模型在本轮有限调用内纠正，实际读到 Saved 并正常清理。运行正确结束为 completed_unverified/manual、changed_paths=[]，没有运行 unittest 冒充代码验收。诊断 22 行，真实截图只保存在本机。

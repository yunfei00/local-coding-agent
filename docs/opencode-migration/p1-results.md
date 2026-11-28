# P1 适配层实施记录

状态：PARTIAL，未验收。用户允许先编写代码、最后统一实机验收，但 P0 安全门禁仍为 BLOCKED。

新增 desktop/electron/engineAdapter.ts：统一接口、Legacy 委托、OpenCode v2 会话创建/回查/中断、默认 Legacy 路由、线程级并发保护。OpenCode prompt 强制禁用；创建会话默认 deny-all。新增对应 Vitest 测试。

尚未完成：主进程接线、进程托管、持久映射、SSE 转换/去重、工作区级跨引擎锁、UI 选择、完整权限/预算验证。当前模块没有接入生产执行路径，不应标记 P1 完成。未运行测试或 CI。后续复用 P0 固定版本与真实接口记录，不重复建设 P0。

验收命令：npm run desktop:typecheck、npm run desktop:test、npm run desktop:build、npm run agent:test。Windows 实机统一验收，未通过不得启用 OpenCode 或合并 main。

## P1.9 集成检查
已提交 sidecar supervisor、session store、SSE parser、event bridge、workspace lease、IPC 状态和前端菜单及测试。当前仍为 PARTIAL：生产 turn/task 未经过新 router，sidecar 未接入启动流程，事件未接入 UI，互斥未覆盖后台任务。禁止开放 OpenCode prompt，禁止合并。CI 需要实际运行，不能以代码提交代替验收。

# 验证方式

修改代码后沿用原 VerificationEngine，按项目实际配置选择命令。普通问答不创建复杂计划或运行无关测试。测试必须直接通过工具真实执行，保留命令、退出码、stdout/stderr 摘要及日志。

验证级别、代码失败修复、环境/网络/权限/超时分类与无进展指纹复用已有统一运行时；本轮没有通过增加循环上限解决可靠性问题。

在仓库根目录使用 PowerShell：

```powershell
uv sync --locked
uv run --locked python -m unittest discover -s tests -p "test_v06*.py" -v
uv run --locked python -m unittest discover -s tests -p test_unified_runtime.py -v
$env:LCA_REQUIRE_INTERACTIVE_DESKTOP='1'
uv run --locked python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
git diff --check
```

Windows 真实 GUI 测试需要解锁的交互桌面。基础 HTTP Mock 测试不依赖真实付费 API；真实模型与真实 GUI 结果分别记录，不能互相替代。当前结果见验收报告。

新增覆盖：事件幂等与隐私、事务回滚、取消/终态屏障、启动中断、完整历史导出、运行中追加、无 Plan 原目标恢复、HTTP 分片、构造失败、429、超时和取消。

低内存 Windows 可限制测试并发，所有断言仍然执行：

```powershell
$env:VITEST_MAX_THREADS='1'
$env:VITEST_MIN_THREADS='1'
$env:NODE_OPTIONS='--max-old-space-size=256'
uv run --locked python scripts/validation/check.py
```

真实模型驱动额外覆盖实际响应流中断（本机透明代理只截断一次，凭据仅内存转发）、同页运行中追加、实际审批拒绝与原检查点恢复。模型调用只通过生产 Electron IPC/Agent 入口，Codex 不替模型实现被测计算器、优惠券、React 或 Electron 功能。

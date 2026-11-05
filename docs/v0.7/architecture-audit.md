# v0.7 Windows Computer Agent 审计

基线：main `d385d95feac4f9a889ecd699edebcdaa89b75dc2`。2026-11-05 本地/远程无 v0.7 分支，创建 `feature/v0.7-computer-agent`。用户未提交的 `.codex-attachments/`、egg-info 保留。只处理 v0.7。

## 复用

- `agent/desktop/runtime.py`、`worker.py`：当前用户/会话、窗口代际、UIA、焦点、输入、裁剪与脱敏截图、可取消 worker、Windows Job 进程树。
- `agent/tools/desktop.py`、原 ToolRegistry/审批：桌面访问和截图上传始终独立授权；坐标及高风险动作再次批准。
- 原统一聊天入口、Provider/Model Catalog/Observer、上下文、预算、持久计划、真实工具证据、独立 GUI 合约。不建第二套执行器或 Provider。
- M3/M4/M5 测试和 fixtures 保持路径与既有契约，补充系统应用、轻量本地网页和资源门禁。

## 分支审计

远程 Tkinter/Notepad/视觉修复分支与 main 分叉，部分改动已以其他提交进入 main。比较后确认 main 已有编辑框隐私遮盖、黑帧保护与普通输入确认；旧 Tk Pane 分支还包含落后的会话/焦点实现，不能整批覆盖主线。只按真实证据扩展必要能力，保留安全检查。

## 需验证/扩展

1. UIA 失效后的视觉坐标必须绑定本次授权截图、窗口、缩放与时效；不能让缩小图片中的坐标直接当作物理坐标。
2. 现代记事本可能暴露 Document/RichEdit，需实际探测再扩展输入，不能把“没有 Edit”当作已输入。
3. 原生应用启动 PID 不一定等于最终窗口 PID，必须通过受管理进程/本次发现确认归属，禁止关闭用户已有窗口。
4. 验收串行，先单元/集成，启动真实 GUI 前检查可用内存和系统提交量。不足记录 BLOCKED_RESOURCE，继续其他无依赖检查。
5. 真实视觉模型不可用须 BLOCKED；Mock 仅验证协议，不能替代实际视觉决策。禁止 qwen3.8-flash、qwen3.7-plus 及变体；不修改原模型设置。Ollama 保留、真实连接 SKIPPED。

最终实现与逐项结果见 acceptance-report.md；本文不是已通过声明。

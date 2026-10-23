# M4 全面修复验收

2026-10-23，PR [#20](https://github.com/yunfei00/local-coding-agent/pull/20)。基线 `0000914`。未跟踪 egg-info 原样保留，无数据清理/数据库重建。

| 分类 | 当前证据 |
| --- | --- |
| 初始完整基线 | check.py Errors=0；342 Python 总数，2 项平台不适用跳过；43 Desktop |
| 本机完整回归 | check.py Errors=0；350 Python 总数，348 通过、2 平台跳过；43 Desktop、类型检查、源码构建通过；validation-reports/20261023-211639-935007.json |
| 最终增量路由专项 | test_unified_chat_profiles.py 11 项通过；双 HTTP 连接、独立密钥、重名模型、Default/Thread 恢复、JPEG Observer、无重复附件、失效 Profile、缺 Key、Task Observer 预算和过期能力结果 |
| 截图单元边界 | test_desktop_capture_fallback.py 5 项通过，原始黑屏/暗色/前台/遮挡保护及只读页面 Document 不整页遮盖 |
| Windows 真 GUI 回归 | 原 M3 WinForms 及 M4 自主 GUI 修复用例通过；真实 UIA/点击/键入/滚动/截图/取消/进程清理。m3-windows-gui.json、m4-autonomous-gui.json；仅模型决策 Mock |
| 实际 JPEG HTTP | M3 真实 WinForms 截图经原 OpenAI Compatible Client 到本机 aiohttp，核对 JPEG、模型和 Authorization；非路径、非 OCR |
| 系统计算器 | 产品 PrintWindow_client，480×799、DPI144、原始有效、零遮盖；仅本机保存，不上传 |
| Windows 记事本 | 产品 PrintWindow_client，1422×720、DPI144、原始有效，编辑区遮盖比例 0.7889；仅本机保存，不查看或发送被遮盖内容 |
| Electron 产品捕获 | Windows 可见窗口经产品枚举/聚焦/截图通过，PrintWindow_client，1478×919，原始有效；m4-electron-window.json；不是 webContents.capturePage 冒充 Windows 截图 |
| UI 烟测 | 最终 30 项通过、0 跳过；m4-complete-desktop-visible-gate.log / desktop-smoke.json，包含真实 Electron 产品捕获、无歧义旧 Thread 的加载竞态回归 |
| 凭据/隐私扫描 | credential_scan.py 通过；只提交代码和无敏感文档，截图/本地日志不提交 |
| 双平台最终门禁 | [PR #20 checks](https://github.com/yunfei00/local-coding-agent/pull/20/checks)；最终提交必须全部通过才合并 |

最终代码包含晚于首次完整回归的增强，不把旧完整回归冒充最终结果。最终提交由 Windows/Ubuntu CI 在干净环境重新运行全部测试，合并记录附最终检查结果。

最终门禁已完成：head 9e5fd20，本机 check.py Errors=0（354 Python：352 通过、2 平台跳过；44 Vitest；类型检查和源码构建通过），报告 20261023-232447-811400；desktop-smoke 30 通过、0 跳过，包含原生截图与本地预览 IPC。Windows/Ubuntu [CI 39978469791](https://github.com/yunfei00/local-coding-agent/actions/runs/39978469791) 均成功，PR #20 合并 main 921fdd950da368d6d5f587e31071ec3641389844。

## 本轮真实模型边界

无付费调用授权，没有读取或索取 Key。真实在线模型推理 **NOT RUN**。百炼 qwen3.8-flash Configuration/Connection/Text/Vision/Tools PASS 与 executor_bound=true 仅为用户历史结果。

HTTP Mock 证明路由、协议、预算和程序闭环，不能证明真实强模型自主选择这些修复。真实 Windows GUI 证明系统工具和独立断言，不能替代在线推理验收。

## 环境与兼容边界

补充门禁发现并修复两项测试环境问题：干净 uv 环境执行截图脚本时缺少项目导入路径；坐标测试窗口被其他桌面窗口遮挡。脚本明确加入仓库路径，测试仅将自有窗口置前，生产遮挡检查保持拒绝。另补应用内截图预览：仅允许当前应用数据目录下受限命名、32MiB 内的 PNG，拒绝任意文件路径；预览不发送模型请求。烟测从真实 Electron 捕获结果经 IPC 读取预览。

旧烟测以 offscreen 启动，只证明 Renderer 图像。本轮增加可见受控窗口，才验证真实 HWND。测试只调整自己窗口位置/大小/置顶并恢复；没有关闭遮挡、权限、隐私、锁屏保护。被遮挡/越界的检查明确失败，未计成功。

聚焦获准且未被遮挡才允许前台回退；UIA 安全容量、锁屏、UAC、跨用户窗口保护保留。不能推断旧裸 Model ID 从未保存的连接历史；歧义时保留记录并要求重选。

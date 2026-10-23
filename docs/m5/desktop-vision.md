# M5 桌面与视觉

顺序为：受管理 npm start → 真实 Electron main/renderer → 按精确标题和进程 Job 归属查窗 → UIA → Settings/输入/Save → 独立状态断言 → 产品 Windows API 截图。

截图保留 capture_method、原始有效性、DPI、尺寸、遮盖比例、artifact_id、sha256、窗口代次。Edit 和敏感区域继续遮盖；只读 Chromium 页面 Document 不整页覆盖。PrintWindow 无效时仅允许无覆盖、前台且完整在屏幕内的回退。锁屏/UAC/其他用户会话不能操作。

授权图片先由原客户端转换 JPEG，经过真实 HTTP 到指定 Observer；代码执行模型收到不可信观察文字，Observer 无工具权限。独立 GUI 最终判定仍由真实控件断言作出，观察文字不能覆盖失败。

Task → Screenshot artifacts 可查看失败轮与成功轮截图；工具卡也可 View local screenshot。读取仅允许应用数据目录中受限命名的 PNG（32MiB 内），任意路径拒绝。预览不会发送模型请求，上传继续需要单独审批。所有像素只留本机，不进入 Git/CI 产物。

Stop/Pause 取消 worker 和模型请求并关闭 Job；再 Resume 时重新启动应用和枚举窗口。固定 fixture 的 alwaysOnTop 仅隔离自身窗口，并未关闭生产遮挡保护。

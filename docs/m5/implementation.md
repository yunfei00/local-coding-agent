# M5 实施

固定工程 manual-fixtures/m5-electron-e2e 使用锁定 Electron/React/TypeScript/Vite/Vitest。sandbox、contextIsolation 开启，nodeIntegration 关闭，preload 只提供普通姓名 load/save。运行状态保存在 .runtime，源码不含凭据。

新增 TaskEvidence 从后台已持久化 transitions、verification_history 渲染可折叠 Timeline 和截图产物入口；保留失败轮次，预览只读取本地产物，不触发图片上传。原 Model call journal、终端工具卡、Diff 和 Stop/Resume 继续使用。

验收保护扩展至 package.json 的 start/prestart/poststart、pretypecheck/posttypecheck；不存在的钩子也冻结，不能通过新增生命周期脚本改换入口。冻结 GUI 契约使用 npm start 时不能被改换入口。篡改触发 ACCEPTANCE_CONTRACT_CHANGED，暂停且不执行被改变的测试。

真实 Electron 用例发现 Chromium UIA SetValue 可绕过 React 输入事件并回滚。Chrome_WidgetWin 的精确 Edit 改用经过 UIA ValuePattern、非只读、非敏感、精确 RuntimeId 焦点和前台身份校验的单批 Unicode SendInput；所有按键平衡释放，之后通过 ValuePattern 验证，不使用剪贴板或盲打回退。原生 Edit 仍使用 SetValue。输入仍脱敏，不写入日志。

成功桌面操作后仅允许刷新只读观察计数；不重置动作次数、短循环或总体请求/时间限制，避免第三次必要 inspect 被当成无进展循环。相关守卫测试同时确认重复点击仍受限制。

Save 不降低危险操作规则；GUI 契约和 Mock 决策显式请求 confirm_risk，并由原 Approval 获得一次授权。

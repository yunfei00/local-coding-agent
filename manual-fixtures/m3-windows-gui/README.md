# M3 Windows GUI 故障/交互验收程序

Windows 10/11 当前已解锁用户会话，使用系统 WinForms，不依赖 API Key 或安装包：

```powershell
powershell.exe -NoProfile -STA -File app.ps1 -StatePath "$env:TEMP\m3-fixture.json"
```

Settings 启用输入框；Ctrl+K 更新状态；滚动区域有 40 行；Wait for ready 异步更新状态。Delete record 仅更新计数，用于验证风险审批；密码框为空，用于验证拒绝操作和截图遮盖。状态文件由真实 WinForms 控件事件生成，只包含测试数据。测试通过 M2 进程管理启动并清理，不控制用户其他程序。

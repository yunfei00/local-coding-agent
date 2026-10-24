# Windows 本机原生验收阻断记录

日期：2026-10-24。分支：`feature/real-online-agent-validation`，PR：[22](https://github.com/yunfei00/local-coding-agent/pull/22)。本记录区分已观测事实和推断，不指定未经证实的驱动责任，不执行系统修复、重启或无关进程终止。

## 已观测证据

| 来源 | 观测值 | 含义与边界 |
| --- | --- | --- |
| GlobalMemoryStatusEx | 总物理内存 16,106 MB，使用率 99%，可用 88 MB | 当时的物理内存压力，不是 API Token 预算 |
| Win32_PerfFormattedData_PerfOS_Memory | PoolNonpagedBytes 13,287,026,688（约 12.37 GiB） | 巨量非分页内核池，普通应用工作集无法说明该占用 |
| 同一计数器后续复查 | AvailableMBytes 24，PoolNonpagedBytes 13,287,399,424 | 异常仍持续；读数随时间变化 |
| 只读 SystemPoolTagInformation | 3,856 个 tag；统计非分页池约 11,481.2 MiB | 与性能计数器采样时点/范围不同，不能强行相等 |
| 上述 tag 中 NtFC | 10,771,627,984 字节，约 10,272.62 MiB，30,601,216 个未释放分配 | 最大分配标签；尚未验证具体驱动/调用路径，不能仅靠标签断言责任 |
| Ollama /api/ps | 没有已加载模型；相关普通进程工作集仅约 6 MB / 0 MB | 没有证据说明已加载的 Ollama 模型占满内存，没有卸载/停止该服务 |

只读采样未读取用户文件内容、密钥或内核地址。完整本机摘要保存在忽略目录 `validation-reports/windows-kernel-pool-audit.json`。其中 `result: PASS` 仅表示采样成功，绝不是系统健康或业务验收通过。

[Microsoft PoolMon 文档](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/poolmon)说明 pool tag 可用于分析内核池分配及驱动使用模式；要确定责任需要更多驱动映射/时间趋势证据。本轮没有安装驱动工具、开启 Driver Verifier、改注册表、卸载驱动、关闭安全软件或停止其他服务。

## 原生停止证据

最新本机串行 M5 Electron + HTTP Mock 专项为失败，不产生真实 API 费用：

- `real-online-m5-owned-handle-termination.log`：308.024 秒；1 个测试 failure，另伴临时目录清理 error。
- 已核验当前 Job 内 9 个受控进程；1 次窗口关闭请求，3.453 秒优雅等待，之后终止 Job，并最多 30 秒确认进程实际退出。
- 34.672 秒后仍有两个原句柄未发退出信号，其 GetExitCodeProcess 已为 1；临时 Chromium profile 仍被锁定。额外 TerminateProcess 尝试返回错误 5，不能解释为缺少管理员权限并自行提权。
- 调整前后多次真实测试均保留失败，包括 10 秒和 30 秒确认期限；不能继续无限增大期限或忽略文件锁来让测试变绿。

[Microsoft 进程终止文档](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process)描述进程对象信号及内核等待等终止语义。产品仍以原进程句柄实际信号为确认，不单凭退出码/已发送终止请求声称进程树已退出。

巨大内核池与原生启动、输入和收尾迟缓同时存在，是恢复环境后应优先复验的方向；**尚未证明该异常是每个失败的唯一原因**。已确定的软件输入确认缺陷、上下文/错误传播缺陷另有代码和回归证据，详见[在线验收记录](real-online-agent-acceptance.md)。

## 独立 CI 与尚未完成事项

代码提交 `3582adf9243fec39b4f98f1b530dc8e89e742d87`：[CI 40071929862](https://github.com/yunfei00/local-coding-agent/actions/runs/40071929862) 全绿。

- Windows：396 项 Python，394 通过、2 跳过；3 项额外真实 Electron 专项通过；46 项前端通过；typecheck、build、desktop-smoke 通过。
- Ubuntu：396 项 Python，380 通过、16 跳过；46 项前端、typecheck、build 通过。
- CI 模型为 Mock。真实 Qwen Max 已修改文件并通过工程命令，但 Task 未完成独立验证；Max 视觉请求未发生。CI 不替代真实在线验收。

功能分支和报告保留，不合并 main，不发布、不建 Tag、不打包。用户预先存在的未跟踪 `local_coding_agent.egg-info/` 不清理。

## 安全恢复与继续验收

1. 先保存所有应用中的未保存内容。重启涉及其他应用状态，本轮开发授权不等于允许丢弃未保存工作；应由用户保存后手动重启，或明确授权已保存后的系统重启。
2. 重启后先只读采样：

   ```powershell
   Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory | Select-Object AvailableMBytes,PoolNonpagedBytes
   git status -sb
   git log -1 --oneline
   ```

3. 不设未经验证的绝对健康阈值；确认巨量内核池是否消退，并观察空闲状态下是否快速重新增长。若持续，应交由设备管理员定位具体内核/驱动问题，不自动禁用安全软件或修改驱动。
4. 由 Agent 串行重跑 M5 真桌面 Mock 回归和完整 check.py。通过后，使用[在线验收当前命令](real-online-agent-acceptance.md#恢复后的当前命令)继续 `qwen3.8-max`。原会话调用账本不清零，不需要用户重新配置模型、追加预算或提供 Key。
5. 只有真实业务、独立验证、视觉观察与受控进程退出全部通过，才更新验收为 PASS，并执行后续代码审查/合并。若再失败，继续根据新证据修复，不把内存异常预设为最终答案。

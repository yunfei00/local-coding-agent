# M4 接口准备

M4 的业务范围尚需后续任务明确。按既有路线图“工作区审查与权限”的方向，M3 已提供可复用基础，不宣称 M4 功能已完成：

| 已有接口 | M4 可接入的工作 |
| --- | --- |
| 原 Task/Turn ID、执行日志和 ToolResult | 将桌面动作与代码修改、验证、Git Diff 放入同一不可变审查记录 |
| window_id + PID/创建时间/session/generation | 形成版本化 DesktopConsentRecord，明确有效期、窗口范围、动作与数据发送范围 |
| artifact_id/path/SHA256/时间/尺寸/DPI/vision_feedback | DesktopArtifactRef 与 WorkspaceSnapshot/ChangeSet 关联；审查时验证产物未被替换，设计有授权的本地预览/查询接口 |
| 原 ApprovalManager、风险新审批和上传独立范围 | 继续完善审批范围及过期规则、历史审计，而不另建桌面 Agent |
| M2 进程树/worker 取消、真实 fixture | 覆盖审查拒绝、取消、窗口换代、产物失效与重启恢复的自动化 |

窗口授权/句柄不跨轮次恢复，内存视觉附件结束即清除，本地产物保留；M4 如需跨轮次操作必须设计重新授权，不能复活旧授权。当前没有通用 task.artifacts 查询、本地图片预览服务、不可变产物数据库或 OS 沙箱。M4 应定义保留/清理策略与审查快照，不默认对外上传截图。

M3 验收与双平台 CI 通过后可启动 M4 的接口设计和实现。多显示器/DPI 硬件矩阵、自绘/GPU 应用适配、真实视觉模型质量仍是明确的后续验证项，不把一次 WinForms fixture 通过外推为任意桌面程序可靠性。

# Task 预算启动修复：测试结果

## 可复制命令

在仓库根目录 PowerShell 运行：

```powershell
uv sync --locked
uv run python -m unittest discover -s tests -p test_task_budget_start.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
git diff --check
```

`check.py` 完整运行 Python 回归、桌面类型检查、Vitest 和构建。desktop-smoke 运行真实 Electron/Renderer/Agent、隔离数据和本机 HTTP Mock，无外部收费请求。

## 新增覆盖

`tests/test_task_budget_start.py` 10 项：

- 在线连接和 Planner 已绑定、默认 30000 Token 下首次请求准入；4 次真实 HTTP Mock 调用，真实 Worktree 内修改 calculator.py、unittest 和 Diff 验证通过，原目录不被覆盖。可信 Usage 最终合计 480 Token。
- 明确零值的任务调用、任务 Token、全局调用、全局 Token，全部零 HTTP；字段、scope、limit=0、used=0、required>0 和 request_sent=false 可在持久诊断查询。
- Settings 更新后新 Task 使用最新策略、Planner、调用数/Token；旧 Task 恢复保留配置、角色、全局预算和快照时间。
- 第一次请求估算超出 Token 上限也拒绝，输出上限 32768 对任务 Token 30000 的情形有精确公式。
- 其他任务消耗全局额度时，新任务自身为零仍阻止，并区分全局已用 4、上限 4、本次需 1。
- 显式任务零值覆盖不能被非零 Settings 改写；相等的边界允许准入，下一次拒绝。
- 零、缺失、null 的 JSON 读写语义；嵌套字段覆盖和非法配置验证。

`taskConfigOverrides.test.ts` 4 项验证只提交真实字段变化、策略切换不重放缓存零预算/Planner、显式零覆盖和后续新 Task 覆盖保留。

Windows Electron 烟测增加真实 Settings 表单保存 API-only、在线角色和零调用；重新打开 Task 面板（正常 Settings 导航会关闭 Task）后验证具体拒绝。随后通过原设置 RPC 保存 6 次上限，保持零预算面板挂载，再用真实启动按钮验证缓存不会覆盖新设置、完整 API-only Mock 编码闭环。旧 Task 的零快照保持不变。该用例完成后恢复默认设置，避免污染原重启持久化检查。

## 结果记录

初始回归：247 Python 通过。新增预算专项：10 通过，0 失败。完整回归、桌面烟测及双平台 CI 的最终记录见下方追加结果。

| 最终本地检查 | 结果 | 本机证据（validation-reports，忽略入 Git） |
| --- | --- | --- |
| 完整 check.py | 257 Python、36 Desktop，0 失败；类型检查和构建通过 | 20261022-172650-901924.json / .log |
| 最终预算专项 | 10 通过，0 失败 | task-budget-targeted-final.log |
| Electron desktop-smoke | 25 检查通过，0 跳过 | task-budget-desktop-verified.log / desktop-smoke.json |
| compileall / git diff --check | 通过 | 命令退出码 0 |

完整 Python 回归包含原混合 Provider 19 项、v0.4 编排 23 项和 Planning HTTP 18 项；没有依赖真实模型或收费服务。Windows/Ubuntu GitHub CI 通过后才合并 main，最终 PR 检查链接随提交记录追加。

**真实 DeepSeek / 公司 API：NOT RUN。** 用户已明确删除临时凭据并安排公司口述验证。本轮没有请求凭据，没有付费请求，不把 Mock Usage 当成真实 API 计费。

首轮扩展烟测的新预算闭环成功，但原重启检查发现用例没有恢复它修改的默认绑定；已修复测试清理后重跑。没有把这次失败描述为产品验收通过。

第二轮将配置改为真实 Settings 表单时，暴露了测试假设错误：App 本来就会关闭 Task 面板，不能直接继续填面板输入。已补重新打开步骤，并明确区分正常导航与后台更新缓存的用例，没有将该假设保留为公司根因。

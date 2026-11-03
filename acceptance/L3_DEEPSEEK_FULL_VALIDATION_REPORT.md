# DeepSeek L3 全流程验收报告

## 结论：BLOCKED

2026-11-03，家用 Windows、Asia/Shanghai。指定分支 `test/agent-functional-validation`，远程核对基线为 `303e265848aeec75e1b2dae684e3b9c5b26c573e`。源码修复提交 `af5d534d97eb48e189458a3ad83a6d1346598937`，追加真实 WebSocket 回归提交 `14c6f105ce4d0b3895b796c379a7991bab8b1c9c`。只切换已有远程分支的本地跟踪分支，没有另起功能分支，没有合并 main、强推或删除用户任务。

关键外部阻断：已有在线 `deepseek-v4.1-flash` 在最小 Planner 准入测试返回 HTTP 403 / `OPENAI_COMPATIBLE_AUTH_FAILED`。共发送 1 次请求，终态 paused；未进入 Executor，未产生业务文件修改、单元测试或优惠券报告。`deepseek-flash`、`deepseek-v4-pro` 的既有配置缺少可用 OS 安全凭据，各请求 0 次。环境变量 DEEPSEEK_API_KEY/LCA_OPENAI_API_KEY 均未配置；只检查是否存在，没有读取密钥进提示词或报告。

因此真实优惠券 L3 **未运行/BLOCKED**，没有以计算器准入失败冒充优惠券验收、没有用其他厂商模型代替 DeepSeek、没有由 Codex 编写优惠券业务代码。服务端实际上下文能力未获验证，50,000 仅为本次客户端测试窗口，不是服务端规格。403 无准确 Usage，实际计费 Token/费用未知，保守预留保留在既有累计账本，未清零或退款。

## 环境及调用保护

Python 3.12.13、Electron 38.8.6。实际准入 Task `bac7837d-4b7a-4044-85db-78db59464e81`，Call `cade1ad2-74b0-4709-a52e-c152ca9595b6`，请求模型 deepseek-v4.1-flash（服务端没有成功返回模型身份）。官方 api.deepseek.com 配置无安全凭据；唯一发出的请求走已保存的阿里 MAAS 网关，返回 403。未把阿里密钥发往官方 DeepSeek 域名，也不能断言是密钥失效还是模型/额度授权问题。预留 6,652 Token 为估算，包含未生成的输出预留，不是实际 Usage。

uv 0.11.2、Node v24.14.0，Python 使用 `uv run --locked` 项目环境。依赖 `uv sync --locked` 成功。真实请求走已保存 OpenAI-compatible 连接和 Electron OS 安全凭据同步。单请求 60 秒；单次准入最多 12 请求/60,000 Token，沿用已有累计会话账本；鉴权失败不自动重试、不自动提额。完整日志只在被 Git 忽略的 validation-reports，密钥、完整 Prompt、业务正文、原始截图不入报告。

## 根因与修复

1. `agent/core/task_diagnostics.py`：末尾 return 被字面量 `\\n` 留在 Python 注释中，函数实际返回 None，破坏诊断查询。恢复真实返回语句；保持兼容的 JSON 字段，但调用/状态/执行数组分别只返回最近 8 条；完整脱敏历史仍写磁盘 JSON。Markdown 当前问题使用紧凑序列化，避免漂亮打印数组撑成数百/数千行。
2. `agent/server/main.py`：重复操作入口虽跳过 running 日志，结果回写仍无条件追加失败日志并写 recovery；造成已拦截的重放污染已有执行证据。结果回写也检查 not replay。不可重复修改仍被阻止；不改成忽略失败或伪造成功。
3. `desktop/electron/main.ts`：WebSocket 关闭只更新 error，无重连。增加最多 8 次、1～10 秒退避重连，排除旧 Socket 的迟到 close 回调；不重发旧请求、不自动启动任务。`AutonomousTaskPanel.tsx` 在 connection.restored 后重新 task.list，继续使用 revision 合并，避免旧 Blocked 缓存覆盖真实状态。
4. 已有 Completed 单调保护、真实证据门禁、只读命令安全重跑、错误/Diff/计划状态指纹、有界失败上下文及环境错误暂停逻辑已审计，继续复用，不另建状态机、不增加执行循环上限。本次没有证据证明公司原任务的 87 次恢复已在真实 DeepSeek 下收敛，不能宣称全部历史问题已经解决。

后续回归发现并修复：

- `agent/task_plans.py`：uv --locked、uv run pytest、git diff --check 被误归为不可重复修改；现在允许这些明确验证命令，复合 Shell、任意 Python 修改脚本、git --output 等仍不能按只读重跑。
- `agent/core/orchestration.py`：历史压缩丢弃截图身份，原 M5 断言真实失败；保留有界 tool/ok/path/artifact_id/sha256、退出码与日志路径，完整验证结果脱敏后写入独立 attempt 时间戳 JSON，不删除旧归档。
- 同文件压缩失败反馈时丢弃视觉 Observer 的具体 errors，原 M4 修复模型缺少原因并暂停；现在保留最多 3 条、每条 300 字符的视觉错误，仍受整体失败上下文上限约束。原有 M4 GUI 7 项、M5 Electron 3 项复测通过，未弱化断言。
- `task_diagnostics.py`：原导出遗漏 MODEL_CONTEXT_LIMIT 的 context 组成；现在与 API budget 独立显示并保留数值类型。单测用 58,416/50,000 验证窗口、请求估算、输出预留、request_sent=false；这些是回归测试数据，不冒充本次服务端实际限制。

对应后续源码提交 d91f709、a50192a、bf60dda；最终源码验收对象 `bf60ddaacf6f8faaa2c62fc4e8623db1a9e47d4b`。

## 已完成的针对性回归

| 命令（均在仓库根目录） | 结果 | 日志 |
| --- | --- | --- |
| uv run --locked python -m unittest discover -s tests -p test_planning_api.py -v | 18 PASS / exit 0 | validation-reports/20261103-planning.log |
| uv run --locked python -m unittest discover -s tests -p test_task_plans.py -v | 6 PASS / exit 0 | validation-reports/20261103-state.log |
| uv run --locked python -m unittest discover -s tests -p test_execution_recovery.py -v | 修复前 17 PASS/1 FAIL；修复后 18 PASS / exit 0 | validation-reports/20261103-recovery-fixed.log |
| uv run --locked python -m unittest discover -s tests -p test_api_context_fit.py -v | 10 PASS / exit 0 | validation-reports/20261103-context.log |
| uv run --locked python -m unittest discover -s tests -p test_l3_diagnostic_transport.py -v | 3 PASS / exit 0 | validation-reports/20261103-diagnostic-transport.log |
| npm.cmd --prefix desktop run typecheck | PASS / exit 0 | 本次工具输出 |
| npm.cmd --prefix desktop run test | 50 PASS / exit 0 | 本次工具输出 |
| npm.cmd --prefix desktop run build | PASS / exit 0，保留 bundle 大小 warning | 本次工具输出 |
| uv run --locked python scripts/validation/credential_scan.py | 392 文件、0 findings / exit 0 | 本次工具输出 |

以上不是独立用例总数，完整回归会包含这些用例，不重复累计。

## WebSocket、诊断及历史

新增测试实际启动 aiohttp WebSocket，连接、查询、断开、重连、再次查询同一持久 Task，状态/id 一致且 API calls=0，没有改数据库来伪造 Completed。该测试覆盖后端重连同步，真实 Electron 故障注入另见下一段。

收尾追加真实 Electron 故障注入已通过：在隔离桌面验收进程中，按唯一 Agent 端口识别并断开该进程自有 TCP 连接；不读取 token、不改防火墙。等待真实 connection.restored 事件后重新读取任务，状态 awaiting_approval、步骤与用量完全一致，模型请求增量 0，Composer 可用。加入此检查后的桌面烟测 **50 PASS、0 SKIP**，日志 validation-reports/20261103-l3-reconnect-smoke-final.log。运行中付费 DeepSeek 流式任务断线恢复仍未验收。首次控制器错误地使用异步 waitForFunction 提前返回，已改为等待同步事件标志，未放宽产品检查。

诊断专项构造 2000 次调用/状态/执行历史，重复导出 3 次；完整 JSON 仍有 2000 调用，线上各数组最多 8 条，响应低于 20,000 字符，Markdown 低于 100 行，命令/退出码/当前未完成步骤可见，已知秘密已脱敏。完整历史未删除；文件以临时文件原子替换快照，原始持久账本保留。不自动清理用户旧诊断文件。实际长期磁盘占用/轮转策略仍需单独观察。

## L2、真实 L3 及最终步骤

`uv run --locked python acceptance/feature_l2.py --verify` 返回 exit 1：Run --setup first，本机没有已完成的 workspace_l2。未在原路径运行 setup 覆盖数据，未由 Codex 实现该业务功能。框架 L2 兼容性以既有工程工具/恢复/全量回归为依据；该手工 fixture 的业务验收不能标 PASS。

优惠券任务的固定金额、百分比、门槛、上限、有效期、不可叠加、无效输入、单测、中文报告及完整计划状态均 NOT RUN。最小准入任务的占位计划未完成，状态 paused；没有将开发完成与验收通过混为一谈。真实完整请求日志路径：validation-reports/20261103-deepseek-live.json；另外两次安全凭据检查见同目录 deepseek-flash-live / deepseek-pro-live JSON。

## 全量、CI、Git 与建议

全量命令 `uv run --locked python scripts/validation/check.py`，首轮日志 validation-reports/20261103-l3-full.log。早期失败 CI 41619920277、41621098944 的问题均按实际断言修复；没有删除或跳过关键测试。最终双平台结果见下方。

`git diff --check` 通过。无安装包、Tag、Release、main 合并。由于真实 DeepSeek 关键准入不通过，**不建议合并 main**；需要有效的服务商访问权限后，重新通过真实自主任务入口执行优惠券场景、独立验收及中断恢复，才能改判。现有修复和离线结果不能替代该条件。

## 收尾复测记录

- 原始基线完整运行 458 项，422 PASS / 3 FAIL / 31 ERROR / 2 SKIP，exit 1，日志 validation-reports/20261103-182108-324554.log。没有将其称为通过。
- 第二轮完整回归只剩 M4 视觉错误反馈丢失导致的暂停，exit 1，日志 validation-reports/20261103-183706-985508.log。修复后 M4 GUI 套件 7 PASS / exit 0，M5 Electron 3 PASS / exit 0，分别见 20261103-observer-fixed.log、20261103-m5-fixed.log。
- 本机收尾 `uv run --locked python scripts/validation/check.py` **Errors=0 / exit 0**：461 Python 项，459 PASS / 2 平台 SKIP / 0 FAIL；frontend 50 PASS，typecheck/build PASS，完整日志 validation-reports/20261103-185516-056941.log，摘要同名 JSON。最后的上下文诊断字段修复另有 3 项专项通过；精确最终源码以 CI 提交为准。
- v0.3 运行时专项 10 PASS，日志 validation-reports/20261103-v03-fixed.log；恢复最终专项 18 PASS，日志 20261103-recovery-final.log；诊断/真实 WebSocket/只读命令专项 3 PASS，日志 20261103-diagnostic-transport.log。
- 原桌面烟测因界面已中文化而仍定位英文按钮失败，exit 1，日志 20261103-l3-desktop-smoke.log。只同步定位文字，没有删除点击、状态、取消、诊断断言；复测 49 PASS，追加真实重连后 50 PASS。
- 所有模型决策替身测试明确属于 Mock + 实际文件/进程/GUI/HTTP 工具，不算真实 DeepSeek 推理成功。没有把重复执行次数相加成不同用例数。
- 验证脚本同步提交 dc068c8；加入真实 Electron Socket 中断检查的验收提交 `b799768f666d0127510f1ee4a6625976591aa0bd`，最终 CI 跟踪：https://github.com/yunfei00/local-coding-agent/actions/runs/41627823155 。报告提交只补中文证据，不改变产品代码或关键测试。

## 最终 CI 与交付边界（2026-11-03 19:45 北京时间）

验收提交 b799768 的 CI 529 **Windows / Ubuntu 全部成功**：

| 门禁 | 真实结果 |
| --- | --- |
| Windows Python | 461 项：459 PASS / 2 平台 SKIP / 0 FAIL；581.112 秒 |
| Windows 独立 M5 Electron | 3 PASS；130.429 秒，另已包含在全量中，不重复计为新用例 |
| Ubuntu Python | 461 项：445 PASS / 16 平台 SKIP / 0 FAIL；257.057 秒 |
| 两平台前端 | 各 50 PASS；typecheck、build 均 PASS |
| Windows 实际桌面烟测 | 50 PASS / 0 FAIL / 0 SKIP，包含真实 Socket 中断、自动重连与预算不变 |
| 本机最终凭据扫描 | 393 文件 / 0 findings；属于可用规则扫描，不是任意凭据格式的绝对证明 |

已知边界：真实优惠券九项需求、真实模型修复失败、真实模型中断恢复、服务端上下文上限未验。旧版本已经丢弃的历史字段不做虚构回填，原日志/数据库保留；新的完整验证归档从修复后开始产生。未运行 fixture 的 L2 业务验收不标 PASS。一次从 tests 子目录直接点名单个 M4 测试因根路径不在 sys.path 而导入失败，已改为仓库根目录的 uv unittest discover，M4 7 项通过，不据此误报依赖缺失。

最终只提交本报告收尾；产品代码与验收脚本保持 b799768 不变。报告提交后的 CI 若重新触发，应与上表已完成的源码验收区分，不把排队状态虚报为成功。完整产品验收结论保持 **BLOCKED**，不合并 main、不发布。

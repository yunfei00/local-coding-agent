# Unified Agent Runtime 开发与验收报告

日期：2026-11-04；环境：Windows 11、16 GB RAM、uv Python 3.12、Node/Electron/React/TypeScript 项目锁定依赖。基础 main：`489157e197f63c57db2af827610e3010e0f3f9ab`。开发分支：`feature/unified-agent-runtime`。PR：[#28](https://github.com/yunfei00/local-coding-agent/pull/28)。未合并 main，未创建 Tag、Release 或安装包。

> 最终结论：**PARTIAL**。统一入口、自动验证、持久化计划、恢复、预算及全量自动化已验证；两款允许模型的真实完整套件均 9/10 通过。指定优惠券用例仍有请求超时，后续四款允许模型新请求均 HTTP 403，因此不能宣称全部在线验收通过。PR 保持草稿，暂不建议合并 main。

最终产品源码：`f9eab339cdeb0774e75425eab38911b6fbf878b4`；此后提交仅改进独立验收控制器、汇总文档和脱敏证据，产品代码未变。最终分支 Commit 由 [PR head](https://github.com/yunfei00/local-coding-agent/pull/28) 标识。未修改用户原有两个未跟踪目录。

## 实现及审查结论

主聊天已取消模式选择。直接问答不建立计划、不发送工具；分析用真实读取/只读检查并拒绝修改；简单修改直接执行工具；复杂开发由 native `agent_plan` 和实际文件/工具证据升级为原持久化计划。没有新建第二套 Agent Loop、Provider 或任务状态机。

修改后程序复用 VerificationEngine 自动独立验证，命令仍经过原权限/审批。显式工程配置优先，按实际 Python、受影响前端包和可用类型检查发现命令；找不到能力时明确 Unverified/Manual。中间计划步骤只做 Basic，末步骤独立运行最终检查。代码/断言错误有限修复，环境错误停止，已完成步骤不回退。

同页显示文件、真实验证、复杂计划、停止/恢复及当前诊断。重新连接重新同步后端真实状态。高级 Task 的 Worktree、角色路由、追加需求、审批、接受报告和旧数据原地保留；统一入口默认当前工作区及 Chat 所选模型，不自动创建隔离 Worktree。

修复的实际缺陷：

1. 修改后原普通循环只提示模型验证，缺少程序独立检查。
2. 无步骤证据仍可能提前结束为部分完成；现在只补正一次，仍不足则明确 `PLAN_STEP_NO_EVIDENCE`，不能假完成。
3. Plan.get 自带 execution，直接写入 runtime.plan 会把账本再次嵌入自身；已移除该字段，保留独立账本，避免递归膨胀与 WS 大消息。
4. 只读诊断的失败 unittest 被误当成开发验收失败；现在保留失败命令/退出码为诊断证据，不宣称测试通过，权限/环境失败不被忽略。
5. Windows TEMP 的 8.3 路径别名和解析后的长路径不能直接 relative_to；先解析根目录。
6. 单次请求超时被错误报告成整个任务时间耗尽；现在保留具体 `MODEL_REQUEST_TIMEOUT` 和不确定 Usage 预留。
7. 统一请求纳入原任务/全局预算；新运行读取 Settings，恢复保留模型/预算快照。失败、中断不会清空累计记录。
8. WS 断开暂停并保存检查点，不再关闭服务拥有的 MCP 连接；界面不保留旧 running 状态。

## 核心文件

- `agent/core/unified_runtime.py`：请求约束、升级策略、变更元数据、验证选择、结果视图和脱敏诊断。
- `agent/server/main.py`：扩展原循环、native 计划、独立验证、有界修复、模型/预算快照及连接恢复。
- `agent/core/execution.py`、`budget.py`、`task_runtime.py`：复用账本、预留/结算及共享全局统计。
- `agent/core/orchestration.py`、`agent/task_plans.py`：兼容高级 Task、原计划追加和最新状态查询。
- `agent/core/verification.py`、`agent/llm/router.py`、`openai_compatible.py`：验证级别、清单解析、只记计数的流进度诊断。
- `desktop/src/App.tsx`、`UnifiedProgress.tsx`、`ModelSettingsSection.tsx`、Electron main/preload/类型：单入口及同页结果。
- `tests/test_unified_runtime.py`、`test_unified_contract.py`、Provider 和前端测试、`scripts/validation/desktop-smoke.cjs`：基础和桌面回归。
- `scripts/validation/unified_live.py/.cjs`、`unified_contract.py`：真实产品入口驱动与独立验收，不写被测业务实现。
- README、架构、公司使用/验证文档、本报告、用例和脱敏证据。

## 自动化与 L2/L3 回归

核心提交 `80a5d9f721342b69fca52028a072c6ec359bddb5` 的 [PR 双平台 CI](https://github.com/yunfei00/local-coding-agent/actions/runs/41776453187) 已通过：

| 检查 | 实际结果 |
| --- | --- |
| Windows Python | 517 总数，515 通过、2 跳过、0 失败 |
| Ubuntu Python | 517 总数，500 通过、17 跳过、0 失败；Windows 原生功能按平台跳过 |
| Windows 独立 M5 | 3 通过，真实受控 Electron 窗口，模型决策为 HTTP Mock |
| 前端 | 57 通过、0 失败；类型检查和构建通过 |
| 桌面 smoke | 52 通过、0 跳过，含统一 composer、真实 unittest/Diff、旧 Task/Worktree 续作、重启和诊断 |
| 密钥/私有产物扫描 | 通过；未提交运行数据库、密钥、截图和完整在线日志 |

此后补充的 Provider 流计数/脱敏断言及单请求超时预留断言，针对性 6 项通过；最终文档候选的状态由 [PR Checks](https://github.com/yunfei00/local-coding-agent/pull/28/checks) 提供，不把旧提交的绿色状态套到新提交。首次 Windows CI 确实因短路径错误失败，修复后上述 CI 通过；旧失败没有删除。基础回归覆盖原 L2/L3、MCP、Pinned Files、Git/Worktree、审批、重复操作、上下文、停止进程树、计划恢复及混合 Provider。

本机首轮完整回归：511 项中 506 通过、1 失败、2 错误、2 跳过。两项原生 GUI 报 `Windows did not grant focus; no input was sent`，第三项同一路径导致 Mock 流程暂停（`MODEL_CLIENT_ERROR`）；没有通过强行输入或删除测试掩盖。

最终聚合 `uv run --locked python scripts/validation/check.py` **PASS，Errors: 0**：Python 517 项（515 通过、2 跳过）、前端 57 项、类型检查和构建全部通过。本机日志 `validation-reports/20261104-125841-084879.log/.json`，Python 耗时 972.320 秒。最终单独桌面 smoke 52 项通过、0 跳过（`unified-desktop-smoke-final.log`）。初次焦点错误没有在最终完整回归复现。之后补充验收控制器 2 项防误判回归，5 项独立契约专项全部通过；新增 Runtime/独立断言最终共 45 项，连同原终端为 56 项，不把重复运行叠加成测试数量。最终 CI 的总数应包括这 2 项新增测试。

## 真实阿里云验证方式

从原安全存储通过生产 Electron 取凭据；Codex 未导出 Key。隔离配置、数据库和缺陷工程在本机忽略目录 `validation-reports/`，不改变用户已保存目录及业务工程。通过真实输入框提交，真实 Provider、原工具、真实文件、unittest 和 Diff；不是仅请求 API 回复文本。

模型发现使用原连接 GET 模型列表，发现结果不等于能力支持。候选 ID 必须来自实际返回列表；工具/JSON 参数能力由真实 native function call 探测。测试窗口 65536、输出 8192 是受控客户端配置，未确认 Provider 最大窗口。未测试视觉，不能将文本工具能力说成视觉验收。

收到禁用指令后，排除 `qwen3.7-plus`、`qwen3.8-flash` 及名称包含该 ID 的变体。之前已经发生的开发期调用单独保留，后续无新调用；最终验收只使用允许模型。

| 模型 | 已执行真实用例与结果 |
| --- | --- |
| qwen3.8-max、glm-5.3、deepseek-v4.1-flash、qwen3.8-omni-flash | 保存配置逐一探测 HTTP 403；暂时不可用，不判断为错误 Key 或框架失败 |
| kimi-k3、kimi/kimi-k3 | HTTP 400，未继续业务任务 |
| qwen3-coder-flash | 文本/native tools、问答和读取已通过；初次简单修改独立边界失败；后续复杂任务 HTTP 403 |
| qwen3.7-flash | 最新完整套件 9/10 通过，简单修改独立边界通过；优惠券 60 秒请求超时，单独 120 秒复测仍超时 |
| qwen3.8-27b | 完整套件 9/10 通过；优惠券原 60 秒超时，后续独立复测首请求 HTTP 403 |
| qwen3.6-flash、qwen3.5-flash | 文本/native tools 和问答/读取通过；初次简单修改未通过更严格的独立输入边界；后续优惠券首请求均 HTTP 403 |
| qwen3-omni-flash | 文本/native tools 和问答/读取通过；真实修改遇到 HTTP 429，未伪造完成 |
| qwen3-vl-plus、qwen-plus | 文本/native tools 和问答/读取通过；原断言保留并追加断言，但未通过 NaN/Inf 独立边界，不称为完整开发验收通过 |

开发期“analysis PASS”有旧控制器漏查运行时 failed 的问题。修复后完整套件同时要求后端 completed、真实读取、实际回答及工作区未变；旧记录在公开证据中保留真实 phase，不用旧 PASS 代替新版验收。

初版冻结整个原测试文件，误拒绝添加新方法；首次 AST 版本也误拒绝在原方法末尾增加断言。最终保留方法签名/装饰器及原语句前缀，允许追加断言，明确拒绝修改原断言、插入 early return 或 skip，并在独立进程运行冻结的原测试和输入边界。八款模型的原断言实际均保留；只有 qwen3.8-27b 的初次工程通过全部输入边界，其余仍失败，原因不是“新增测试”。原记录与最终重评分别保留。最早优惠券控制器的 PASS 被独立 12 项契约发现漏检负门槛，已撤销其最终 PASS 资格，不改原报告造成功。

## 最新真实用例与状态

| 用例 | qwen3.7-flash / qwen3.8-27b 最新完整套件 |
| --- | --- |
| 普通装饰器问答 | PASS，无工具/计划/文件修改 |
| 只读分析缺陷 | PASS，真实读取并给原因，失败测试作为诊断证据 |
| 加法与有限输入校验 | PASS，原断言保留，独立输入边界通过 |
| 优惠券多文件 | 原套件 FAIL，单次请求超时；独立复测见下文，不改成假 Completed |
| 缺失依赖 | PASS，等待用户，具体 environment、命令、退出码，无无限模型循环 |
| 真实失败测试修复 | PASS，实际修改、复测、Diff |
| 长历史 | PASS，确实裁剪历史，保留当前目标且不修改文件 |
| Stop 后恢复 | PASS，实际按钮停止，原 Completed ID 保持，剩余步骤和独立 unittest 完成 |
| WS 断开恢复 | PASS，仅断开受测应用拥有的 socket，后端 paused、重连、同页恢复并验证 |
| JSON/中文交付 | PASS，普通 JSON 不触发工具；开发交付由模型生成 |

Stop/WS 的复杂工程包含修复 calculator、创建 validation 模块、测试和中文交付文件，Agent 自己执行，全计划 Completed，实际最终独立验证通过。WS 测试在真实步骤 Completed 后断开，避免把尚无计划的只读分析称为计划恢复。计划建立前的问答/分析中断可重新发送，不伪称无计划也能逐步骤恢复。

每个运行诊断 Markdown 限制约 140 行，线上用例逐一验证本机 JSON 存在，完整历史不随 WS 传输、不删除。旧过大快照已修复新运行的递归来源。完整历史/原始日志留在本机；公开[脱敏结构化证据](evidence/unified-runtime-online.json)只含模型、状态、命令、退出码、计数，不含 Key、Prompt 或文件正文。

优惠券单项最终结果：qwen3.7-flash 在 60/120 秒均未完成单次响应；qwen3-coder-flash、qwen3.8-27b、qwen3.6-flash、qwen3.5-flash 的后续新请求均 403，未重试该模型或回退到用户禁止模型。403 不能据此确认是配额、权限还是服务可用性，也未要求用户重新配置 Key。所有在途调用已结束，保留实际错误和未知 Usage；未替 Agent 编写引擎来制造通过。

新流诊断只记事件数、首末事件时间、content/reasoning/tool-arguments 字符数，不保存这些内容。它用于后续区分响应仍在生成、流中断和迟迟未结束；本轮 403 的事件数为零，不能据此推断先前超时的内容。分批写入指令已加入，但受 403 阻断，未宣称它解决了真实优惠券超时。

## 请求、Token 与实际费用

真实测试每次均有有限累计调用、Token、单请求及总时长限制，不自动扩额或收费回退。完整套件每轮 100 次/1000 万 Token、请求 60 秒、单任务 600 秒；独立优惠券复测 45 次/500 万 Token、请求 120 秒、单任务 600 秒；整个驱动器硬停止 3900 秒。Provider 未返回真实费用且没有核实价格，费用为 UNKNOWN，不能保证或宣称免费。

| 运行 | 模型请求数 | 实际 Usage 或保守预留 Token | 说明 |
| --- | --- | --- | --- |
| 初期开发探测 | 58 | 596249 | 包含禁用指令前调用；旧 estimated 标记未包含失败能力探测，不是全量精确 Usage |
| 允许模型批量测试 | 160 | 1240026 | 含未知预留；达到累计限额后后续用例明确 BLOCKED |
| qwen3.7-flash 首次最终套件 | 51 | 565654 | 从持久化账本恢复，2 次统计不确定；该旧控制器 WS 早于建计划，报告 BLOCKED |
| qwen3.8-27b 完整套件 | 46 | 383691 | 含请求超时的不确定预留 |
| qwen3.7-flash 修复后完整套件 | 55 | 541715 | 9 PASS、1 超时；含不确定预留 |
| qwen3.7-flash 120 秒单项 | 4 | 53546 | 超时，未知 Usage 保留预留 |
| 四款允许模型后续单项 | 每款 1 | 25564 / 25562 / 25572 / 25572 | 依次 coder / 27b / 3.6 / 3.5，均 403；这是预留，不是实际消费声明 |

精确 Provider 输入/输出与未知请求分别公布；失败/取消保守预留不是声称实际消费了这些 Token。恢复预算不清零；新增 API 请求前检查任务及全局调用/Token/费用，没有通过增加默认额度解决故障。

## 使用、边界及合并判断

源码安装、配置、真实验收命令见[公司验证](../docs/v0.4/company-validation.md)和[测试用例](UNIFIED_AGENT_RUNTIME_TEST_CASES.md)。完整退出旧版本后同步功能分支，`uv sync --locked`、`npm.cmd --prefix desktop ci`、`npm.cmd --prefix desktop run dev`。保存的模型和安全凭据继续使用，不需要清空历史或重新填写 Key。

边界：统一入口不自动隔离 Worktree；不支持运行中消息排队/实时引导；Basic 不等于完整回归；没有测试能力时不能 Verified；Provider 费用/最大上下文未知；可用模型及配额随服务变化；本机原生输入仍受 Windows 焦点保护。高级 Worktree/多角色使用原 Task，不自动提交/推送/合并。

交付结论：源码、文档、回归和两款模型的 9 项实际用例已完成；优惠券完整在线用例仍未通过，影响本次“全部真实用例通过”的标准。PR 保持草稿，暂不建议合并。后续应在允许模型服务可用时仅复测该用例，仍须保留有限请求/时间和原契约，不能只放大预算或跳过测试。

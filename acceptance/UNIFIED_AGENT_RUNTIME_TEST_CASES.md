# Unified Agent Runtime 测试用例

测试入口：生产 Electron IPC 和主聊天输入框；Python 基础回归不需要付费 API。验收工程在忽略目录 `validation-reports/` 下独立初始化，不改用户工程。控制器只准备缺陷基线和外部验收，不替 Agent 实现业务代码。

## 自动化回归

| 范围 | 断言与证据 |
| --- | --- |
| 任务识别 | 问答不创建计划、不提供工具；只读分析拒绝模型编造的写入；实际读写与 native agent_plan 决定升级 |
| 自动验证 | 模型只编辑而不运行测试时，程序真实执行 unittest/Diff；失败提供错误并有限修复；测试缺依赖直接等待用户 |
| 范围选择 | 无测试能力不发明命令；TS 缺类型检查能力不假通过；相邻 package 发现；目录/文件名不能插入 Shell 命令 |
| 生命周期 | 原 Completed 与执行证据保留；简单任务升级；Stop 与恢复不重复副作用；未恢复计划允许问答但不允许绕过确认修改 |
| 快照与预算 | 新运行读取 Settings、旧运行保留；零调用/Token/未知价格费用上限阻止请求；两种入口共用全局账本 |
| 连接与诊断 | 原生 WS 中断保存 paused、清空 active IDs、保留 MCP；重连从持久化加载；诊断约 140 行内且 JSON 保留完整脱敏证据 |
| 原有功能 | 全量 L2/L3、Worktree、审批、MCP、Pinned Context、进程树、上下文和桌面 M5 测试 |
| 界面 | 桌面 smoke 真实发送问答/复杂计划/同页续作、自动测试、诊断及重启，无模式选择；原高级 Task/Worktree 续作契约不删 |

```powershell
uv sync --locked
npm.cmd --prefix desktop ci --no-audit --no-fund
uv run --locked python -m unittest discover -s tests -p "test_unified*.py" -v
$env:LCA_REQUIRE_INTERACTIVE_DESKTOP = "1"
uv run --locked python -m unittest discover -s tests -v
npm.cmd --prefix desktop run typecheck
npm.cmd --prefix desktop test
npm.cmd --prefix desktop run build
node scripts/validation/desktop-smoke.cjs
uv run --locked python scripts/validation/credential_scan.py
git diff --check
```

`scripts/validation/check.py` 是上述 Python/前端检查的聚合入口，不包含真实在线调用。Windows 原生桌面测试需要已解锁的交互桌面；Ubuntu 不支持的 Windows 原生用例明确跳过，不能当作通过。

## 真实阿里云用例

| 用例 | 外部验收要求 |
| --- | --- |
| 概念问答 | 解释装饰器，无文件变化、工具和复杂计划 |
| 代码分析 | 读取有缺陷的 calculator，定位减法/加法错误，无修改 |
| 简单修改 | 增加有限数字校验、拒绝 bool/字符串/None/NaN/Inf，保留原断言，新增测试，独立检查 |
| 优惠券多文件 | Agent 自己规划与实现 fixed/percent/min_spend/max_discount/expires/不可叠加/非法输入，真实测试、Diff、中文交付 |
| 测试失败修复 | 修复真实失败的 calculator unittest，实际重测 |
| 环境失败 | 缺失依赖，程序显示 environment 与命令，不无限循环 |
| 上下文压力 | 预置合成历史，确实发生裁剪，同时读取当前文件、保持只读 |
| 中断恢复 | 第一阶段 Completed 后实际点击 Stop，恢复保持原 Completed ID，完成剩余内容 |
| WS 重连 | 仅断开受测应用拥有的 WS，确认 restored、真实 paused，同页恢复 |
| 交付与 JSON | 中文交付文件和真实测试一致，普通 JSON 回复不错误触发工具计划 |

先执行不带 `--live` 的清单检查；实际联网必须显式指定 `--live`，由 Electron 从现有安全存储读取 Key，不在命令行传密钥。费用信息未知则报告 UNKNOWN，不把“免费额度”当作软件可保证的费用上限。

```powershell
uv run --locked python scripts/validation/unified_live.py
uv run --locked python scripts/validation/unified_live.py --live --discover-only --exclude-model qwen3.7-plus --exclude-model qwen3.8-flash --output validation-reports/unified-discovery-new
# 候选 ID 必须来自上一步真实发现结果；以下模型按本轮证据选择，不保证以后仍可用。
uv run --locked python scripts/validation/unified_live.py --live --suite --candidate-model qwen3.7-flash --only-model qwen3.7-flash --discovery-report validation-reports/unified-discovery-new/report.json --exclude-model qwen3.7-plus --exclude-model qwen3.8-flash --max-calls 100 --max-tokens 10000000 --output validation-reports/unified-live-new
```

默认单请求 60 秒、单运行 600 秒、整个控制器 3900 秒，累计请求/Token 上限在发送前检查。必要时可显式设置 `--request-seconds 120`（硬范围 1～180 秒），不自动扩额；用 `--suite --case coupon` 只复测失败用例，避免重新消耗全部用例。两款用户禁止的模型及名称包含该 ID 的变体均排除；没有静默切换收费模型。

计算器外部检查保留原 AST 断言、方法签名/装饰器及原语句前缀，允许新增方法或在原方法末尾追加断言，拒绝 early return、skip 或原断言改变；并在独立进程中执行冻结的原测试及输入边界契约，避免将“新增测试”误判成破坏测试。优惠券另有固定 12 项外部契约；控制器同时固定验证配置及契约文件哈希，不能削弱后宣称通过。详细 PASS/FAIL/BLOCKED 以最终报告和原始 JSON 为准。

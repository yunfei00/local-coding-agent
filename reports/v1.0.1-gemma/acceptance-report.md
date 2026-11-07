# Gemma 真实验收复测

- 基线为 Windows x64 正式版 v1.0.0（`445d4ed`）及分支验收提交 `6821392`。
- 模型为 `gemma4:31b`，经已配置的 Ollama 原生接口和 Local Coding Agent WebSocket 入口执行。只读取模型配置，无生产数据写入。
- 源码和冻结版各用独立的绝对数据目录。原 21 轮保持 7 个计分项 × 3 次，视觉理解与桌面操作独立计分。各轮保留 8,192 上下文、1,024 单次输出预留和 18 个模型步骤。原用例与断言保持不变。
- 原生记事本对照只证明 Windows 工具能力，单独列示，不给 Gemma 加分。

## 修复与证据

| 范围 | 根因或处理 |
| --- | --- |
| 截断 | 真机账本出现 HTTP 200、`finish_reason=length`、输出达到 1,024。旧恢复条件在已有缓冲工具时跳过重试，即使这些调用尚未派发。现在完成帧先保留终止原因和用量，截断批次整体丢弃，使用同一模型在原重试次数与任务预算内重新生成。先前已执行操作继续保留。 |
| 空响应和诊断 | 空响应进入同一有界恢复机制。Ollama 超时和连接异常分开记录，账本派生可检索的失败类别，无请求正文或凭据。 |
| 无 Git | 保留已有修复。只有真正的 Git 工作树才添加 Git 差异验证，普通项目仍执行实际测试。 |
| 修改意图 | 补充中英文明确修复请求和显式只读覆盖的回归。权限由现有后端独立执行。 |
| 数据目录 | 相对 `LCA_DATA_DIR` 曾按安装版后端当前工作目录解析，导致试验数据库写进安装树。显式路径现在必须是绝对路径，默认数据位置延续现有行为。 |

安装目录下原有的 `resources\agent\build\ollama-pilot` 保留。此前只读检查显示试验库没有工程、会话或消息，清理动作被自动审批策略拦截。若需要清理，可在应用关闭后确认路径与文件占用，仅处理该试验子目录。

## 复现命令

```powershell
uv run --locked --with 'pytest==9.2.0' python -m scripts.validation.local_ollama_benchmark --source --model gemma4:31b --output build/gemma-retest
uv run --locked --with 'pytest==9.2.0' python -m scripts.validation.local_ollama_benchmark --source --model gemma4:31b --case P1 --case P2 --case P3 --repeat 1 --output build/gemma-projects
uv run --locked --with 'pytest==9.2.0' python -m scripts.validation.local_ollama_benchmark --source --model gemma4:31b --case R --case N --repeat 1 --output build/gemma-lifecycle
uv run --locked python scripts/validation/computer_native.py --scenario notepad --gemma-notepad-fixture --output build/gemma-notepad-native
```

每个输出目录应尚不存在。Windows 桌面测试需要已解锁的交互会话，测试记事本需要没有其他记事本实例。

## 原有用例汇总

| 能力 | PASS | FAIL | BLOCKED | 成功率 |
| --- | ---: | ---: | ---: | ---: |
| A 文件操作 | 1 | 2 | 0 | 33.3% |
| B Python CLI | 0 | 3 | 0 | 0% |
| C 终端执行和修复 | 3 | 0 | 0 | 100% |
| D 自主开发和测试 | 3 | 0 | 0 | 100% |
| E Git 管理 | 0 | 3 | 0 | 0% |
| F 视觉理解 | 2 | 1 | 0 | 66.7% |
| F Windows 桌面操作 | 0 | 3 | 0 | 0% |
| 合计 | 9 | 12 | 0 | 42.9% |

首次 F-desktop/2 在已有记事本进程时由测试保护拦截。待进程退出后只补跑此轮，模型实际运行并失败。下表保留两次记录，汇总只计补跑结果。D/2 实际收到一次 `finish_reason=length`，一次协议恢复后进入独立验证并通过。CLI 和 Git 场景仍有截断耗尽与断言失败。

## 扩展验收和回归

- **PASS**：真实 Gemma 取消、关闭 WebSocket、重连及从原运行恢复。恢复后真实执行 pytest，文件成功修改事件累计一次。
- **FAIL**：三个新增空白工程。待办 CLI 和文件扫描器均在输出截断后耗尽恢复次数。Tk 计算器生成代码和测试，独立复跑为 1 项通过、3 项失败。失败包含把 Tcl 变量标识当作 Python 变量对象，以及 Tk 初始化异常。计算器整体验收未通过。
- **FAIL**：Gemma 记事本中文用例和三轮原桌面操作。模型成功激活窗口并读取 UIA，重复“发现 → 激活 → 检查”后触发循环保护，未提交输入和保存证据。
- **PASS**：独立 Windows 原生对照调用真实桌面工具，将指定中文写入记事本并通过 Ctrl+S 保存，读回一致，测试窗口已关闭。该对照未使用模型。
- **PASS**：Windows Python 全量 714 项通过、2 项跳过。全量之后新增的 Git 初始化非零退出断言随工程创建定向回归 8 项通过。HTTP 流协议、诊断与数据目录定向回归分别 5、12、9 项通过。
- **PASS**：TypeScript、前端 102 项、Electron 构建、独立 Windows x64 打包应用 55 项 Electron Smoke。Smoke 的模拟模型与真实 Ollama 评分分开。
- **PASS / FAIL**：冻结版真实 Gemma 的 C 用例通过，B 用例未满足独立 CLI 断言。正式安装版旧后端额外执行的 B 基线也未满足断言。正式安装与用户数据目录保持原样。完整安装器升级和卸载本轮为 **NOT_RUN**。
- 权限、取消、重复操作、进程树、WS 和无 Git 验证由既有自动化套件回归。Git 安装正常、Git 不存在、Git 初始化非零退出均有独立用例。真实模型桌面轮次只允许向专用 PID、指定控件发送限定操作，保留了后端安全校验。

原始日志和测试目录索引位于本机 `build/gemma-v101-*`。账本 Token 为 Ollama 报告的累计输入及输出，重复上下文请求会计入，未获得用量以横线表示。脱敏工具事件、文件变更、退出码及状态见 [results.json](results.json)。

## 逐轮证据

| 入口 | 用例 | 轮次 | 结果 | 原因或错误码 | 秒 | 工具数 | 输入 / 输出 Token | 协议恢复 |
| --- | --- | ---: | --- | --- | ---: | ---: | --- | ---: |
| installed_baseline | B | 1 | FAIL | MODEL_FAILURE | 157.91 | 23 | 138990 / 3502 | 0 |
| original_21 | A | 1 | FAIL | MODEL_TRUNCATED | 101.84 | 8 | 65316 / 2940 | 1 |
| original_21 | A | 2 | FAIL | TOOL_FAILURE_LIMIT | 89.88 | 11 | 72237 / 2446 | 0 |
| original_21 | A | 3 | PASS | — | 48.8 | 7 | 48966 / 1125 | 0 |
| original_21 | B | 1 | FAIL | MODEL_TRUNCATED | 137.45 | 10 | 83768 / 4086 | 1 |
| original_21 | B | 2 | FAIL | MODEL_TRUNCATED | 140.25 | 9 | 79526 / 3967 | 1 |
| original_21 | B | 3 | FAIL | MODEL_FAILURE | 109.89 | 10 | 61652 / 2439 | 0 |
| original_21 | C | 1 | PASS | — | 51.95 | 6 | 37104 / 863 | 0 |
| original_21 | C | 2 | PASS | — | 45.59 | 6 | 37092 / 877 | 0 |
| original_21 | C | 3 | PASS | — | 46.01 | 6 | 37111 / 884 | 0 |
| original_21 | D | 1 | PASS | — | 45.58 | 5 | 23188 / 1277 | 0 |
| original_21 | D | 2 | PASS | — | 65.05 | 5 | 28822 / 2227 | 1 |
| original_21 | D | 3 | PASS | — | 57.7 | 7 | 37519 / 1505 | 0 |
| original_21 | E | 1 | FAIL | MODEL_TRUNCATED | 146.41 | 13 | 110116 / 3730 | 1 |
| original_21 | E | 2 | FAIL | MODEL_FAILURE | 86.45 | 10 | 62019 / 2387 | 0 |
| original_21 | E | 3 | FAIL | MODEL_TRUNCATED | 149.52 | 14 | 118741 / 3732 | 1 |
| original_21 | F-vision | 1 | PASS | — | 39.88 | 2 | 20032 / 647 | 0 |
| original_21 | F-vision | 2 | PASS | — | 31.5 | 2 | 20072 / 351 | 0 |
| original_21 | F-vision | 3 | FAIL | MODEL_TRUNCATED | 77.03 | 2 | 28267 / 2370 | 1 |
| original_21 | F-desktop | 1 | FAIL | TOOL_LOOP_DETECTED | 63.76 | 6 | 25173 / 1218 | 0 |
| original_21 | F-desktop | 2 | BLOCKED | existing_notepad | 0.36 | 0 | — | — |
| original_21 | F-desktop | 3 | FAIL | TOOL_LOOP_DETECTED | 64.58 | 6 | 20241 / 1446 | 0 |
| desktop_retry | F-desktop | 2 | FAIL | TOOL_LOOP_DETECTED | 51.22 | 6 | 20262 / 1328 | 0 |
| projects | P1 | 1 | FAIL | MODEL_TRUNCATED | 113.05 | 3 | 34040 / 3801 | 1 |
| projects | P2 | 1 | FAIL | MODEL_TRUNCATED | 82.47 | 2 | 24091 / 3154 | 1 |
| projects | P3 | 1 | FAIL | TOOL_LOOP_DETECTED | 82.58 | 9 | 41704 / 2556 | 0 |
| lifecycle | R | 1 | PASS | — | 69.19 | 10 | 49726 / 1830 | 0 |
| lifecycle | N | 1 | FAIL | TOOL_LOOP_DETECTED | 54.81 | 6 | 25094 / 1426 | 0 |
| packaged | C | 1 | PASS | — | 44.69 | 6 | 37144 / 859 | 0 |
| packaged | B | 1 | FAIL | MODEL_FAILURE | 84.45 | 10 | 61690 / 2134 | 0 |


## 发布判断

**未达到 v1.0.1 发布条件。** 截断后的安全恢复和真实取消恢复已有证据。原 21 轮只有 9 轮通过，CLI、Git、复杂空白工程和 Gemma 桌面保存仍缺少通过证据。后续需要验证长输出配置与复杂任务拆分策略，并查明 Gemma 重复请求 UIA 的原因。自动化 CI 与真实模型评分分别判断。

最后一轮诊断字段修补后，Unified Runtime 定向 46 项通过，重新冻结的 Windows 后端启动与 8 个工作流模板加载检查通过。CI 结论见本分支 Pull Request 的 Windows / Ubuntu Core checks。

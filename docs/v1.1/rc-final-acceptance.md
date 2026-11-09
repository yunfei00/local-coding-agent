# v1.1 Release Candidate 最终复验

## 2026-11-09 收尾复验

本节产品 SHA 为 `dba4ef42716b3ed99a6770e3746b6346e1323930`。**RC 未达门槛，PR #38 保持 Draft。** 下文是前一产品 SHA 的历史证据。

- 原记事本失败时，前台和点击工具已成功，失败发生于清空读回，随后模型重复按键。旧工具把 Ctrl+A 与 Backspace 一次提交，无法在删除前确认选区。新实现等待同一个已绑定 RichEdit 的真实选区读回，检查 UIA 查询前后的焦点，再发送一次清空键并读回。延迟选区和未确认选区的确定性测试通过。原记事本独立三次 3/3，耗时 96.08、88.53、83.33 秒；完整旧批次里另有 3/3。原前台、输入、保存和独立读回断言均保留。
- 旧 21 项完整回归 20 PASS、1 FAIL。B 第一轮在 Windows PowerShell 中使用不兼容的 `&&`，后续命令仍失败并触发工具失败上限，独立补测 1 PASS，原批次仍为 20/21。
- 30 项完整回归 28 PASS、1 FAIL、1 BLOCKED。此次产品改动只涉及桌面输入工具，所以执行一轮完整回归。库存 30 通过，只有一个 Tester，交付目录无库存数据。05 定向和完整轮均未满足原评分要求的 `ValueError`；定向交付保留了坏文件但抛出 `RuntimeError`。21 定向轮未完成服务接线，完整轮通过。24 两次均为显式恢复确认 BLOCKED；此前的空响应已有有界协议重试入口，本轮未重现，不自动确认或重放。
- 待办旧超时轮有 117 条模型完成事件，累计 585.51 秒、输入 2676334、输出 15911 Token；383 秒成功轮有 24 条，累计 358.86 秒、输入 353905、输出 14181 Token。新空白工程轮有 120 条、累计 589.38 秒，未到 Tester，601.88 秒终止。主要差异是调用数量和累计上下文，另有重复命令与重写测试；旧超时轮 pytest 曾通过，证据不支持 pytest 等待是主因。新定向轮在 522.55 秒因 Developer 修正测试后未重新声明交接而失败；旧哈希拒绝保护生效，下一步需在修复路径要求重新声明并复核授权。600 秒基线保持。
- 三个空白工程原批次 0 PASS、2 FAIL、1 BLOCKED。待办超时，扫描器 Tester 尝试递归删除文件被阻断，Tk 计算器因 Windows 会话锁定未启动。安全拒绝未绕过。
- 本地确认测试 6 PASS；本地 Windows 原生套件 4 PASS、7 SKIP；同产品 Windows 与 Ubuntu CI 全绿。隔离 Setup 安装、启动、卸载与 v1.0.1 升级通过，Portable 检查通过。下载后两份 SHA256 一致，见候选构建清单。正式安装版保持。[CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42550348440) · [候选资产](https://github.com/yunfei00/local-coding-agent/actions/runs/42550420258)
- [逐项脱敏记录](rc-desktop-stability-results.json)；原始结果和日志索引保存在本机 `build/v11-final-evidence/dba4ef4`。未合并或发布。

本次验收在 Windows 11 x64 上运行，独立 Git 工作树、临时工程、数据目录和窗口均与现有 v1.0.1 分离。真实模型为已配置的局域网 Ollama `gemma4:31b`。各轮使用 Python 3.12.13、uv 0.11.2，模型上下文 32768、输出上限由服务端决定，单次模型请求最多 180 秒，模型步骤上限 100。完整工程用例和旧回归单例上限 600 秒。原任务和原始独立评分保持不变。

**结论为暂未达到 RC 门槛，PR #38 保持 Draft。** 最终提交三轮 30 项均达标，库存和候选安装通过。旧 21 项的原始批次为 20/21，独立补测通过后仍保留原始失败。

## 冻结基线与修复依据

| 被测提交 | 真实记录 | 处理 |
|---|---|---|
| `0b65ed9e9030b66103382b7f2c7f405d232e6cba` | 独立库存复验 PASS，277.39 秒，22 次模型请求、29 次工具调用。一个 Tester，三个独立 cwd 各运行 6 项测试，交付目录没有库存运行数据。完整首轮 25 PASS、4 FAIL、1 BLOCKED，其中库存再次通过。 | 用例 16 的外部评分器在干净环境缺少 `packaging`。安装现有锁定 extra 后，对同一交付执行原评分通过，保留原始失败记录。用例 25 真实改写了先运行的原测试。 |
| `63a96344485cb1233c75220e9835d6e9645b2d49` | 复验 25、30 都通过。25 的原测试保留，真实退出码先为 1，再为 0。完整三轮为 28、27、28 PASS，共 83 PASS、4 FAIL、3 BLOCKED。 | 将明确要求先复现、修复实现、再复测的任务接到现有测试保护，允许明确授权的测试更新。库存第二轮仍在 Tester 已通过 7 项测试后尝试执行未授权的业务命令，权限阻断有效，端到端结果为 FAIL。 |

两次产品缺陷均先通过真实事件定位，再建立修复前失败的确定性回归。最终收尾规则只在当前独立 Tester 的持久化步骤已有实际成功测试证据时过滤额外越权请求。仍执行获准的必要验证以及最终独立验收。模型声称通过、旧步骤证据、命令返回非零和无实际测试结果都不能用于此规则。

用例 05 的需求未指定异常类型，原独立评分要求 `ValueError`。早期失败中模型保留损坏数据但返回 `RuntimeError`，按原断言计失败。用例 24 在取消后以新请求重发，触发显式恢复确认，按 BLOCKED 计。工作区安全控制保持开启。

## 收尾修复后的候选 6d7d26f

产品 SHA 为 `6d7d26f8a2c7cd1b3e5816c2dba8cca61fa31bd7`。库存 30 在同一干净工作树定向运行三次，3 PASS，耗时分别为 462.58、265.38、249.45 秒。每次都有四个 Developer 步骤及一个 Tester，实际测试通过后进入最终独立验证。原始评分均通过，交付目录均无 `inventory.json`。额外越权请求的安全收尾由确定性回归覆盖。

Windows 本地定向回归 109 PASS。该产品提交的 Windows、Ubuntu CI 均通过，包含 Python 全量、TypeScript、前端、Electron 构建，Windows 还运行了真实 Electron Smoke 与受控原生 GUI 检查。[最终产品 CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42480752337)

同一 SHA 的 Windows x64 候选包在隔离 Windows runner 完成 Setup 安装、启动、无 SDK 运行、卸载，以及 v1.0.1 到 v1.1.0 升级和数据保留。Portable 启动及受控聊天路径通过。候选包已下载并重新计算 SHA256。[构建和隔离升级](https://github.com/yunfei00/local-coding-agent/actions/runs/42482984113)

| 产物 | SHA256 |
|---|---|
| Local-Coding-Agent-1.1.0-x64-Setup.exe | `b0af5c857ce7e253e98627b7b76cd74b5b4205e5201ef11f68e1b798550fff79` |
| Local-Coding-Agent-1.1.0-x64-Portable.exe | `3c8286ccd6be017d4d59e58e1319e99c636d65b224c59e41b35231fd7e3804d4` |

从已校验 Portable 解出的原始打包后端，使用独立数据目录和真实 Gemma 完成旧基线文件任务 A。实际调用 8 次工具，原评分通过，耗时 68.52 秒。安装与渲染器验证使用隔离 Windows 构建环境的受控模型，真实 Gemma 证据来自同一候选资产中的打包后端。

### 30 项真实工程

| 轮次 | PASS | FAIL | BLOCKED | NOT_RUN |
|---|---:|---:|---:|---:|
| 1 | 28 | 1 | 1 | 0 |
| 2 | 28 | 1 | 1 | 0 |
| 3 | 29 | 0 | 1 | 0 |

合计 85/90。用例 05 第 1、2 轮的异常类型不符合原始独立断言。用例 24 三轮均停在显式恢复确认。库存 30 的完整批次为 3/3，连同定向复验共 6/6，六次均只有一个 Tester，交付目录均无运行数据。完整第二轮的真实事件包含 `workflow.tester.redundant_tool_blocked`，随后终态为 `completed_verified`，原始独立评分通过。

### 旧回归与空白工程

- 旧回归为 19/21。视觉首轮遇到资源阻断，后续截图已成功，但模型输出仍未通过独立挑战断言。桌面首轮输入读回不符，模型随后重复按键，工具正确终止循环。视觉与桌面其余各两轮通过。
- 空白工程为 1/3，文件扫描器通过。Tk 计算器的模型实现把按钮嵌套在 Frame 内，违反原任务和断言的直接子控件约定。待办 CLI 的隔离测试遇到产品兼容缺陷，进入后续修复。

## pytest 隔离兼容修复

待办项目先调用 `pytest`，隔离启动器拒绝了标准别名；改用 `python -m pytest` 后，uv 临时环境的已安装包以及 pytest 对系统空设备的访问又被拒。用实际 pytest 9.2.0 和一个可写临时数据的最小测试复现。直接安装到独立虚拟环境也复现了系统空设备拒绝，排除了单一 uv 环境因素。

产品提交 `62452fa14ea32dd3e66984084a8d4c365048bc99` 将 pytest 别名转成单条 Python 调用；只允许读取已选 uv 环境的活动依赖目录，精确允许系统空设备。Windows 下禁用 pytest 可选的 Colorama 终端适配，原生调用仍被拦截。既有子进程、绝对路径和写入防护保持。真实 pytest 最小验证退出 0，原交付无测试数据。进程、运行时、工作流、权限定向回归共 114 PASS、1 SKIP。

## 最终产品 62452fa

库存 30 门槛复验 3/3，每次只有一个 Tester，最终独立验证通过，交付目录无库存数据。该提交的 Windows、Ubuntu PR 检查以及分支检查通过。PR 首次运行的 Windows GUI 夹具未创建 readiness 文件，同提交复跑通过。[最终产品 CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42496752236)

同提交的 Windows x64 候选包完成隔离安装、启动、卸载、无 SDK 验证，以及 v1.0.1 到 v1.1.0 的升级和数据保留。Setup 和 Portable 下载后按清单重新计算 SHA256，均相符。本地保存在 `build/v11-final-evidence/62452fa-windows-ci-artifacts/desktop/release`。[最终候选构建和资产](https://github.com/yunfei00/local-coding-agent/actions/runs/42497809637)

| 产物 | SHA256 |
|---|---|
| Local-Coding-Agent-1.1.0-x64-Setup.exe | `9eb9f95658d3535bddc9ef3ba2784237083963b2cdc30d841aad297af834d1da` |
| Local-Coding-Agent-1.1.0-x64-Portable.exe | `56273b908639785c0d32b254ba27fc794500e8decb85136843335e8d47ca8493` |

使用上述 Portable 中原始打包后端，通过真实 Gemma 完成文件操作基准 A，原独立评分通过。

### 三轮最终工程验收

| 轮次 | PASS | FAIL | BLOCKED | NOT_RUN |
|---|---:|---:|---:|---:|
| 1 | 28 | 1 | 1 | 0 |
| 2 | 28 | 1 | 1 | 0 |
| 3 | 28 | 2 | 0 | 0 |

合计 84/90，三轮均达到 27/30。库存在完整批次 3/3，与定向复验合计 6/6。第 1 轮用例 05 因尝试重复执行已有副作用的命令且未补充成功证据而失败。第 2 轮用例 05 仍未满足原异常类型断言。第 3 轮用例 21 的终端失败没有对应的成功复测，第 3 轮用例 24 收到空模型响应。第 1、2 轮用例 24 继续停在恢复确认门槛。保留工具重复保护、成功证据要求和恢复审批。

### 旧 21 项和空白工程

| 验收 | 原始批次 | 独立补测或证据 |
|---|---|---|
| 旧 21 项 Gemma 回归 | 20 PASS、1 FAIL | 文件、CLI、pytest 修复、pytest 开发、Git 和真实截图视觉各 3/3。Windows 记事本原批次 2/3，独立补测 1/1。 |
| 待办 CLI | FAIL，601.94 秒触发 600 秒任务上限 | Agent 的真实 pytest 命令已通过。对保留交付的副本执行原评分也通过，端到端仍按 FAIL。900 秒补测配置下独立完成并通过，实际 383.14 秒。 |
| 文件扫描器 | PASS | 原功能和 pytest 断言通过。 |
| Tk 计算器 | PASS | 原 Tk 窗口和控件断言通过。 |

记事本失败轮先得到 `DESKTOP_VALUE_MISMATCH`，清空阶段的实际读回与预期不符。随后模型反复提交 Ctrl+A 和未获批准的 Backspace，触发 `TOOL_LOOP_DETECTED`。真实焦点、写入和读取在另外两轮及独立补测均有证据，补测用时 107.95 秒。相同签名也出现于收尾修复前，授权和循环保护均按预期工作。保留所有失败与独立通过记录，到此结束有界复测。

### 软件回归和证据保存

- Windows Python 全量 758 PASS、2 SKIP，另有 3 项受控 Windows 原生 GUI 检查通过。Ubuntu Python 全量 743 PASS、17 SKIP。前端 102 PASS，TypeScript、Electron 构建及 Windows Electron Smoke 通过。
- 权限、取消、恢复、无 Git 工程、WebSocket 重连，以及 Ollama 输出限制留空均有自动化覆盖。用例 20、23 在最终三轮各 3/3。真实模型配置使用空输出上限，未出现 `Invalid output_limit`。
- [逐项脱敏结果](rc-final-results.json) 保留最终提交每轮原结果及独立补测。原始运行日志和独立目录索引留在本地 `build/v11-final-evidence`。报告提交仅更新文档和验收数据，所有产品测试和安装包指向上文产品 SHA。
- [PR #38](https://github.com/yunfei00/local-coding-agent/pull/38) 保持 Draft，未合并 main、未发布，也未覆盖本机 v1.0.1。

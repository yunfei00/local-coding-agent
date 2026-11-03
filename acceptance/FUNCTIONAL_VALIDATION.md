# Local Coding Agent 功能验收操作手册（Windows 公司环境）

## 目标与边界
本阶段只验证功能，不开发新功能、不合并 main、不发布安装包。验收对象是 Local Coding Agent 的真实 Agent Loop、模型生成、文件读写、终端执行和自动测试能力。所有测试只操作独立样例工程。

## 0. 准备
- Windows PowerShell、Git、Python 3.8+（可运行 `python --version`）。
- Local Coding Agent 已安装并能打开；模型连接已经配置。不要在日志中公开 API Key。
- 不要在存在未提交修改的工作目录里直接切换分支；建议单独克隆。

## 1. 拉取专用验收分支
在一个你希望放置测试文件的目录中执行：

```powershell
git clone --branch test/agent-functional-validation https://github.com/yunfei00/local-coding-agent.git local-coding-agent-validation
cd local-coding-agent-validation
git branch --show-current
git log -1 --oneline
python --version
```

预期分支是 `test/agent-functional-validation`。如仓库私有且 HTTPS 需要认证，使用你已有的 Git 凭据。若已有单独克隆，则 `git fetch origin; git switch test/agent-functional-validation; git pull --ff-only`。

## 2. 自动生成 L1 样例工程

```powershell
python acceptance/company_l1.py --setup
```

预期打印 `BASELINE_EXPECTED_FAIL: True`。这表示故意预置的 Bug 已被测试发现，不是环境异常。脚本会覆盖 `acceptance/workspace` 下固定的样例文件；不要在此放个人文件。

## 3. 在 Local Coding Agent 中执行
1. 启动 Local Coding Agent（如果修改过源码，应完全退出后重新启动）。
2. 选择“打开工程”，只打开刚生成的 `acceptance/workspace` 目录，不要打开整个产品仓库。
3. 选择公司已配置的一个在线模型；第一轮先不要同时切换多个模型。
4. 新建对话，把下方整段任务要求复制到聊天框，发送。
5. 如果弹出正常的文件写入/命令执行审批，检查目标仅在样例工程内再批准；不要批准工作区外的写入、危险命令或敏感文件读取。
6. 等待 Agent 自己运行测试并报告结果。记录模型名称、耗时、工具调用失败、审批次数和最终回复。不要自己修复代码。

### 完整任务指令（直接复制）
```text
请修复当前 Python 订单计算项目的金额计算错误。

规则：折扣只适用于商品小计，运费不参与折扣。
示例：单价100元，数量3，折扣10%，运费10元，正确总额280.00元。

请自行完成：
1. 阅读当前工程代码，定位错误原因。
2. 仅修改必要的业务代码，不能修改测试文件来掩盖错误。
3. 自动执行 python -m unittest discover -v。
4. 如果测试失败，继续定位并修复。
5. 最后报告实际修改的文件、错误原因、执行的命令和真实测试结果。
6. 不访问或修改工程目录以外的文件。
不要让我手动修改代码或手动运行 Agent 的测试。
```

## 4. 独立验收（在 PowerShell 中运行）
回到克隆仓库的根目录：

```powershell
python acceptance/company_l1.py --verify
Get-Content acceptance/result.json
```

通过标准：`result.json` 的 `passed` 为 `true`。验证包括公开测试、六个独立测试，以及测试文件完整性检查。即使 Agent 自称成功，`passed: false` 仍视为未通过。

## 5. 第二次运行：验证重复性
先保存第一轮 `result.json` 的内容（复制到仓库外，或直接发送给我）。然后重新运行：

```powershell
python acceptance/company_l1.py --setup
```

在 Local Coding Agent 中新建对话，再发送同一段任务指令；结束后再次运行 `--verify`。第三次同样操作。每次都记录结果，避免复用已修好的代码。

## 6. Ollama 模型测试
先在 PowerShell 确认模型可独立回复（替换成你实际安装的模型名）：

```powershell
ollama list
ollama run <模型名称> "请回答：2+2等于多少？"
```

随后在 Local Coding Agent 里选择同一个 Ollama 模型，重复第 2–4 步。若 Ollama 命令行正常但 Agent 生成失败，保留完整报错文字；这是 Provider/Agent 兼容性问题的关键证据。

## 7. 反馈给我
请提供以下信息（无需自己分析）：
- Local Coding Agent 当前使用版本或源码提交号
- 模型名称、Provider 类型（Ollama 或在线 API）
- 第 4 步生成的 `acceptance/result.json` 内容
- Agent 最后回复，以及是否自动执行了终端测试
- 如失败，完整错误提示和相关日志（先删除密钥、Token、个人路径中的敏感部分）

## 8. 下一阶段
L1 稳定后，依次进行 L2（增加优惠规则）、L3（多文件功能）、L4（Web 小项目）、L5（失败自动修复）、L6（任务恢复）。后续用例也由仓库提供完整脚本，不要求用户自己编写。

## 备注
当前 L1 的 `company_l1.py` 文件名是早期测试资产的内部名称，不影响使用；后续统一重命名为功能验收命名。旧分支 `test/company-agent-acceptance-20261103` 不再作为执行入口。

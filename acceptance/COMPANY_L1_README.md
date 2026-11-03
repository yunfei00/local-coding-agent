# 公司环境 L1：真实自主修复验收

此目录是独立的测试资产，不修改 Local Coding Agent 产品代码。使用 Windows PowerShell，在仓库根目录执行。

## 1. 获取分支

```powershell
git fetch origin
git switch test/company-agent-acceptance-20261103
git pull --ff-only
```

如当前有未提交修改，先备份或使用独立克隆，不要强行切换。

## 2. 生成测试工程（Python 3.8+）

```powershell
python acceptance/company_l1.py --setup
```

预期显示 `BASELINE_EXPECTED_FAIL: True`，因为故意保留一个订单折扣 Bug。

## 3. 在 Local Coding Agent 中执行

打开仓库中的 `acceptance/workspace` 目录作为**独立工程**（不是整个 local-coding-agent 仓库）。
使用当前已配置的在线模型或 Ollama 模型，直接粘贴 --setup 输出的 PROMPT（也可复制下面这段）：

> 请修复当前 Python 订单计算项目的金额计算错误。规则：折扣只适用于商品小计，运费不参与折扣。示例：单价100元，数量3，折扣10%，运费10元，正确总额280.00元。请先阅读项目文件，定位原因，只修改必要的业务代码，不要修改测试文件，不要跳过测试；自行运行 python -m unittest discover -v，如果失败继续修复，最后报告修改文件、原因和真实测试结果。不要访问工程以外的文件。

记录所用模型、耗时、是否弹出审批、工具调用异常，以及最终 Agent 回复。

## 4. 独立验收

回到仓库根目录的 PowerShell，执行：

```powershell
python acceptance/company_l1.py --verify
Get-Content acceptance/result.json
```

只有 `passed: true` 才代表 L1 代码验收通过。验收脚本还会运行 6 项不在 Agent 工作区中的独立测试，检查公开测试文件没有被修改。

## 5. 复测其他模型

每次切换模型前重新运行 `python acceptance/company_l1.py --setup`，再用新会话打开相同 workspace，避免模型读取上一次修复结果。

## 6. 反馈信息

请发回：模型名称、`acceptance/result.json`、Agent 最后回复、是否出现报错。若生成失败，请附错误文字或日志（删除 API Key 和其他凭据）。

注意：`--setup` 会覆盖 `acceptance/workspace` 中的三个固定样例文件。请勿在该目录放置自己的工作文件。不要把真实 API Key 写入测试文件。
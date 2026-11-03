# L2：Agent 自主新增功能验收（Windows 公司环境）

## 验收目标
L1 已通过：DeepSeek V4 Flash 与 GPT-OSS 20B 均成功修复 Bug，自动执行终端测试并通过独立验收。

L2 进一步验证 Agent 是否能根据自然语言需求**新增功能**，而不是只修复现成 Bug。本阶段不修改产品代码、不合并 main。

## 1. 更新测试分支
在此前克隆的 `local-coding-agent-validation` 目录打开 PowerShell：

```powershell
git switch test/agent-functional-validation
git pull --ff-only
git log -1 --oneline
```

## 2. 生成 L2 测试工程
```powershell
python acceptance/feature_l2.py --setup
```

预期输出 `BASELINE_EXISTING_TESTS_PASS: True`。脚本会自动生成 `acceptance/workspace_l2`，里面已有订单计算逻辑，但**没有优惠券功能**。

注意：`--setup` 会重置该样例目录的固定文件；每换一个模型之前都要重置。

## 3. Local Coding Agent 实际执行
1. 打开 Local Coding Agent。
2. 打开 `acceptance/workspace_l2` 作为独立项目，不要打开整个产品仓库。
3. 新建会话，选择 DeepSeek V4 Flash。
4. 复制下方完整任务指令发送给 Agent；让 Agent 自己查看文件、修改代码、运行测试。正常审批可检查后批准，不要自己编辑代码。
5. 等 Agent 完成，记录其最后回复、自动测试是否执行、是否出现报错。

### 完整任务指令（直接复制）

```text
请在当前 Python 订单计算项目中新增“满减优惠券”功能。

保留现有 total_price(unit_price, quantity, discount_percent=0, shipping=0) 的兼容性，新增两个可选参数 coupon=0 和 min_spend=0。

业务规则：
1. 先计算原始商品小计 = 单价 × 数量。
2. 按 discount_percent 对商品金额打折。
3. 只有原始商品小计达到 min_spend，才可在折后商品金额中减去固定优惠券金额 coupon。
4. 优惠券最多抵扣商品金额，折后商品金额不能为负数。
5. 运费最后加上；运费不参与折扣，也不计入满减门槛。
6. 返回保留两位小数的 Decimal。
7. coupon 或 min_spend 为负数时抛出 ValueError。
8. 旧调用方式必须继续工作。

示例：单价100元，数量3，折扣10%，运费10元，满200减30元，正确总额250.00元。

请自行阅读工程，修改必要的业务代码，补充必要的公开单元测试，并自动执行：
python -m unittest discover -v

如果测试失败，继续定位修复。不要通过删除或篡改原有测试来使结果通过。完成后报告修改文件、功能逻辑、执行命令和实际测试结果。不要访问工程目录以外的文件，也不要让我手动修改代码。
```

## 4. 独立验收
回到 PowerShell 的仓库根目录执行：

```powershell
python acceptance/feature_l2.py --verify
Get-Content acceptance/result_l2.json
```

通过标准：`result_l2.json` 中 `passed: true`。独立验收检查兼容性、满减门槛、折扣顺序、运费、抵扣下限、参数校验和公开测试，共包含 10 个独立业务测试。

## 5. 本地 GPT-OSS 20B 复测
重新运行：

```powershell
python acceptance/feature_l2.py --setup
```

在 Local Coding Agent 中打开相同的 `workspace_l2`，新建会话，切换 GPT-OSS 20B，再发送**完全相同的任务指令**。完成后执行：

```powershell
python acceptance/feature_l2.py --verify
Get-Content acceptance/result_l2.json
```

## 6. 把结果发给我
请分别反馈两个模型的 `passed`、`checks`、Agent 最后回复，以及是否调用终端测试。若失败，发送失败的独立测试输出即可（隐藏密钥）。

如果两个模型均通过，进入 L3：多文件功能开发验收。不要提前合并到 main。

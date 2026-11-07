# 缺陷与失败归因

## 确认缺陷 · 英文诊断并修复被误判为只读

安装版 C 用例对 Gemma 三次、Qwen 两次返回 UNIFIED_READ_ONLY_INTENT。Qwen 另一轮先达到轮次超时。真实工具先执行了失败的测试，但意图守卫拒绝后续写入。

`requested_intent` 将 diagnose 识别为分析，未识别明确的 repair 文件请求。分支修复仅识别句首或 and/then 后直接指定文件的 repair 命令，显式只分析仍优先。回归断言覆盖原复现、显式只分析及仅讨论修复选项。最终代码的 Unified Runtime 回归 45 项通过。源码真实复测独立记录于 results.json 的 source_retest。

## 确认缺陷 · 无 Git 工程仍强制要求 Git diff

第一项修复后的中间版本中，Gemma C 前两轮实际写入修复，pytest 从退出码 1 变为 0，但 Agent 仍以 PLAN_STEP_NO_EVIDENCE 结束。该批三轮记录保留在 intermediate_source_retest。发现第二项问题后结束中间版本试验。

完成检查把 Git diff 作为任何改动的必经步骤，自动验证也调用 Git diff。现在按当前工作区及其父目录的 Git 元数据判断，非 Git 工作区仍要求适用的代码验证。Git 仓库保留原差异门槛。Agent Loop 12 项和 Unified Runtime 45 项通过。

## 验收驱动问题

初次 F 用例替换隔离模型目录时遗漏了旧角色绑定，进入模型之前被拒绝。驱动改为同时显式绑定测试角色。Windows 记事本可能由启动器转交新窗口，复测通过唯一测试文件标题和窗口身份锁定范围。原版部署和服务设置不受这些驱动修正影响。

首次启动探测使用相对数据路径，在安装版后端目录下产生了 `build\ollama-pilot` 验收数据。后续驱动强制绝对路径，并把实际工程与数据库放进独立临时目录。安装目录中的探测残留仅含两组测试数据库和锁文件。自动审批审核拒绝了移动清理命令，返回 `blocked by policy`，该目录保留。安装版二进制和原用户数据库未被替换。

## 其他实测失败

- Gemma 的截断请求有 HTTP 200 和完成事件，finish_reason 为 length，部分输出达到 1024 Token。Agent 拒绝将截断结果当完成。
- Gemma Git 首轮创建了分支和提交，也产生了真实差异，scratch.txt 仍未纳入提交，恢复断言失败。
- Qwen 出现超时和空响应。已保存的接口可获取模型列表，部分真实 Agent 请求也返回 HTTP 200。服务报告 Qwen 显存占用为 0。这些证据不足以把延迟或空响应归为已确认产品缺陷。

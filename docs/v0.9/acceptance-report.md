# v0.9 验收报告（进行中）

基础 main：`7dbec0a5839f6af8b8621374c0e0f2b17108c200`。开发分支：`feature/v0.9-autonomous-workflow`。尚未合并，不能宣称完整验收通过。

已运行：计划基线 6 PASS；v0.9 工作流单元 10 PASS、交付/CI 安全单元 5 PASS、后台调度单元 4 PASS；原统一 Runtime 第一轮 44 PASS，之后新增四模型逻辑角色集成测试通过。最终全量统计待回归完成，不能直接相加当作去重总数。

前端第一轮原有 65 PASS，Electron 构建及类型检查 PASS。新增 UI 用例、最终 Smoke 和双平台 CI 待执行/更新。

真实模型探针：DeepSeek 与 Qwen 文本/工具 PASS；kimi-k3 HTTP 400 BLOCKED。真实 Python 四角色任务及独立 unittest、原测试保护、交付文件核对 PASS。原始失败报告保留，见综合验收。

待验收：React、测试修复闭环、真实暂停恢复、WebSocket 不中断执行、Windows GUI、本轮最终 CI。当前结论：尚未达到合并门槛。

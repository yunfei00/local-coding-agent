# v0.8 验收报告（执行中）

基线 main：00954ecd921c28823764e02e3a2d91b3c2720454。分支：feature/v0.8-intelligent-context。日期：2026-11-05，Windows，uv Python 3.12，串行测试。

当前结论：尚未达到合并门槛。实现、全量回归与真实工程验收进行中；不以历史通过记录替代本轮结果。

已运行：新增知识/路由/环境/真实 HTTP Mock Runtime 45 PASS；既有统一 Runtime 41 PASS；Repository Context 7 PASS；前端 65 PASS，类型检查和构建 PASS。随后新增缓存损坏与旧配置证据回归，需以最终全量结果更新数量。数据库迁移测试原版本断言失效，已修正为版本 6，等待复测。

真实模型、A–F 场景、Electron Smoke、远程 Windows/Ubuntu CI、PR 和 main 合并：NOT RUN。没有发起 Ollama 真实请求，没有调用禁止模型。

完整本机日志保存在 validation-reports/v08-*.log。完整历史失败记录保留，最终报告需分别标明 Mock、真实模型、真实 GUI、BLOCKED 与 SKIPPED。

## 首轮全量与修复记录

`20261105-154644-737520.log`：Python 共 613 项，594 PASS、15 FAIL、2 ERROR、2 SKIP；前端 65 PASS、类型检查和构建 PASS。失败明确保留，不计为通过。根因包括旧编排长提示超出检索词限制及新增上下文/工具描述挤占旧任务预算；已将查询限制到原目标的 500 字符，并让旧入口保持原请求开销，新统一入口自动启用知识。

受影响回归 `v08-regression-repair.log` 共 150 项：144 PASS、6 SKIP、0 FAIL。6 项 Windows GUI 因 DESKTOP_SESSION_LOCKED 跳过，不能标为 GUI PASS。新增能力探针额度停止与缓存时钟边界测试另行复测。首轮原生窗口焦点失败也保留，待桌面可用后复验。

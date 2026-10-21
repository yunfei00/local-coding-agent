# 公司电脑部署与使用

## 安装开发环境

Windows PowerShell，在克隆后的仓库目录执行：

```powershell
git switch feature/v0.4-local-first-agent
uv sync --locked
npm.cmd --prefix desktop ci
uv run python scripts/validation/check.py
.\scripts\dev\start.ps1
```

此分支仍是 v0.4 候选版。Setup/Portable 从本地 `desktop/release` 获取；正式 Tag/Release 只在全部门禁通过后创建。测试前备份日常数据，使用测试项目和隔离数据目录，不能用测试脚本覆盖实际公司项目。

## 模型配置

在公司允许的环境安装并启动 Ollama。检查已安装模型和本地服务：

```powershell
ollama list
ollama serve
```

若 Ollama 已在托盘运行，无需再启动第二个服务。Settings → Provider 设置实际本地 URL、已安装的模型名称、上下文窗口和温度。16GB/CPU 环境需要结合实际内存和延迟选择上下文；本次 1.5B 模型能连接、规划和读取文件，但没有完成修复，不能作为复杂自主编程验收通过的证据。

API 模型在同一 Provider 设置中填写公司允许的 OpenAI 兼容地址、模型和密钥。密钥由已有 OS-protected storage 或 session/environment 管理。不要把密钥写入项目、配置 JSON、Prompt 或 Git。Task → Models and budget 的 Test local/API connection 不生成模型 Token；连接成功不等于工具能力已经验证。真实生成可能产生费用，先设置调用数、Token、价格及费用上限。

## 自主任务

1. 打开已初始化并有至少一个提交的 Git 工程和 Thread，点击 Task。
2. 选择 Local-first / Local-only / API-only，按需为四个角色指定模型；空值继承对应 Provider。
3. 输入目标与本工程验证命令；未知项目先填写真实测试/构建命令。点击 Start autonomous task。
4. 在原 Approval 卡片确认隔离 Worktree 创建。任务从当前 HEAD 创建独立分支，不携带源工作区未提交文件；这些文件保留原位。若目标依赖未提交内容，先自行审查和提交到任务基线，不自动覆盖或搬移。
5. 查看聊天中的阶段摘要和 Task 中的模型、计划、预算、失败、日志路径、升级次数。Git/Context/Plan/Diagnostics 可按需打开，输入框仍可编辑，Enter 发送、Shift+Enter 换行。
6. Pause task 可暂停；Stop 取消执行并保留状态。恢复时确认 Worktree 和 Checkpoint，再选 Reopen / continue 或 Continue local-only。需要变更命令/模型/预算时先暂停，编辑面板配置并点击 Apply configuration to paused task；地址从 Settings 刷新，旧使用量保留。
7. 验证通过后阅读 Completion report and Git review，核对所有测试、Diff 和独立分支。Accept verified report 仅接受报告，不提交、不推送、不合并。
8. 需要 Git 操作时，在 Git 面板中打开报告所列受管理 Worktree，使用原显式提交和审批流程；所有远程操作由用户单独决定。

Local-first 升级会将有限相关代码 Diff/失败摘要发给配置的 API；使用公司代码前应确保该地址获准接收这些内容。Local-only 禁止全部自主 API 请求。没有付费 API 凭据时照常运行 Mock 自动化验收，真实 API 一项保留未验收。

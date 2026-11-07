# Phase 0 真实工程基准

使用仓库自制工程。每个工程至少有两个相关文件，具有可触发的初始缺陷或未完成需求。评估脚本和期望值由评估进程持有，初始工作区仅复制 fixture 文件。30 项与 v1.0.1 原 21 项独立计数。

| ID | 场景 | 独立验收 |
|---|---|---|
| 01 | 购物车多文件修复 | 数量计入总价，空车返回零 |
| 02 | 折扣兼容 | 旧整数接口与新折扣输入，包含零折扣 |
| 03 | 异常输入 | 有效端口与四类非法输入 |
| 04 | CLI | 成功/错误退出码、stderr 和无堆栈 |
| 05 | 持久化 | 保留历史键，损坏数据保留且抛错 |
| 06 | React 组件逻辑 | 检查 busy、disabled 和标签；无浏览器 DOM |
| 07 | 状态管理 | 不可变删除，缺失 ID 保留原列表 |
| 08 | API | 成功结果，失败响应禁止解析 |
| 09 | 表单 | 正常与非法邮箱/金额 |
| 10 | 构建测试 | 独立 ESM 导入、求和与空数组 |
| 11 | Git 分支 | 真实分支名和原始文件 |
| 12 | Git 提交 | 提交范围、次数、内容和干净状态 |
| 13 | Git 冲突 | 真冲突、双父提交、合并内容 |
| 14 | Git Diff | 仅目标文件有未暂存变更，精确行 |
| 15 | Git 恢复 | 撤销暂存与工作树误修改 |
| 16 | Python 依赖 | 解析两个 manifest 的约束并检查边界 |
| 17 | uv | 真实离线 lock 和工作区成员 |
| 18 | Node 依赖 | 本地依赖 manifest 和导出行为 |
| 19 | Windows 路径 | 真实中文空格路径，缺失分支 |
| 20 | 无 Git | 工程无 .git，可读取版本和回退 |
| 21 | 多阶段 | 解析、汇总、兼容入口和多输入 |
| 22 | 失败纠错 | 真实命令失败/成功证据，加外部函数测试 |
| 23 | 中断恢复 | 写入后取消，重连恢复，并独立验收 |
| 24 | 取消重试 | 写入后取消，重连同一请求，并独立验收 |
| 25 | 验证后修复 | 命令失败/成功证据及订单负输入 |
| 26 | 既有工程 | 修复大小写聚合，保留文档 |
| 27 | 功能与测试 | 配额边界，真实运行新增单元测试 |
| 28 | 多模块重构 | 账本行为与兼容入口 |
| 29 | 交付报告 | 功能通过，机器可读命令结果可复验 |
| 30 | 完整 CLI | 跨进程持久化、边界、单元测试、说明 |

## 运行方式

```powershell
uv sync --locked
uv run --locked python -m scripts.validation.realworld_benchmark --output build/phase0-baseline
uv run --locked python -m scripts.validation.realworld_benchmark --case 02 --output build/phase0-02
uv run --locked python -m scripts.validation.realworld_benchmark --category git --repeat 3 --output build/phase0-git
uv run --locked python -m scripts.validation.realworld_benchmark --retry build/phase0-baseline/results.json --compare build/phase0-baseline/results.json --output build/phase0-retry
uv run --locked python -m scripts.validation.realworld_benchmark --resume --output build/phase0-baseline
uv run --locked python -m scripts.validation.realworld_benchmark --rebuild-report build/phase0-baseline/results.json --output build/phase0-derived
```

需要已配置或用 `--ollama-url` 显式提供可用的 Ollama 连接，仅调用 `gemma4:31b`。不修改用户模型配置。默认上下文 32768，50 模型步骤配置，120 秒单请求，300 秒单用例，无客户端固定输出上限。原产品取消、预算与循环检测保留。每轮新建项目、后端、数据目录，串行执行。历史比较按用例和轮次对照，配置不同时应单独解读。

任务限定工程内操作、无外网、无远程 Git。Git 只使用临时仓库的本地身份。审批回包只对受控操作放行。当前进程与终端仍继承当前用户的 OS 权限；对不可信输入应在另行隔离的账号或虚拟机运行。不要发布 scratch 路径、完整日志或工作区数据库。每轮结果分片不覆盖，续跑保留已有分片并从新工作区开始未提交结果的轮次。汇总 JSON 与 Markdown 可重建，真实原始结果保留。

PASS 以外部断言通过为准。FAIL 表示已运行且未满足合同，BLOCKED 表示环境或驱动没有产生可评分结果，NOT_RUN 表示尚未执行。用例退出码失败需结合实际文件、工具结果和模型错误区分根因。Ollama 返回的 input/output token 按完成响应累加，缺失时保持未知。输入统计可包含重复提示；不等同于唯一上下文长度。

# 系统架构

## 1. 总体架构

Local Coding Agent 采用 **Desktop UI 与 Agent Core 分离** 的架构。

```text
┌──────────────────────────────────────────────┐
│              Electron Desktop                │
│                                              │
│ React + TypeScript                           │
│ Project / Thread / Chat / Diff / Approval    │
└───────────────────┬──────────────────────────┘
                    │
             WebSocket / JSON
                    │
┌───────────────────▼──────────────────────────┐
│               Agent Server                   │
│                  Python                      │
│                                              │
│ Thread / Turn / Event / Cancellation         │
└───────────────────┬──────────────────────────┘
                    │
┌───────────────────▼──────────────────────────┐
│                Agent Core                    │
│                                              │
│ Context Builder                              │
│ Agent Loop                                   │
│ Tool Dispatcher                              │
│ Permission Engine                            │
│ Provider Interface                           │
└──────────────┬───────────────┬───────────────┘
               │               │
        ┌──────▼──────┐  ┌────▼────────────────┐
        │ LLM Provider│  │     Tool System      │
        │             │  │                     │
        │ Ollama      │  │ Files / Search      │
        │ OpenAI-comp.│  │ Shell / Git         │
        └─────────────┘  └──────────┬──────────┘
                                    │
                          ┌─────────▼──────────┐
                          │ Windows Local Env  │
                          │                    │
                          │ PowerShell         │
                          │ Git                │
                          │ Python / Node      │
                          │ Gradle / ADB       │
                          │ Docker / SSH       │
                          └────────────────────┘

                    ┌──────────────────────────┐
                    │ SQLite                  │
                    │ Projects / Threads      │
                    │ Turns / Settings        │
                    └──────────────────────────┘
```

---

## 2. 架构原则

### 2.1 UI 不承担 Agent 逻辑

Electron 只负责：

- 桌面窗口。
- 项目选择。
- Thread 展示。
- 输入和停止。
- Tool Call 可视化。
- Diff。
- Approval。
- 设置。

以下逻辑禁止放在 Renderer：

- Agent Loop。
- 模型推理编排。
- Shell 权限判断。
- 文件权限判断。
- Git 自动操作。
- Provider 具体实现。

---

### 2.2 Agent Core 不依赖具体 UI

Agent Core 应能够脱离 Electron 独立运行。

未来可以复用到：

- CLI。
- 其他桌面客户端。
- Web UI。
- 远程 Agent。
- 自动化任务。

---

### 2.3 Provider 抽象

建议接口：

```python
class BaseProvider:
    async def list_models(self): ...
    async def chat(self, request): ...
    async def stream_chat(self, request): ...
    async def cancel(self, request_id): ...
```

当前：

```text
BaseProvider
├─ OllamaProvider
└─ OpenAICompatibleProvider
```

后续 Provider 继续通过同一抽象扩展，Agent Core 不依赖具体供应商。

Agent Core 不允许判断：

```python
if model == "某个具体模型":
    ...
```

模型差异通过 Provider Capability 处理。

---


---

## 2.4 Desktop / Agent 协议兼容

产品版本和通信协议版本独立演进。

当前协议版本：

```text
1.0.0
```

Desktop 在读取 Agent 的 ready payload 后、建立 WebSocket 前检查协议版本。

当前兼容策略：

```text
Desktop protocol major = 1
Agent 1.x.x            -> compatible
Agent 2.x.x            -> reject clearly
legacy/malformed label -> reject clearly
```

协议不兼容时必须进入明确 Error 状态，不能继续建立一个行为未定义的连接。

## 3. Thread / Turn 模型

### Thread

代表一个持续开发会话。

包含：

- thread_id
- project_id
- title
- created_at
- updated_at
- active_model
- permission_mode

### Turn

代表用户发起的一次任务。

```text
Thread
├─ Turn 1
├─ Turn 2
└─ Turn 3
```

一个 Turn 内可以发生很多次：

```text
LLM
-> Tool
-> LLM
-> Tool
-> LLM
-> Tool
-> Complete
```

因此不能把一次 LLM 请求等同于一个 Turn。

---

## 4. Agent Loop

建议状态：

```text
IDLE
THINKING
WAITING_TOOL
RUNNING_TOOL
WAITING_APPROVAL
COMPLETING
COMPLETED
FAILED
CANCELLED
```

基本流程：

```text
Turn Start
   │
   ▼
Build Context
   │
   ▼
Call Provider
   │
   ├── Text Delta ──────────────> UI
   │
   ├── Tool Call
   │      │
   │      ▼
   │  Permission Check
   │      │
   │      ├─ Need Approval ─────> UI
   │      │
   │      ▼
   │  Execute Tool
   │      │
   │      ▼
   │  Tool Result
   │      │
   └──────┴──────────────> Call Provider Again
                          │
                          ▼
                       Complete
```

必须有：

- max_steps
- turn_timeout
- cancellation token
- duplicate-call detection
- tool error recovery
- structured events

---

## 5. Tool System

所有 Tool 实现统一接口。

建议结构：

```python
class Tool:
    name: str
    description: str
    input_schema: dict

    async def execute(self, context, arguments):
        ...
```

Tool Result 建议统一包含：

```json
{
  "ok": true,
  "summary": "...",
  "data": {},
  "stdout": "",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 123
}
```

并非所有字段每次都存在。

---

## 6. 文件系统边界

Workspace 是 Agent 的核心安全边界。

例如：

```text
D:\code_2026\demo
```

Workspace Mode 下：

允许：

```text
D:\code_2026\demo\src\a.py
D:\code_2026\demo\tests\test_a.py
```

默认禁止静默写入：

```text
C:\Windows\...
C:\Users\...\.ssh\...
D:\other-project\...
```

路径检查必须：

1. resolve。
2. normalize。
3. 检查符号链接 / junction 风险。
4. 检查最终路径是否在允许边界内。
5. 再执行读写。

不能只用字符串 startswith 做安全判断。

---

## 7. Shell Runner

Windows 第一版默认 PowerShell。

Shell Runner 需要支持：

- command
- cwd
- timeout
- env 白名单
- stdout stream
- stderr stream
- exit code
- process id
- cancellation
- terminate process tree

Agent 不需要为：

```text
pytest
npm
gradlew.bat
adb
cmake
```

分别写 Runner。

都通过通用 Shell Runner。

---

## 8. Permission Engine

输入：

```text
Tool Call
+
Permission Mode
+
Workspace
+
Command Risk
+
Path Risk
```

输出：

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

第一版风险示例：

### Low

- read_file
- list_directory
- git status
- git diff
- pytest

### Medium

- write_file
- apply_patch
- npm install
- pip install

### High

- 删除大量文件
- git reset --hard
- git clean -fd
- Workspace 外写文件
- 系统级安装
- 修改注册表
- shutdown / restart

不能只依赖字符串黑名单；第一版可以规则为主，但接口要允许后续升级。

---

## 9. Desktop 与 Agent 协议

建议统一 Envelope：

```json
{
  "type": "tool.completed",
  "request_id": "req_xxx",
  "thread_id": "thread_xxx",
  "turn_id": "turn_xxx",
  "timestamp": "ISO-8601",
  "payload": {}
}
```

### Desktop -> Agent

建议：

```text
client.hello
project.open
thread.create
thread.list
thread.get
turn.start
turn.cancel
approval.resolve
model.list
settings.update
```

### Agent -> Desktop

建议：

```text
server.ready
project.opened
thread.created
thread.loaded
turn.started
turn.delta
tool.requested
tool.started
tool.output
tool.completed
approval.required
file.changed
turn.completed
turn.failed
turn.cancelled
model.listed
error
```

协议对象建议后续放在：

```text
shared/protocol/
```

并尽量生成 Python / TypeScript 双端类型，避免两边手工维护后漂移。

---

## 10. 持久化

SQLite 由 Agent 侧统一管理。

不要让 Renderer 直接访问 SQLite。

建议表：

### projects

- id
- path
- name
- created_at
- last_opened_at

### threads

- id
- project_id
- title
- model
- permission_mode
- created_at
- updated_at

### turns

- id
- thread_id
- status
- user_prompt
- started_at
- completed_at

### messages

- id
- turn_id
- role
- content
- created_at

### tool_calls

- id
- turn_id
- tool_name
- arguments_summary
- status
- exit_code
- duration_ms

### approvals

- id
- turn_id
- tool_call_id
- decision
- created_at

### settings

- key
- value

---

## 11. Context 管理

v0.1.0 不建立复杂向量索引。

优先使用：

- 当前 Thread 最近消息。
- 当前 Turn Tool Results。
- Agent 主动读取的文件。
- 必要的 Git 状态。
- Workspace 元信息。

原则：

> 让 Agent 通过 Tool 主动获得上下文，而不是启动时把整个仓库塞给模型。

后续再增加：

- summary
- compaction
- semantic index
- repository map

---

## 12. Diff 设计

文件修改以后：

1. Tool 记录 changed path。
2. Agent 执行或内部计算 Git Diff。
3. 发送 `file.changed`。
4. Desktop 更新 Changed Files。
5. 用户可展开 Unified Diff。

第一版以 Git 仓库为主要场景。

非 Git Workspace 后续再实现内部 snapshot diff。

---

## 13. 进程模型

推荐第一版：

```text
Electron Main Process
  ├─ Renderer
  └─ spawn Python Agent Process
```

Agent 监听：

```text
127.0.0.1:<dynamic-port>
```

优先动态端口，避免固定端口冲突。

Electron 启动时：

1. 创建 Agent 子进程。
2. Agent 绑定本地端口。
3. Agent 返回 ready 信息。
4. Electron 建立 WebSocket。
5. Renderer 通过安全 IPC 获取连接状态。

退出时：

1. Stop active turn。
2. 关闭 WebSocket。
3. 让 Agent graceful shutdown。
4. 超时后强制结束子进程。

---

## 14. Electron 安全边界

必须：

- `contextIsolation: true`
- Renderer 禁止直接 Node 全权限访问。
- 使用 preload 暴露最小 API。
- 文件选择由 Main Process 处理。
- Agent Server 只监听 localhost。
- 本地协议加入 session token，避免其他本机网页随意连接 Agent。
- 禁止 Renderer 直接 spawn 任意进程。

---

## 15. 日志

建议：

```text
logs/
├─ desktop.log
├─ agent.log
└─ turns/
   └─ <turn_id>.log
```

生产版本日志进入用户数据目录，不写安装目录。

日志应支持后续：

- Debug mode
- Export diagnostics
- Turn replay
- Bug report

---

## 16. 错误模型

统一错误结构：

```json
{
  "code": "TOOL_TIMEOUT",
  "message": "Command exceeded timeout",
  "recoverable": true,
  "details": {}
}
```

Agent Loop 根据 recoverable 决定：

- 把错误交回模型继续处理。
- 终止 Turn。

用户界面必须区分：

- Tool command failed
- Agent internal failed
- Provider failed
- Permission denied
- User cancelled

不要把所有异常都显示成“执行失败”。

---

## 17. Repository 目录职责

```text
desktop/
  electron/       Electron main / preload
  src/            React Renderer

agent/
  core/           Agent Loop / Thread / Context
  llm/            Provider abstraction
  tools/          Tool implementations
  permissions/    Policy / Approval
  persistence/    SQLite
  server/         WebSocket / Protocol handling

shared/
  protocol/       Protocol schema / generated types

tests/
  fixtures/       故意包含 Bug 的测试项目
  integration/
  e2e/

scripts/
  dev/
  build/
  diagnostics/

docs/
  plans/
  design/
```

---

## 18. 后续可替换点

从 v0.1.0 起必须确保下面这些可以替换而不推倒重来：

### Python Agent -> Rust Agent

UI 协议不变即可替换。

### Ollama -> Online API

Provider 接口不变即可增加。

### Electron -> Other Desktop Shell

Agent Server 不变即可更换 UI。

### Local Workspace -> Remote Workspace

Tool backend 抽象后可以增加 SSH / container。

这也是本项目架构设计最重要的长期价值之一。

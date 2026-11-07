# 环境

Windows 安装版冻结后端通过健康与工作流模板检查，返回版本 1.0.0、协议 1.0.0、8 个模板。源树 origin/main 与 v1.0.0 均为 445d4edcba011663a74dce24829c7e8afb494bb6。

uv 0.11.2、Python 3.12.13、Node v24.14.0、Git 2.32.0.windows.2、Electron 38.8.6、Playwright Core 1.56.1。项目基础 uv 环境没有 pytest，验收通过 uv 的临时 pytest 9.2.0 依赖运行。

从安装版 SQLite 以只读方式发现模型配置，仅选启用的 Ollama 连接和指定模型。连接地址只在进程内使用。两端 /api/tags 均发现目标模型，生成流量经冻结 Agent。

两条已保存连接在本次检查中均为回环地址，既有连接可用。安装版配置位于 `%APPDATA%\local-coding-agent-desktop\local-coding-agent.sqlite3`，日志位于同目录下的 `logs`、`command-logs`、`verification`。验收只使用隔离后端的数据库和日志。

安装版的冻结 UIA worker 在独立 WinForms 窗口通过窗口发现、激活、输入、点击和保存回读。模型视觉及记事本分数只依据各自的 Agent 轮次，见结果文件。

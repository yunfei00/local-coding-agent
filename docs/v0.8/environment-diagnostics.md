# 环境智能诊断

environment_diagnose 使用原 ProcessManager 执行有界只读检查：Git/PATH、项目 npm 代理、Electron 安装文件、uv 环境、Python 模块、已配置 Provider /models 连通性。返回检查、问题类别和具体证据。检查执行成功不等于环境正常，更不等于业务测试通过。

Provider 检查仅访问已配置连接的模型列表，不能据此证明额度或工具能力。Python 模块以项目 .venv 为优先；没有项目环境时明确标记，不能将 Agent 自身依赖视作工程依赖。Electron 检查验证安装路径及可执行文件头，不启动应用。

environment_repair 沿用现有审批，允许的修复范围：移除项目 .npmrc 的 proxy/https-proxy；为项目子进程追加已安装 Git 的目录；存在 pyproject.toml 和 uv.lock 时执行 uv sync --locked --no-python-downloads 后重新检测模块。不会修改系统 PATH、全局 npm 配置或代理，不自动安装软件、删除全局缓存或提权。

仅实际复查通过后，将问题、修复范围及验证事实写入项目历史知识。权限拒绝、依赖/网络/超时分别保留错误，不让模型无止境尝试。隔离故障测试使用临时目录和局部配置，不改变开发电脑正常环境。

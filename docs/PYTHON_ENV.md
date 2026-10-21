# Python 环境

本项目统一使用 uv 管理仓库内的 `.venv`，由 `.python-version` 固定 Python 3.12，由 `uv.lock` 固定依赖解析结果。

## 安装与验证

```powershell
uv --version
uv sync --locked
uv run python -c "import sys, aiohttp, httpx2, mcp; print(sys.executable)"
uv run python -m unittest discover -s tests -v
```

Windows 解释器应为仓库内 `.venv\Scripts\python.exe`。Electron 开发模式使用这一解释器，不退回系统 Python；高级调试可显式设置 `LCA_PYTHON`。

首次准备前后端环境和检查：

```powershell
.\scripts\dev\bootstrap.ps1
.\scripts\dev\start.ps1
```

只安装打包依赖：

```powershell
uv sync --locked --extra packaging
uv run --no-sync pyinstaller --version
```

带 `--no-sync` 的命令复用当前 uv 环境，避免打包中途删除可选依赖。

完整本地验收：

```powershell
npm.cmd --prefix desktop ci
uv run python scripts/validation/check.py
```

脚本会识别 uv 和 Windows npm.cmd，输出编号错误，并把完整日志和 JSON 报告保存在本地 `validation-reports`。不要因裸系统 Python 缺少模块而误判项目依赖缺失。

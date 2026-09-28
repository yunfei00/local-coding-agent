# Python Environment

Local Coding Agent uses a repository-local Python virtual environment managed by **uv**.

## Windows setup

Install uv once:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open a new PowerShell window and verify:

```powershell
uv --version
```

Then bootstrap the project:

```powershell
.\scripts\dev\bootstrap.ps1
```

The bootstrap script pins Python 3.12 through uv, creates:

```text
.venv\Scripts\python.exe
```

and installs the Agent dependencies into that environment.

## Runtime rule

Electron launches the Agent only with the repository virtual environment:

```text
<repo>\.venv\Scripts\python.exe
```

It does not fall back to the Windows system Python.

This prevents missing-package errors and avoids polluting or depending on the user's global Python installation.

For advanced debugging only, `LCA_PYTHON` can explicitly override the interpreter.

## Diagnostics

```powershell
.\scripts\diagnostics\check-env.ps1
```

The output should show both:

```text
[OK] uv: ...
[OK] project .venv: Python 3.12.x
```

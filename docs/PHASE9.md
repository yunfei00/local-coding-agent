# Phase 9 - Windows Packaging and v0.1.0 Release

Status: **implemented on `feature/v0.1-mvp`; package artifact CI is the release gate**

## Packaging architecture

Development mode:

```text
Electron
  -> repository .venv Python
  -> python -m agent.server.main --port 0
```

Packaged mode:

```text
LocalCodingAgent.exe
  -> resources/agent/lca-agent.exe
  -> embedded Python runtime + Agent dependencies
  -> dynamic localhost port
```

The installed application does not require a system Python installation.

PyInstaller is intentionally used in onedir mode for v0.1.0. The whole Agent folder is bundled into Electron `extraResources`; the end user still receives a normal NSIS installer or one portable EXE.

## Runtime paths

- Agent executable: `process.resourcesPath/agent/lca-agent.exe`
- SQLite/user data: Electron `app.getPath("userData")`
- runtime logs: `<userData>/logs/desktop.log` and `agent.log`
- Ollama: `http://127.0.0.1:11434`
- Agent server: dynamic localhost port selected with `--port 0`

The Desktop never exposes the Agent session token to the Renderer.

## Windows artifacts

The Windows x64 build produces:

```text
Local-Coding-Agent-0.1.0-x64-Setup.exe
Local-Coding-Agent-0.1.0-x64-Portable.exe
SHA256SUMS.txt
```

The installer is assisted rather than silent/one-click and allows changing the installation directory.

v0.1.0 is unsigned, so Windows SmartScreen may show an unknown-publisher warning. Code signing can be added later without changing the runtime architecture.

## Local build

From Windows PowerShell:

```powershell
cd D:\code_2026\local-coding-agent
git checkout feature/v0.1-mvp
git pull --ff-only origin feature/v0.1-mvp

.\scripts\build\package-windows.ps1
```

The script prepares the Python packaging environment, runs the full Python suite, builds `lca-agent.exe`, starts that packaged Agent and checks its real HTTP health endpoint, runs Desktop checks, creates NSIS + portable packages, then starts the actual packaged `LocalCodingAgent.exe`. The Desktop smoke test requires the bundled Agent to connect with `phase9`, closes the Desktop, and verifies that no new `lca-agent` process was left behind. It also writes `SHA256SUMS.txt` for the Setup and Portable executables.

## GitHub Actions

`.github/workflows/package-windows.yml` builds the same artifacts on `windows-latest`.

During Phase 9, `.github/workflows/package-windows.yml` is a **candidate-only** workflow. It runs for relevant pushes to `feature/v0.1-mvp`, has read-only repository contents permission, and uploads the Setup EXE, Portable EXE and checksum file as a temporary Actions artifact.

Formal publishing is isolated in `.github/workflows/release.yml`. It only runs for `v*` tags, requires the root and Desktop versions to match, and requires the tag to equal `v<desktop version>`. Only after the full packaging and packaged-Desktop smoke test passes does it create or update the GitHub Release.

## Fresh-machine acceptance

Use a Windows 10/11 machine that does not rely on this repository's Python environment.

- installer launches and installs;
- portable EXE launches;
- Desktop reports Agent Connected;
- Agent protocol reports `phase9`;
- Ollama offline state is explicit when Ollama is not running;
- once Ollama is running, local models can be refreshed;
- project folder can be opened;
- a Turn can call tools;
- Stop works;
- close/reopen restores project/thread/model/permission state;
- logs are written to userData/logs;
- no repository `.venv` is needed.

## Release gate

Only after the packaged artifact passes the fresh-machine smoke test should `feature/v0.1-mvp` be merged into `main` and tagged `v0.1.0`.

"""One owned subprocess runtime for foreground commands and development servers."""
from __future__ import annotations

import asyncio
import codecs
from contextlib import suppress
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

from agent.tools.base import ToolError, ToolResult
from agent.tools.stream import ToolStreamState
from agent.tools.windows_job import WindowsJob

MAX_OUTPUT_CHARS = 200_000
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 86400


def shell_command(shell="auto"):
    if shell not in {"auto", "powershell", "cmd", "bash"}:
        raise ToolError("INVALID_SHELL", "shell must be auto, powershell, cmd or bash")
    shell = ("powershell" if os.name == "nt" else "bash") if shell == "auto" else shell
    if shell == "cmd":
        if os.name != "nt":
            raise ToolError("SHELL_UNAVAILABLE", "CMD is supported on Windows only")
        return "cmd.exe", ["/d", "/s", "/c"]
    if shell == "powershell":
        binary = shutil.which("powershell.exe" if os.name == "nt" else "pwsh")
        if not binary:
            raise ToolError("SHELL_UNAVAILABLE", "PowerShell is not installed")
        return binary, ["-NoProfile", "-NonInteractive", "-Command"]
    binary = shutil.which("bash")
    if not binary:
        raise ToolError("SHELL_UNAVAILABLE", "Bash is not installed")
    return binary, ["-c"]


async def terminate_process_tree(process):
    """A POSIX group may still exist after its original shell has exited."""
    if os.name == "nt":
        if process.returncode is not None:
            return "already_exited"  # The Job handles descendants on Windows.
        try:
            killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            await asyncio.wait_for(killer.wait(), 5)
            if killer.returncode and process.returncode is None:
                process.kill()
        except (OSError, asyncio.TimeoutError):
            with suppress(ProcessLookupError):
                process.kill()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), 3)
        return "taskkill"
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    # Do not return when only the root exited: grandchildren can ignore SIGTERM.
    await asyncio.sleep(.1)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), 3)
    # SIGKILL is asynchronous too. The shell may already have exited while
    # descendants still run. Verify only its process group; zombies are dead and
    # have released their descriptors, even if init has not reaped them yet.
    deadline = time.monotonic()+5
    while True:
        active = False
        if Path('/proc').is_dir():
            for item in Path('/proc').iterdir():
                if not item.name.isdigit():
                    continue
                try:
                    fields = (item/'stat').read_text(encoding='utf-8',errors='replace').rsplit(')',1)[1].split()
                    if int(fields[2]) == process.pid and fields[0] not in {'Z','X'}:
                        active = True
                        break
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
        else:
            try:
                os.killpg(process.pid,0)
                active = True
            except ProcessLookupError:
                pass
        if not active:
            break
        if time.monotonic() >= deadline:
            raise ToolError('PROCESS_CLEANUP_FAILED','Owned process group did not finish terminating')
        await asyncio.sleep(.02)
    return "sigkill"


@dataclass
class ProcessSession:
    id: str
    owner: str
    process: asyncio.subprocess.Process
    job: WindowsJob
    shell: str
    command: str
    cwd: str
    timeout: int
    directory: Path
    started: float = field(default_factory=time.monotonic)
    started_at: float = field(default_factory=time.time)
    state: str = "running"
    stdout: str = ""
    stderr: str = ""
    cursor: int = 0
    chunks: list = field(default_factory=list)
    log_bytes: int = 0
    log_truncated: bool = False
    output_truncated: bool = False
    stream: ToolStreamState = field(default_factory=ToolStreamState)
    task: asyncio.Task | None = None
    readers: list = field(default_factory=list)
    error: str | None = None
    cleanup_detail: str | None = None
    stopping: bool = False
    on_output: object = None
    on_raw_output: object = None
    persist_output: bool = True

    def result(self, *, cursor=0):
        events = [c for c in self.chunks if c["cursor"] > cursor]
        return ToolResult(ok=self.state not in {"failed", "timed_out", "output_error", "cleanup_failed"},
            summary=f"Process {self.id}: {self.state}; exit={self.process.returncode}",
            stdout=self.stdout, stderr=self.stderr, exit_code=self.process.returncode,
            duration_ms=round((time.monotonic() - self.started) * 1000),
            data={"process_id": self.id, "pid": self.process.pid, "state": self.state,
                  "shell": self.shell, "cwd": self.cwd, "command": self.command,
                  "next_cursor": self.cursor, "chunks": events,
                  "output_omitted": bool(self.chunks and cursor < self.chunks[0]["cursor"] - 1),
                  "log_path": str(self.directory / "output.jsonl") if self.persist_output else None, "log_truncated": self.log_truncated,
                  "output_truncated": self.output_truncated,
                  "output_drain_timed_out": self.error == "OUTPUT_DRAIN_TIMEOUT",
                  "job_cleanup":self.job.last_cleanup,
                  "error_code": {"timed_out":"COMMAND_TIMEOUT", "output_error":"COMMAND_OUTPUT_FAILED", "failed":"COMMAND_EXIT_NONZERO", "cleanup_failed":"PROCESS_CLEANUP_FAILED"}.get(self.state),
                  "metadata_path": str(self.directory / "process.json"), "stream": self.stream.snapshot()})


class ProcessManager:
    def __init__(self, workspace, log_root=None, *, persist_output=True):
        self.persist_output=persist_output
        self.project_path_prefix=list(getattr(workspace,'project_path_prefix',[]))
        self.workspace = workspace
        base = Path(os.getenv("LCA_DATA_DIR") or Path.home() / ".local-coding-agent")
        self.log_root = Path(log_root) if log_root else base / "command-logs"
        self.sessions = {}
        self.scratch_workdirs = {}
        self.scratch_sources = {}

    def scratch_cwd(self, owner):
        if not owner:
            raise ToolError("INVALID_COMMAND_CWD", "An owned task is required for an isolated command")
        if owner not in self.scratch_workdirs:
            parent = self.workspace.root / ".runtime"
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise ToolError("INVALID_COMMAND_CWD", "The scratch directory cannot be a link")
            parent.mkdir(exist_ok=True)
            if parent.resolve() != parent:
                raise ToolError("INVALID_COMMAND_CWD", "The scratch directory must remain in the workspace")
            self.scratch_workdirs[owner] = tempfile.TemporaryDirectory(prefix="command-", dir=parent)
            self.scratch_sources[owner] = {}
        return self.scratch_workdirs[owner].name

    def mirror_scratch_sources(self, owner, cwd):
        from agent.core.project_files import ProjectFiles
        policy = ProjectFiles(self.workspace.root)
        visible = list(policy.paths(maximum=129))
        mirrored = self.scratch_sources[owner]
        current = {}
        remaining = 4 * 1024 * 1024
        for path in visible if len(visible) <= 128 else ():
            if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            source = policy.read(path)
            if source is None:
                continue
            content = source.encode("utf-8")
            remaining -= len(content)
            if remaining < 0:
                break
            target = cwd / path.relative_to(self.workspace.root)
            if not target.resolve().is_relative_to(cwd) or target.is_symlink():
                continue
            if target.exists() and (target not in mirrored or target.stat().st_size != len(mirrored[target])
                                    or target.read_bytes() != mirrored[target]):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            current[target] = content
        for target, content in mirrored.items():
            if (target not in current and target.resolve().is_relative_to(cwd) and not target.is_symlink()
                    and target.is_file() and target.stat().st_size == len(content)
                    and target.read_bytes() == content):
                target.unlink()
        self.scratch_sources[owner] = current

    async def _emit(self, session, event, **data):
        if session.on_output:
            await session.on_output(session.stream.meta(event, process_id=session.id, pid=session.process.pid, **data))

    async def _consume(self, session, stream, label):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            raw = await stream.read(4096)
            text = decoder.decode(raw, final=not raw)
            if text:
                session.output_truncated |= len(getattr(session, label)) + len(text) > MAX_OUTPUT_CHARS
                setattr(session, label, (getattr(session, label) + text)[-MAX_OUTPUT_CHARS:])
                session.cursor += 1
                item = {"cursor": session.cursor, "stream": label, "text": text}
                session.chunks.append(item)
                while sum(len(c["text"]) for c in session.chunks) > MAX_OUTPUT_CHARS:
                    session.chunks.pop(0)
                line = json.dumps(item, ensure_ascii=False) + "\n"
                size = len(line.encode("utf-8"))
                if not session.persist_output:
                    pass
                elif session.log_bytes + size <= MAX_LOG_BYTES:
                    with (session.directory / "output.jsonl").open("a", encoding="utf-8") as log:
                        log.write(line)
                    session.log_bytes += size
                else:
                    session.log_truncated = True
                if session.on_raw_output:
                    await session.on_raw_output(label, text)
                if session.on_output:
                    for event in session.stream.output(label, text):
                        await session.on_output({**event, "process_id": session.id, "pid": session.process.pid})
            if not raw:
                break

    async def launch(self, arguments, *, owner="", on_output=None, on_raw_output=None, environment=None, argv=None, reuse_running=False):
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip() or len(command) > 32768:
            raise ToolError("INVALID_COMMAND", "Provide a nonempty command of at most 32768 characters")
        timeout = arguments.get("timeout_seconds", 120)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_SECONDS:
            raise ToolError("INVALID_TIMEOUT", "timeout_seconds must be 1..86400")
        try:
            cwd = self.workspace.resolve(arguments.get("cwd") or ".", must_exist=True)
        except (FileNotFoundError, PermissionError) as exc:
            raise ToolError("WORKING_DIRECTORY_UNAVAILABLE", "Working directory is missing or inaccessible") from exc
        if not cwd.is_dir():
            raise ToolError("NOT_DIRECTORY", "Command cwd must be a directory")
        if argv:
            executable, prefix = argv[0], []
        else:
            executable, prefix = shell_command(arguments.get("shell", "auto"))
        if reuse_running:
            for existing in self.sessions.values():
                if (existing.owner == owner and existing.state == 'running' and
                    existing.process.returncode is None and existing.command == command and
                    existing.cwd == self.workspace.display(cwd) and existing.shell == Path(executable).stem):
                    return existing
        if sum(s.owner == owner and s.state == "running" for s in self.sessions.values()) >= 8 or len(self.sessions) >= 64:
            raise ToolError("PROCESS_LIMIT", "Stop existing processes before starting more")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        if arguments.get("isolated_cwd") is True:
            env["LCA_PROJECT_ROOT"] = str(self.workspace.root)
        if self.project_path_prefix:env['PATH']=os.pathsep.join([*self.project_path_prefix,env.get('PATH','')])
        if self.project_path_prefix and argv:
            # Windows resolves argv[0] before applying the child's environment.
            # Resolve only against the approved project PATH, without changing os.environ.
            resolved=shutil.which(argv[0],path=env['PATH'])
            if resolved:argv=[resolved,*argv[1:]]
        if environment:
            if set(environment) - {"PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE"}:
                raise ToolError("INVALID_COMMAND_ENVIRONMENT", "Only internal Python cache controls are supported")
            env.update(environment)
        wire = command
        if prefix and prefix[-1] == "-Command":
            wire = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
                    "$OutputEncoding=[Console]::OutputEncoding; & {\n" + command + "\n}; if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }")
        kwargs = {"cwd": str(cwd), "env": env, "stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.PIPE}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 4  # suspended until Job ownership
        else:
            kwargs["start_new_session"] = True
        ident = "process_" + uuid.uuid4().hex
        directory = self.log_root / ident
        directory.mkdir(parents=True)
        if prefix and prefix[-1] == "/c":
            # Avoid C-runtime quote escaping inside CMD. CALL expands just the
            # quoted script path; script contents retain native CMD semantics.
            script = directory / "command.cmd"
            script.write_text("@echo off\n@chcp 65001 >nul\n" + command + "\nexit /b %errorlevel%\n", encoding="utf-8")
            env["LCA_INTERNAL_SCRIPT"] = '"' + str(script) + '"'
            wire = "call %LCA_INTERNAL_SCRIPT%"
        try:
            process = await asyncio.create_subprocess_exec(*(argv or (executable, *prefix, wire)), **kwargs)
        except OSError as exc:
            raise ToolError("PROCESS_START_FAILED", f"Could not start {executable}: {exc}") from exc
        try:
            job = WindowsJob(process.pid)
            job.resume(process.pid)
        except OSError as exc:
            if 'job' in locals():
                job.close()
            await terminate_process_tree(process)
            process._transport.close()
            raise ToolError("PROCESS_ISOLATION_FAILED", "Could not own the process tree before execution") from exc
        session = ProcessSession(ident, owner, process, job, Path(executable).stem, command, self.workspace.display(cwd), timeout, directory,
                                 on_output=on_output, on_raw_output=on_raw_output,persist_output=self.persist_output)
        self.sessions[ident] = session
        # Monitor is created before any cancellable callback or stream consumption.
        session.task = asyncio.create_task(self._monitor(session), name=ident)
        return session

    async def _monitor(self, s):
        reason = None
        try:
            await self._emit(s, "process_started", command=s.command, cwd=s.cwd, timeout_seconds=s.timeout, shell=s.shell)
            s.readers = [asyncio.create_task(self._consume(s, s.process.stdout, "stdout")),
                         asyncio.create_task(self._consume(s, s.process.stderr, "stderr"))]
            async with asyncio.timeout(s.timeout):
                # Process.wait can wait for inherited pipes, even after the root exited.
                while s.process.returncode is None:
                    for reader in s.readers:
                        if reader.done() and not reader.cancelled() and reader.exception():
                            raise reader.exception()
                    await asyncio.sleep(.03)
        except TimeoutError:
            reason, s.state = "timeout", "timed_out"
        except asyncio.CancelledError:
            reason, s.state = s.state if s.state != "running" else "user_cancelled", "stopped"
        except Exception as exc:
            reason, s.state, s.error = "output_error", "output_error", type(exc).__name__
        finally:
            s.stopping = True
            cleanup_stage = 'termination_event'
            try:
                if reason:
                    with suppress(Exception):
                        await self._emit(s, "process_terminating", reason=reason)
                cleanup_stage = 'job_exit_confirmation'
                await s.job.terminate_and_wait()
                cleanup_stage = 'root_exit_confirmation'
                method = await terminate_process_tree(s.process)
                cleanup_stage = 'output_drain'
                if s.readers:
                    try:
                        reader_results = await asyncio.wait_for(asyncio.gather(*s.readers, return_exceptions=True), 3)
                    except TimeoutError:
                        # A slow/disconnected output consumer must not turn a
                        # successful explicit Stop into an uncaught TimeoutError
                        # that is thrown again on every scope cleanup. The Job
                        # has already been terminated. Normal command completion
                        # with incomplete output remains a verification failure.
                        s.error, s.output_truncated = "OUTPUT_DRAIN_TIMEOUT", True
                        if s.state == "running":
                            reason, s.state = "output_drain_timeout", "output_error"
                        reader_results = []
                    failures = [value for value in reader_results if isinstance(value, Exception)]
                    if failures and s.state == "running":
                        reason, s.state, s.error = "output_error", "output_error", type(failures[0]).__name__
                if s.state == "running":
                    s.state = "exited" if s.process.returncode == 0 else "failed"
                with suppress(Exception):
                    cleanup_stage = 'exit_event'
                    await self._emit(s, "process_terminated" if reason else "process_exited", reason=reason,
                                     method=method, exit_code=s.process.returncode, duration_ms=round((time.monotonic()-s.started)*1000))
                cleanup_stage = 'finished'
            except Exception as exc:
                # Keep the failing stage in scoped metadata. No command output,
                # environment or credentials are included in this diagnosis.
                s.error = f'PROCESS_CLEANUP_FAILED:{cleanup_stage}:{type(exc).__name__}'
                s.state = 'cleanup_failed'
                if cleanup_stage == 'job_exit_confirmation' and isinstance(exc,TimeoutError):
                    s.cleanup_detail = str(exc)[:400]
                raise ToolError('PROCESS_CLEANUP_FAILED',
                    f'Owned process cleanup failed at {cleanup_stage}: {type(exc).__name__}',
                    details={'cleanup_stage':cleanup_stage,'job_cleanup':s.job.last_cleanup}) from exc
            finally:
                s.job.close()
                for reader in s.readers:
                    if not reader.done():
                        reader.cancel()
                await asyncio.gather(*s.readers, return_exceptions=True)
                s.process._transport.close()
                metadata = {"process_id": s.id, "pid": s.process.pid, "owner": s.owner, "state": s.state,
                            "exit_code": s.process.returncode, "shell": s.shell, "log_truncated": s.log_truncated,
                            "error": s.error, "cleanup_stage": cleanup_stage, "cleanup_detail":s.cleanup_detail,
                            "job_cleanup":s.job.last_cleanup,
                            "cleanup_reason": reason, "workspace": str(self.workspace.root),
                            "started_at": s.started_at, "ended_at": time.time(),
                            "duration_ms": round((time.monotonic()-s.started)*1000)}
                (s.directory / "process.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, ident, owner=""):
        session = self.sessions.get(ident)
        if not session or session.owner != owner:
            raise ToolError("PROCESS_NOT_FOUND", "Process handle does not belong to this execution scope")
        return session

    async def stop(self, ident, *, owner="", reason="user_stopped"):
        s = self.get(ident, owner)
        if not s.task.done() and not s.stopping:
            # A task cancelled before its first instruction would skip its finally.
            await asyncio.sleep(0)
            if not s.stopping:
                s.stopping = True
                s.state = reason
                s.task.cancel()
        await asyncio.shield(s.task)
        return s.result()

    async def close_owner(self, owner):
        results = []
        errors = []
        for ident, s in list(self.sessions.items()):
            if s.owner == owner:
                try:
                    await self.stop(ident, owner=owner, reason="scope_finished")
                    results.append(s.result().data)
                except Exception as exc:
                    errors.append(f'{s.id}: {s.error or type(exc).__name__}')
                finally:
                    self.sessions.pop(ident, None)
        if errors:
            raise ToolError("PROCESS_CLEANUP_FAILED", "Process cleanup failed; inspect process logs: " + ", ".join(errors))
        scratch = self.scratch_workdirs.pop(owner, None)
        self.scratch_sources.pop(owner, None)
        if scratch:
            try:
                scratch.cleanup()
            except OSError as exc:
                raise ToolError("PROCESS_CLEANUP_FAILED", "Could not clean the owned scratch directory") from exc
        return results

    async def close(self):
        for owner in {s.owner for s in self.sessions.values()} | self.scratch_workdirs.keys():
            await self.close_owner(owner)

    async def run(self, arguments, *, owner="", **kwargs):
        isolated = arguments.get("isolated_cwd", False)
        if not isinstance(isolated, bool) or (isolated and arguments.get("cwd") not in (None, "", ".")):
            raise ToolError("INVALID_COMMAND_CWD", "Use isolated_cwd without a custom cwd")
        if isolated:
            try:
                scratch = Path(self.scratch_cwd(owner))
                self.mirror_scratch_sources(owner, scratch)
            except OSError as exc:
                raise ToolError("INVALID_COMMAND_CWD", "Could not prepare the owned scratch directory") from exc
            arguments = {**arguments, "cwd": str(scratch)}
        session = await self.launch(arguments, owner=owner, **kwargs)
        try:
            await asyncio.shield(session.task)
        except asyncio.CancelledError:
            await self.stop(session.id, owner=owner, reason="user_cancelled")
            raise
        finally:
            self.sessions.pop(session.id, None)
        result = session.result()
        if session.state in {"timed_out", "output_error"}:
            raise ToolError("COMMAND_TIMEOUT" if session.state == "timed_out" else "COMMAND_OUTPUT_FAILED",
                            "Command timed out; its process tree was terminated" if session.state == "timed_out" else "Command output failed; process tree terminated",
                            details=result.to_dict())
        return result

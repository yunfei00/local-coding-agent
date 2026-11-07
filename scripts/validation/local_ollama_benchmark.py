import asyncio
import json
import os
import pathlib
import queue
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

import aiohttp

from agent.core.version import APP_VERSION

P = pathlib.Path
MODELS = ("gemma4:31b", "qwen3.5:9b")
CASES = {
    "A": "Read seed.txt, create draft.txt with its content, rename draft.txt to final.txt, append a newline and READY, delete obsolete.txt. Create ref.txt containing final.txt. Try reading absent.txt and recover without creating it.",
    "B": "Implement items.py CLI: add NAME, list, update OLD NEW, delete NAME. Store a JSON array of names in items.json in the working directory. list prints one name per line. Reject blank or duplicate names and missing update/delete targets with nonzero exit; preserve storage on errors.",
    "C": "Identify Python and pytest availability, run python -m pytest -q, diagnose the failing assertion and repair mathbox.py, then run python -m pytest -q again. Keep test_mathbox.py unchanged.",
    "D": "Build slug.py with function slugify(text): lowercase, replace each run of non-ASCII-alphanumeric characters with one hyphen and trim edge hyphens. Add your own pytest tests and run python -m pytest -q. Repair any failures.",
    "E": "Initialize Git, create branch benchmark-work, commit baseline note.txt, append NEW to note.txt, inspect git diff, modify scratch.txt then restore scratch.txt from the commit. Leave note.txt change uncommitted. Use only repository-local identity and never push.",
}
TEST = "from mathbox import add\ndef test_add():\n    assert add(2, 3) == 5\n"
GUI_CASES = ("F-vision", "F-desktop")
NOTEPAD_PHRASE = "Local Coding Agent Gemma 桌面自动化测试成功"
PROJECTS = {
    "P1": "From scratch implement a Python todo CLI todo.py with add NAME, list, update OLD NEW, delete NAME. Persist a JSON array in todos.json, reject blank or duplicate names and nonexistent targets with nonzero exit. list prints one name per line. Include pytest tests and a Chinese README.md with usage. Run the tests and fix failures.",
    "P2": "From scratch implement Python scan.py DIRECTORY OUTPUT.csv. Recursively scan files, print counts by lowercase extension as JSON to stdout, hash each file with SHA256, and export CSV with columns path (relative to DIRECTORY), extension, sha256, duplicate (true for every member of a repeated digest). Exclude the output file itself. Include and run pytest tests. Fix failures.",
    "P3": "From scratch build a Windows Tkinter calculator in calculator.py with create_app() returning a Tk window. Use direct child Button widgets labelled 0–9, +, -, *, /, =, C and a direct child Label showing the result. Show Error on division by zero. Add GUI pytest tests and run them. Do not touch any existing window or user file.",
}

def child_environment():
    sensitive = re.compile(r"api.?key|secret|credential|password|token", re.I)
    return {key: value for key, value in os.environ.items()
            if not sensitive.search(key) or key == "LCA_CONTEXT_RESERVED_OUTPUT_TOKENS"}


def case_environment(root):
    temporary = root / "temp"
    temporary.mkdir(exist_ok=True)
    return {**child_environment(), "TMP": str(temporary), "TEMP": str(temporary), "TMPDIR": str(temporary)}

class OwnedNotepad:
    @staticmethod
    def owns_title(title, filename):
        return title.removeprefix("*").startswith(filename + " - ")

    def __init__(self, filename):
        import win32gui
        import win32process
        self.filename = filename
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            windows = []
            win32gui.EnumWindows(lambda hwnd, _: windows.append(hwnd), None)
            matches = [hwnd for hwnd in windows if win32gui.IsWindowVisible(hwnd)
                       and self.owns_title(win32gui.GetWindowText(hwnd), filename)]
            if len(matches) == 1:
                self.hwnd = matches[0]
                self.pid = win32process.GetWindowThreadProcessId(self.hwnd)[1]
                return
            time.sleep(.2)
        raise RuntimeError("notepad_window_not_proven")

    def poll(self):
        import win32gui
        import win32process
        if not win32gui.IsWindow(self.hwnd):
            return 0
        if win32process.GetWindowThreadProcessId(self.hwnd)[1] != self.pid:
            return 0
        return None if self.owns_title(win32gui.GetWindowText(self.hwnd), self.filename) else 0

    def terminate(self):
        import win32gui
        import win32con
        if self.poll() is None:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

    def minimize_if_foreground(self):
        if self.poll() is None and foreground_pid() == self.pid:
            import win32con
            import win32gui
            win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while self.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        if self.poll() is None:
            raise RuntimeError("owned_notepad_close_pending")

def start_gui(case, root, work, code):
    from agent.desktop.resources import require_resources
    from agent.desktop.session import require_interactive_session
    require_resources()
    require_interactive_session()
    if case == "F-vision":
        source = P(__file__).resolve().parents[2] / "manual-fixtures/v10-release-app/Main.cs"
        original = source.read_text(encoding="utf-8")
        badge = ('form.Paint += (sender, e) => e.Graphics.DrawString("' + code +
                 '", new System.Drawing.Font("Arial", 24), System.Drawing.Brushes.Black, 220, 64);')
        file = root / "Badge.cs"
        file.write_text(original.replace("Application.Run(form);", badge + "Application.Run(form);"), encoding="utf-8")
        compiler = P(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        binary = root / "Badge.exe"
        subprocess.run([str(compiler),"/nologo","/target:exe","/out:"+str(binary),
                        "/reference:System.Windows.Forms.dll","/reference:System.Drawing.dll",str(file)],
                       check=True, capture_output=True, timeout=20)
        proc = subprocess.Popen([str(binary), str(root)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        prompt = (f"Visual-only GUI test. Find the isolated window with PID {proc.pid} using desktop_list_windows with that exact pid. "
                  "Take its window screenshot with share_with_model=true. Read the six-digit code drawn in pixels and reply with it. "
                  "Use only desktop_list_windows and desktop_screenshot.")
    else:
        for _ in range(8):
            listed = subprocess.check_output(["tasklist","/FI","IMAGENAME eq Notepad.exe","/FO","CSV","/NH"], text=True, errors="replace")
            if not re.search(r'^"notepad\.exe"',listed,re.I|re.M):
                break
            time.sleep(.25)
        else:
            raise RuntimeError("existing_notepad")
        file = work / ("desktop-test.txt" if case == "N" else f"benchmark-note-{code}.txt")
        file.write_text("BASE",encoding="utf-8")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 4
        subprocess.Popen([str(P(os.environ["WINDIR"])/"System32/notepad.exe"),str(file)], startupinfo=startup)
        proc = OwnedNotepad(file.name)
        proc.minimize_if_foreground()
        prompt = (f"仅桌面操作。用 desktop_list_windows 的 pid 参数查找 PID {proc.pid} 的记事本窗口，"
                  f"激活该窗口，查看 UIA 控件，点击编辑区，输入 {code} 替换 BASE，再按 Ctrl+S。"
                  "禁止读取源码或用文件工具写入。")
    return proc, code, prompt

def gui_approval(tool, args, pid, case, editors, expected, session_token):
    if tool == "desktop_list_windows":
        return args.get("pid") == pid
    target = args.get("target_window", {})
    if target.get("pid") != pid:
        return False
    if case == "F-vision":
        return tool == "desktop_screenshot" and args.get("scope","window") == "window" and args.get("share_with_model") is True
    if tool == "desktop_keypress":
        return str(args.get("keys","")).upper() in {"CTRL+A","CTRL+S"}
    if tool in {"desktop_focus_window","desktop_inspect"}:
        return True
    if tool not in {"desktop_click","desktop_type_text"} or args.get("method") == "coordinate":
        return False
    selector = args.get("selector") or {}
    match = bool(selector) and any(all(control.get(k) == v for k,v in selector.items()) for control in editors)
    if not match or tool == "desktop_click":
        return match
    import hmac
    from agent.desktop.runtime import text_confirmation
    proof = args.get("text_confirmation")
    return isinstance(proof, str) and hmac.compare_digest(
        proof, text_confirmation(session_token, args["window_id"], expected))

def foreground_pid():
    import win32gui
    import win32process
    handle = win32gui.GetForegroundWindow()
    return win32process.GetWindowThreadProcessId(handle)[1] if handle else None


async def activate_foreground_fixture(pid):
    from agent.desktop.runtime import DesktopRuntime
    runtime = DesktopRuntime()
    owner = "foreground-fixture"
    try:
        listed = await runtime.execute("desktop_list_windows", {"pid": pid}, owner=owner, authorized=True)
        windows = [window for window in listed.data["windows"]
                   if window["title"] == "LCA focus fixture" and window["pid"] == pid]
        if len(windows) != 1:
            raise RuntimeError("foreground_fixture_not_proven")
        await runtime.execute("desktop_focus_window", {"window_id": windows[0]["window_id"]},
                              owner=owner, authorized=True)
        if foreground_pid() != pid:
            raise RuntimeError("foreground_fixture_not_active")
    finally:
        await runtime.close_owner(owner)

def discover(*, profiles=False):
    data = P(os.environ["APPDATA"]) / "local-coding-agent-desktop"
    with sqlite3.connect((data / "local-coding-agent.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        def setting(key):
            row = db.execute("select value from settings where key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        catalog = setting("models.catalog.v1")
        runtime = {
            "context_window": setting("runtime.ollama_context_window"),
            "model_steps": setting("runtime.max_model_steps"),
            "request_seconds": (setting("orchestration.config") or {}).get("budget", {}).get("request_seconds"),
        } if profiles else None
    connections = {c["connection_id"]: c for c in catalog["connections"]
                   if c["provider_type"] == "ollama" and c.get("enabled", True)}
    urls = {}
    for model in MODELS:
        for profile in catalog["profiles"]:
            if profile["model_id"] == model and profile["connection_id"] in connections:
                url = connections[profile["connection_id"]]["base_url"]
                parsed = urllib.parse.urlsplit(url)
                if parsed.scheme in ("http", "https") and not any((parsed.username, parsed.password, parsed.query, parsed.fragment)):
                    urls[model] = (url.rstrip("/"), profile, runtime) if profiles else url.rstrip("/")
                    break
    return urls

def seed(work, case):
    files = {
        "A": {"seed.txt": "SOURCE", "obsolete.txt": "remove me"},
        "C": {"mathbox.py": "def add(a, b): return a-b\n", "test_mathbox.py": TEST},
        "E": {"note.txt": "BASE\n", "scratch.txt": "KEEP\n"},
    }
    for name, contents in files.get("C" if case == "R" else case, {}).items():
        (work / name).write_text(contents, encoding="utf-8")

def score(work, case, events):
    def read(name):
        return (work / name).read_text(encoding="utf-8")
    def run(*args, good=True):
        p = subprocess.run(args, cwd=work, env=case_environment(work.parent),
                           capture_output=True, text=True, timeout=20)
        assert (p.returncode == 0) == good, "unexpected_command_exit_status"
        return p.stdout.strip()
    py = sys.executable
    commands = [x for x in events if x["name"] == "run_command"]
    if case == "A":
        assert read("final.txt").strip() == "SOURCE\nREADY"
        assert read("ref.txt").strip() == "final.txt"
        assert not any((work / n).exists() for n in ("draft.txt", "obsolete.txt", "absent.txt"))
        assert any(x["name"] == "read_file" and not x["ok"] for x in events)
    elif case == "B":
        def cli(*args, good=True):
            return run(py, "items.py", *args, good=good)
        assert not (work / "items.json").exists() or json.loads(read("items.json")) == [], "cli_delivered_with_test_data"
        cli("add", "Alpha")
        cli("add", "Beta")
        cli("add", "Alpha", good=False)
        cli("add", " ", good=False)
        cli("update", "missing", "C", good=False)
        cli("update", "Alpha", "Gamma")
        assert cli("list").splitlines() == ["Gamma", "Beta"]
        cli("delete", "Beta")
        cli("delete", "missing", good=False)
        assert json.loads(read("items.json")) == ["Gamma"]
    elif case in {"C", "R"}:
        assert read("test_mathbox.py") == TEST
        assert any(x["exit_code"] == 1 for x in commands)
        assert any(x["exit_code"] == 0 for x in commands)
        run(py, "-m", "pytest", "-q")
    elif case == "D":
        assert any(x["exit_code"] == 0 for x in commands)
        run(py, "-m", "pytest", "-q")
        run(py, "-c", "from slug import slugify; assert slugify(' Hi__THERE! ')=='hi-there'; assert slugify('é---')==''; assert slugify('a42')=='a42'")
    elif case == "E":
        assert run("git", "branch", "--show-current") == "benchmark-work", "unexpected_git_branch"
        try:
            assert run("git", "show", "HEAD:scratch.txt") == "KEEP"
        except AssertionError:
            raise AssertionError("git_baseline_missing_or_incorrect_scratch") from None
        assert read("scratch.txt").strip() == "KEEP", "git_restore_content_mismatch"
        assert "+NEW" in run("git", "diff", "--", "note.txt"), "git_diff_missing_change"
        assert any(x["name"] in ("git_diff", "run_command") for x in events)
    elif case in PROJECTS:
        assert any(x["exit_code"] == 0 for x in commands)
        run(py, "-m", "pytest", "-q")
        if case == "P1":
            run(py, "todo.py", "add", "Alpha")
            run(py, "todo.py", "add", "Alpha", good=False)
            run(py, "todo.py", "add", " ", good=False)
            run(py, "todo.py", "update", "Alpha", "Beta")
            assert run(py, "todo.py", "list") == "Beta"
            assert json.loads(read("todos.json")) == ["Beta"]
            run(py, "todo.py", "delete", "Beta")
            run(py, "todo.py", "delete", "missing", good=False)
            assert json.loads(read("todos.json")) == []
            assert re.search(r"[\u4e00-\u9fff]", read("README.md"))
        elif case == "P2":
            import csv
            import hashlib
            fixture = work / "scoring-input"
            fixture.mkdir()
            for name, data in (("a.TXT",b"same"),("b.bin",b"same"),("c.txt",b"other")):
                (fixture / name).write_bytes(data)
            stats = json.loads(run(py, "scan.py", "scoring-input", "scored.csv"))
            assert stats == {".txt":2, ".bin":1}
            rows = {row["path"]:row for row in csv.DictReader(read("scored.csv").splitlines())}
            assert set(rows) == {"a.TXT","b.bin","c.txt"}
            for name, row in rows.items():
                assert {"sha256", "duplicate"} <= row.keys(), "csv_required_columns_missing"
                assert row["sha256"] == hashlib.sha256((fixture/name).read_bytes()).hexdigest()
                assert row["duplicate"].lower() == ("false" if name=="c.txt" else "true")
        else:
            from agent.desktop.session import require_interactive_session
            require_interactive_session()
            run(py, "-c", """from calculator import create_app
from tkinter import Button, Label
root = create_app()
try:
    root.update()
    assert root.winfo_viewable()
    buttons = {w.cget('text'): w for w in root.winfo_children() if isinstance(w, Button)}
    label, = [w for w in root.winfo_children() if isinstance(w, Label)]
    for expression, expected in [('2+3=', '5'), ('9-4=', '5'), ('3*4=', '12'), ('8/2=', '4'), ('8/0=', 'Error')]:
        buttons['C'].invoke()
        for char in expression:
            buttons[char].invoke()
            root.update()
        value = str(label.cget('text'))
        if label.cget('textvariable'):
            value = str(root.getvar(label.cget('textvariable')))
        assert value == expected or (expected.isdigit() and float(value) == int(expected))
finally:
    root.destroy()
""")

async def attempt(session, binary, url, model, case, root, number, source=False, challenge=None, *, profile, options, scenario=None):
    from agent.core.diagnostics import redact_text
    from scripts.validation.packaged_agent_smoke import read_lines
    from agent.tools.base import ToolError
    work = root / "work"
    work.mkdir(parents=True)
    scenario.seed(work) if scenario else seed(work, case)
    result = {"model": model, "case": case, "repeat": number, "tools": [],
              "status": "BLOCKED", "failure": None, "tokens": None, "repairs": None,
              "configuration": options}
    start = time.monotonic()
    ready = None
    fixture = None
    foreground_fixture = None
    reconnected = None
    if case == "P3":
        from agent.desktop.session import require_interactive_session
        try:
            require_interactive_session()
        except ToolError as exc:
            result.update(failure="ENVIRONMENT_FAILURE", detail=exc.code)
            return result
    if case in (*GUI_CASES, "N"):
        try:
            fixture, expected, gui_prompt = start_gui(case, root, work, challenge)
            await asyncio.sleep(2)
            if fixture.poll() is not None:
                raise RuntimeError("fixture_not_owned_or_exited")
        except Exception as exc:
            result.update(failure="ENVIRONMENT_FAILURE", detail=getattr(exc,"code",None) or
                          (str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__))
            result["seconds"] = round(time.monotonic()-start, 2)
            result["tool_calls"] = 0
            return result
    command = [str(binary)]
    cwd = binary.parent
    if source:
        command += ["-m", "agent.server.main"]
        cwd = P(__file__).resolve().parents[2]
    env = {**case_environment(root), "LCA_DATA_DIR": str(root / "data"), "LCA_PROVIDER": "ollama",
           "LCA_OLLAMA_URL": url, "LCA_OLLAMA_MODEL": model}
    if scenario:
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   UV_OFFLINE="1", UV_NO_MANAGED_PYTHON="1", npm_config_offline="true",
                   npm_config_ignore_scripts="true")
        env.pop("VIRTUAL_ENV", None)
    if options["model_steps"] is not None:
        env["LCA_MAX_MODEL_STEPS"] = str(options["model_steps"])
    if options["context_window"] is not None:
        env["LCA_OLLAMA_NUM_CTX"] = str(options["context_window"])
    proc = subprocess.Popen(command + ["--port", "0"], cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        env=env)
    lines = queue.Queue()
    threading.Thread(target=read_lines, args=(proc.stdout, lines), daemon=True).start()
    trace = (root / "turn-events.jsonl").open("w", encoding="utf-8")
    trace_bytes = 0
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                line = await asyncio.to_thread(lines.get, True, .3)
            except queue.Empty:
                continue
            if line.startswith("LCA_AGENT_READY "):
                ready = json.loads(line.split(" ", 1)[1])
                break
        if not ready or ready.get("version") not in ({APP_VERSION} if source else {"1.0.0", APP_VERSION}):
            raise RuntimeError("packaged_boot")
        base = f"http://127.0.0.1:{ready['port']}"
        headers = {"Authorization": "Bearer " + ready["token"]}
        async with asyncio.timeout(options["case_seconds"]), session.ws_connect(base + "/ws", headers=headers) as ws:
            if profile:
                catalog = {"connections":[{"connection_id":"bench","display_name":"Benchmark Ollama",
                    "provider_type":"ollama","base_url":url,"credential_reference":None,"enabled":True}],
                    "profiles":[{**profile,"model_profile_id":"bench","connection_id":"bench",
                                 "supports_vision": True if fixture else profile.get("supports_vision", False)}]}
                await ws.send_json({"type":"task.catalog.update","request_id":"bench-catalog",
                                    "payload":{"catalog":catalog,"chat_default":"bench",
                                               "config":{"strategy":"single-agent","roles":{"executor":{"model_profile_id":"bench"}},
                                                         "budget":{"request_seconds":options["request_seconds"]}}}})
                while True:
                    msg = await ws.receive_json()
                    if msg.get("request_id") == "bench-catalog":
                        if msg["type"] != "task.loaded":
                            raise RuntimeError("isolated_catalog_update")
                        break
                selected = "profile:bench"
            await ws.send_json({"type":"project.open","request_id":"bench-open","payload":{"path":str(work)}})
            while True:
                event = await ws.receive_json()
                if event.get("request_id") == "bench-open":
                    if event["type"] != "project.opened":
                        raise RuntimeError("project_open")
                    thread = event["thread_id"]
                    break
            prompt = gui_prompt if fixture else (scenario.prompt if scenario else (CASES | PROJECTS)["C" if case == "R" else case]) + " Work only in this test project. Never access other directories, install packages, or contact the network."
            await ws.send_json({"type":"turn.start","thread_id":thread,"payload":{"model":selected,"prompt":prompt,"unified":True}})
            control = scenario.control if scenario else "resume" if case == "R" else ""
            denied = False
            chunks = []
            focus_before = None
            editors = []
            turn_id = run_id = None
            cancellation_requested = resumed = False
            while True:
                event = await ws.receive_json()
                kind, p = event["type"], event.get("payload", {})
                if kind in {"turn.delta", "turn.status", "tool.started", "tool.completed",
                            "turn.failed", "turn.cancelled", "turn.completed", "error"} and trace_bytes < 32 * 1024 * 1024:
                    content = redact_text(json.dumps(p, ensure_ascii=False),
                                          exact_secrets=(ready["token"],), max_chars=32000)
                    row = json.dumps({"type": kind, "payload": content}, ensure_ascii=False) + "\n"
                    trace.write(row)
                    trace.flush()
                    trace_bytes += len(row.encode("utf-8"))
                if kind == "turn.started":
                    turn_id = event.get("turn_id")
                if kind == "agent.runtime.updated":
                    run_id = p.get("runtime", {}).get("id") or run_id
                if kind == "turn.delta":
                    chunks.append(p.get("delta",""))
                if kind == "approval.requested":
                    tool = p.get("tool")
                    args = p.get("arguments", {})
                    command = args.get("command", "")
                    safe = tool in {"write_file","apply_patch","delete_file","git_commit","git_branch"} or (
                        tool == "run_command" and command in {
                            "python -m pytest -q", "python --version", "python -m pytest --version",
                            "git init", "git status", "git diff", "git add note.txt scratch.txt",
                            "git restore scratch.txt", "git switch -c benchmark-work",
                            'git commit -m "baseline"', 'git config user.name Benchmark',
                            'git config user.email benchmark@example.invalid'})
                    if scenario:
                        safe = scenario.approve(tool, args)
                    if fixture:
                        safe = fixture.poll() is None and gui_approval(tool,args,fixture.pid,case,editors,expected,ready["token"])
                        if safe and tool == "desktop_focus_window":
                            if isinstance(fixture, OwnedNotepad) and foreground_fixture is None:
                                # Establish a real, separate foreground window
                                # owned by this test. Never activate user windows.
                                foreground_fixture = await asyncio.create_subprocess_exec(
                                    getattr(sys, "_base_executable", sys.executable), "-c",
                                    "import tkinter as t; r=t.Tk(); r.title('LCA focus fixture'); "
                                    "r.geometry('200x70+8+8'); r.attributes('-topmost', True); r.update(); r.mainloop()",
                                    env=child_environment(), creationflags=subprocess.CREATE_NO_WINDOW,
                                )
                                await asyncio.sleep(1)
                                await activate_foreground_fixture(foreground_fixture.pid)
                            focus_before = foreground_pid()
                    denied |= not safe
                    await ws.send_json({"type":"approval.respond","payload":{"approval_id":p["approval_id"],"decision":"allow_once" if safe else "deny"}})
                if kind == "tool.completed":
                    r = p.get("result", {})
                    if case in {"F-desktop", "N"} and p.get("name") == "desktop_inspect" and r.get("ok"):
                        editors = [c for c in (r.get("data") or {}).get("controls",[])
                                   if c.get("control_type") in {"Edit","Document"} and not c.get("sensitive")]
                    if case in {"F-desktop", "N"} and p.get("name") == "desktop_focus_window" and r.get("ok"):
                        observation = r.get("data") or {}
                        before = observation.get("foreground_before_pid")
                        after = observation.get("foreground_after_pid")
                        result.setdefault("foreground_evidence", []).append({"before_pid": before, "after_pid": after})
                        result["foreground_switch"] = bool(result.get("foreground_switch") or
                            (before is not None and before != fixture.pid and after == fixture.pid) or
                            (focus_before is not None and focus_before != fixture.pid and foreground_pid() == fixture.pid))
                    result["tools"].append({"name":p.get("name"),"ok":r.get("ok"),
                                            "exit_code":r.get("exit_code",(r.get("data") or {}).get("exit_code")),
                                            "vision_feedback":(r.get("data") or {}).get("vision_feedback"),
                                            "changed_paths":r.get("changed_paths", []),
                                            "error_code":(r.get("error") or {}).get("code")})
                    if control and not cancellation_requested and turn_id and run_id and r.get("ok") and (r.get("changed_paths") if scenario else "mathbox.py" in r.get("changed_paths", [])):
                        cancellation_requested = True
                        await ws.send_json({"type":"turn.cancel","turn_id":turn_id})
                if control and kind == "turn.cancelled" and cancellation_requested and not resumed:
                    result["cancelled_generation"] = True
                    await ws.close()
                    reconnected = await session.ws_connect(base + "/ws", headers=headers)
                    ws = reconnected
                    resumed = True
                    result["reconnected"] = True
                    result["control"] = control
                    payload = {"model": selected, "prompt": prompt if control == "restart" else "继续原任务，保留已完成操作", "unified": True}
                    if control == "resume":
                        payload.update(resume_run_id=run_id, confirm_workspace=True)
                    await ws.send_json({"type":"turn.start","thread_id":thread,"payload":payload})
                    continue
                if kind in {"turn.completed","turn.failed","turn.cancelled","error"}:
                    result["terminal"] = kind
                    result["code"] = p.get("code")
                    if scenario and kind != "turn.completed":
                        from agent.core.runtime_events import failure_class
                        result["failure"] = failure_class(result["code"])
                    result["outcome"] = p.get("outcome")
                    if kind != "turn.completed":
                        result.update(status="FAIL", failure="TOOL_PERMISSION" if denied else result["failure"] or "AGENT_FAILURE")
                    else:
                        try:
                            if case == "F-vision":
                                assert any(t["name"]=="desktop_screenshot" and t["vision_feedback"]=="image_attached" for t in result["tools"])
                                assert {t["name"] for t in result["tools"] if t["ok"]} <= {"desktop_list_windows","desktop_screenshot"}
                                assert re.search(r"\b"+expected+r"\b","".join(chunks))
                            elif case in {"F-desktop", "N"}:
                                successful = {t["name"] for t in result["tools"] if t["ok"]}
                                filename = "desktop-test.txt" if case == "N" else f"benchmark-note-{expected}.txt"
                                result["saved_text_verified"] = (work/filename).read_text(encoding="utf-8-sig").strip() == expected
                                assert {"desktop_focus_window","desktop_inspect","desktop_click","desktop_type_text","desktop_keypress"} <= successful, "desktop_required_tool_missing"
                                assert result.get("foreground_switch"), "desktop_foreground_switch_not_observed"
                                assert result["saved_text_verified"], "desktop_saved_text_mismatch"
                                assert not successful & {"write_file","apply_patch","run_command"}
                            else:
                                if scenario:
                                    scenario.score(work, result)
                                else:
                                    score(work, case, result["tools"])
                                if case == "R":
                                    assert resumed and result.get("cancelled_generation")
                                    assert sum(t["ok"] and "mathbox.py" in t["changed_paths"] for t in result["tools"] if t["ok"]) == 1
                            result.update(status="PASS")
                        except ToolError as exc:
                            result.update(status="BLOCKED", failure="ENVIRONMENT_FAILURE", detail=exc.code)
                        except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as exc:
                            result.update(status="FAIL", failure="TOOL_PERMISSION" if denied else "DELIVERY_ASSERTION" if scenario else "MODEL_FAILURE")
                            result["assertion_failure"] = (str(exc) or "assertion_failed") if isinstance(exc, AssertionError) else type(exc).__name__
                    break
    except TimeoutError:
        result.update(status="FAIL",failure="TIMEOUT")
    except (RuntimeError, aiohttp.ClientError, TypeError) as exc:
        result.update(failure="ENVIRONMENT_FAILURE", detail=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
    finally:
        trace.close()
        if foreground_fixture and foreground_fixture.returncode is None:
            foreground_fixture.terminate()
            await foreground_fixture.wait()
        if reconnected:
            await reconnected.close()
        if ready:
            try:
                async with session.post(f"http://127.0.0.1:{ready['port']}/shutdown",
                        headers={"Authorization":"Bearer "+ready["token"]}, timeout=5) as response:
                    await response.read()
                await asyncio.to_thread(proc.wait, 8)
            except (aiohttp.ClientError, TimeoutError, subprocess.TimeoutExpired):
                pass
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        if fixture and fixture.poll() is None:
            try:
                fixture.terminate()
                fixture.wait(timeout=10)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                result["cleanup"] = "OWNED_WINDOW_CLOSE_PENDING"
        result["seconds"] = round(time.monotonic()-start, 2)
        result["tool_calls"] = len(result["tools"])
    return result

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument("--agent", type=P)
    entry.add_argument("--source", action="store_true")
    parser.add_argument("--output", type=P, required=True)
    parser.add_argument("--case", choices=(*CASES,*GUI_CASES,*PROJECTS,"R","N"), action="append")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--model", choices=MODELS, action="append")
    parser.add_argument("--context-window", type=int, metavar="TOKENS")
    parser.add_argument("--output-tokens", help="Positive cap, or 'ollama' to use the service default")
    parser.add_argument("--model-steps", type=int, choices=range(1, 129), metavar="STEPS")
    parser.add_argument("--case-seconds", type=int, default=600)
    parser.add_argument("--request-seconds", type=int)
    parser.add_argument("--continue-locked", type=P, help="Retry only desktop rounds blocked by a locked session")
    parser.add_argument("--continue-blocked-desktop", type=P,
                        help="Retry rounds blocked before dispatch by a locked session or existing Notepad")
    args = parser.parse_args()
    if args.context_window is not None and not 1024 <= args.context_window <= 262144:
        parser.error("--context-window must be 1024..262144")
    if args.output_tokens not in (None, "ollama") and (
        not args.output_tokens.isdecimal() or not 64 <= int(args.output_tokens) <= 32768
    ):
        parser.error("--output-tokens must be 64..32768 or ollama")
    if not 1 <= args.case_seconds <= 1800 or (args.request_seconds is not None and not 1 <= args.request_seconds <= 600):
        parser.error("case and request timeouts are outside benchmark bounds")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    sandbox = P(tempfile.mkdtemp(prefix="lca-real-benchmark-")).resolve()
    binary = args.agent.resolve() if args.agent else P(sys.executable).resolve()
    report = {"version":APP_VERSION if args.source else None,"entrypoint":"source" if args.source else "installed_backend","results":[]}
    (args.output / "scratch-path.txt").write_text(str(sandbox), encoding="utf-8")
    models = discover(profiles=True)
    challenges = {(case,n): str(100000 + secrets.randbelow(900000)) if case == "F-vision" else "LCA-" + secrets.token_hex(4)
                  for case in GUI_CASES for n in range(1,args.repeat+1)}
    pending = None
    prior_path = args.continue_blocked_desktop or args.continue_locked
    if prior_path:
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        prior_root = P(prior_path.with_name("scratch-path.txt").read_text(encoding="utf-8").strip())
        desktop_blockers = {"DESKTOP_SESSION_LOCKED"}
        if args.continue_blocked_desktop:
            desktop_blockers.add("existing_notepad")
        pending = {(r["model"],r["case"],r["repeat"]) for r in prior["results"]
                   if r["case"] in GUI_CASES and r["status"] == "BLOCKED" and r.get("detail") in desktop_blockers}
        for model, case, n in sorted(pending):
            original = prior_root / model.replace(":","-") / f"{case}-{n}"
            badge = original / "Badge.cs"
            if case == "F-vision" and badge.is_file():
                match = re.search(r'DrawString\("([0-9]{6})"', badge.read_text(encoding="utf-8"))
                if match:
                    challenges[model,case,n] = match.group(1)
            if case == "F-desktop":
                notes = list((original/"work").glob("benchmark-note-*.txt"))
                if len(notes) == 1:
                    challenges[model,case,n] = notes[0].stem.removeprefix("benchmark-note-")
    def save(result):
        report["results"].append(result)
        (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(result["model"],result["case"],result["repeat"],result["status"],result.get("failure"),flush=True)
    async with aiohttp.ClientSession() as session:
        for model in args.model or MODELS:
            url, profile, runtime = models.get(model, (None, {}, {}))
            if args.context_window is not None:
                profile["context_window"] = args.context_window
            if args.output_tokens is not None:
                profile["max_output_tokens"] = None if args.output_tokens == "ollama" else int(args.output_tokens)
            from agent.core.budget import DEFAULT_LIMITS
            options = {"context_window": profile.get("context_window") or runtime.get("context_window"),
                       "max_output_tokens": profile.get("max_output_tokens"),
                       "context_source": "benchmark_override" if args.context_window else
                           "saved_profile" if profile.get("context_window") else "runtime_settings",
                       "output_source": "benchmark_override" if args.output_tokens else "saved_profile",
                       "model_steps": args.model_steps or runtime.get("model_steps"),
                       "model_steps_source": "benchmark_override" if args.model_steps else "runtime_settings",
                       "request_seconds": args.request_seconds or runtime.get("request_seconds") or DEFAULT_LIMITS["request_seconds"],
                       "case_seconds": args.case_seconds}
            online = False
            if url:
                try:
                    async with session.get(url+"/api/tags", timeout=8) as response:
                        online = response.ok and any(m["name"] == model for m in (await response.json())["models"])
                except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
                    pass
            for case in args.case or (*CASES,*GUI_CASES):
                for n in range(1,args.repeat+1):
                    if pending is not None and (model,case,n) not in pending:
                        continue
                    if online:
                        save(await attempt(session,binary,url,model,case,
                                           sandbox / model.replace(":","-") / f"{case}-{n}",n,args.source,
                                           NOTEPAD_PHRASE if case == "N" else
                                           challenges.get((model,case,n), challenges.get((case,n))),
                                           profile=profile, options=options))
                    else:
                        save({"model":model,"case":case,"repeat":n,"status":"BLOCKED","failure":"ENVIRONMENT_FAILURE"})

if __name__ == "__main__":
    asyncio.run(main())

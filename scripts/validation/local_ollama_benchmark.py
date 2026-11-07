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
    "P2": "From scratch implement Python scan.py DIRECTORY OUTPUT.csv. Recursively scan files, print counts by lowercase extension as JSON to stdout, hash each file with SHA256, and export CSV with relative path, extension, sha256, duplicate columns (duplicate is true for every member of a repeated digest). Exclude the output file itself. Include and run pytest tests. Fix failures.",
    "P3": "From scratch build a Windows Tkinter calculator in calculator.py with create_app() returning a Tk window. Use direct child Button widgets labelled 0–9, +, -, *, /, =, C and a direct child Label showing the result. Show Error on division by zero. Add GUI pytest tests and run them. Do not touch any existing window or user file.",
}

def child_environment():
    sensitive = re.compile(r"api.?key|secret|credential|password|token", re.I)
    return {key: value for key, value in os.environ.items()
            if not sensitive.search(key) or key == "LCA_CONTEXT_RESERVED_OUTPUT_TOKENS"}

class OwnedNotepad:
    def __init__(self, filename):
        import win32gui
        import win32process
        self.filename = filename
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            windows = []
            win32gui.EnumWindows(lambda hwnd, _: windows.append(hwnd), None)
            matches = [hwnd for hwnd in windows if win32gui.IsWindowVisible(hwnd)
                       and win32gui.GetWindowText(hwnd).startswith(filename + " - ")]
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
        return None if win32gui.GetWindowText(self.hwnd).startswith(self.filename + " - ") else 0

    def terminate(self):
        import win32gui
        import win32con
        if self.poll() is None:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

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
        listed = subprocess.check_output(["tasklist","/FI","IMAGENAME eq Notepad.exe","/FO","CSV","/NH"], text=True, errors="replace")
        if re.search(r'^"notepad\.exe"',listed,re.I|re.M):
            raise RuntimeError("existing_notepad")
        file = work / ("desktop-test.txt" if case == "N" else f"benchmark-note-{code}.txt")
        file.write_text("BASE",encoding="utf-8")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 4
        subprocess.Popen([str(P(os.environ["WINDIR"])/"System32/notepad.exe"),str(file)], startupinfo=startup)
        proc = OwnedNotepad(file.name)
        prompt = (f"仅桌面操作。用 desktop_list_windows 的 pid 参数查找 PID {proc.pid} 的记事本窗口，"
                  f"激活该窗口，查看 UIA 控件，点击编辑区，输入 {code} 替换 BASE，再按 Ctrl+S。"
                  "禁止读取源码或用文件工具写入。")
    return proc, code, prompt

def gui_approval(tool, args, pid, case, editors, expected):
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
    return match and (tool == "desktop_click" or args.get("text") == expected)

def foreground_pid():
    import win32gui
    import win32process
    handle = win32gui.GetForegroundWindow()
    return win32process.GetWindowThreadProcessId(handle)[1] if handle else None

def discover():
    data = P(os.environ["APPDATA"]) / "local-coding-agent-desktop"
    with sqlite3.connect((data / "local-coding-agent.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        def setting(key):
            row = db.execute("select value from settings where key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        catalog = setting("models.catalog.v1")
    connections = {c["connection_id"]: c for c in catalog["connections"]
                   if c["provider_type"] == "ollama" and c.get("enabled", True)}
    urls = {}
    for model in MODELS:
        for profile in catalog["profiles"]:
            if profile["model_id"] == model and profile["connection_id"] in connections:
                url = connections[profile["connection_id"]]["base_url"]
                parsed = urllib.parse.urlsplit(url)
                if parsed.scheme in ("http", "https") and not any((parsed.username, parsed.password, parsed.query, parsed.fragment)):
                    urls[model] = url.rstrip("/")
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
        p = subprocess.run(args, cwd=work, env=child_environment(),
                           capture_output=True, text=True, timeout=20)
        assert (p.returncode == 0) == good
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
        assert not (work / "items.json").exists() or json.loads(read("items.json")) == []
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
        assert run("git", "branch", "--show-current") == "benchmark-work"
        assert run("git", "show", "HEAD:scratch.txt") == "KEEP"
        assert read("scratch.txt").strip() == "KEEP"
        assert "+NEW" in run("git", "diff", "--", "note.txt")
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

async def attempt(session, binary, url, model, case, root, number, source=False, challenge=None):
    from scripts.validation.packaged_agent_smoke import read_lines
    from agent.tools.base import ToolError
    work = root / "work"
    work.mkdir(parents=True)
    seed(work, case)
    result = {"model": model, "case": case, "repeat": number, "tools": [],
              "status": "BLOCKED", "failure": None, "tokens": None, "repairs": None}
    start = time.monotonic()
    ready = None
    fixture = None
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
    proc = subprocess.Popen(command + ["--port", "0"], cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        env={**child_environment(), "LCA_DATA_DIR": str(root / "data"), "LCA_PROVIDER": "ollama",
             "LCA_OLLAMA_URL": url, "LCA_OLLAMA_MODEL": model, "LCA_OLLAMA_NUM_CTX": "8192",
             "LCA_MAX_MODEL_STEPS": "18", "LCA_CONTEXT_RESERVED_OUTPUT_TOKENS": "1024"})
    lines = queue.Queue()
    threading.Thread(target=read_lines, args=(proc.stdout, lines), daemon=True).start()
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
        if not ready or ready.get("version") != "1.0.0":
            raise RuntimeError("packaged_boot")
        base = f"http://127.0.0.1:{ready['port']}"
        headers = {"Authorization": "Bearer " + ready["token"]}
        async with asyncio.timeout(600 if case in PROJECTS else 240), session.ws_connect(base + "/ws", headers=headers) as ws:
            selected = model
            if fixture:
                catalog = {"connections":[{"connection_id":"bench","display_name":"Benchmark Ollama",
                    "provider_type":"ollama","base_url":url,"credential_reference":None,"enabled":True}],
                    "profiles":[{"model_profile_id":"bench","connection_id":"bench","model_id":model,
                    "display_name":model,"supports_vision":True,"context_window":8192,"max_output_tokens":1024}]}
                await ws.send_json({"type":"task.catalog.update","request_id":"bench-catalog",
                                    "payload":{"catalog":catalog,"chat_default":"bench",
                                               "config":{"strategy":"single-agent","roles":{"executor":{"model_profile_id":"bench"}}}}})
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
            prompt = gui_prompt if fixture else (CASES | PROJECTS)["C" if case == "R" else case] + " Work only in this test project. Never access other directories, install packages, or contact the network."
            await ws.send_json({"type":"turn.start","thread_id":thread,"payload":{"model":selected,"prompt":prompt,"unified":True}})
            denied = False
            chunks = []
            focus_before = None
            editors = []
            turn_id = run_id = None
            cancellation_requested = resumed = False
            while True:
                event = await ws.receive_json()
                kind, p = event["type"], event.get("payload", {})
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
                    if fixture:
                        safe = fixture.poll() is None and gui_approval(tool,args,fixture.pid,case,editors,expected)
                        if safe and tool == "desktop_focus_window":
                            focus_before = foreground_pid()
                    denied |= not safe
                    await ws.send_json({"type":"approval.respond","payload":{"approval_id":p["approval_id"],"decision":"allow_once" if safe else "deny"}})
                if kind == "tool.completed":
                    r = p.get("result", {})
                    if case in {"F-desktop", "N"} and p.get("name") == "desktop_inspect" and r.get("ok"):
                        editors = [c for c in (r.get("data") or {}).get("controls",[])
                                   if c.get("control_type") in {"Edit","Document"} and not c.get("sensitive")]
                    if case in {"F-desktop", "N"} and p.get("name") == "desktop_focus_window" and r.get("ok"):
                        result["foreground_switch"] = bool(result.get("foreground_switch") or
                            (focus_before is not None and focus_before != fixture.pid and foreground_pid() == fixture.pid))
                    result["tools"].append({"name":p.get("name"),"ok":r.get("ok"),
                                            "exit_code":r.get("exit_code",(r.get("data") or {}).get("exit_code")),
                                            "vision_feedback":(r.get("data") or {}).get("vision_feedback"),
                                            "changed_paths":r.get("changed_paths", []),
                                            "error_code":(r.get("error") or {}).get("code")})
                    if case == "R" and not cancellation_requested and turn_id and run_id and r.get("ok") and "mathbox.py" in r.get("changed_paths", []):
                        cancellation_requested = True
                        await ws.send_json({"type":"turn.cancel","turn_id":turn_id})
                if case == "R" and kind == "turn.cancelled" and cancellation_requested and not resumed:
                    result["cancelled_generation"] = True
                    await ws.close()
                    reconnected = await session.ws_connect(base + "/ws", headers=headers)
                    ws = reconnected
                    resumed = True
                    result["reconnected"] = True
                    await ws.send_json({"type":"turn.start","thread_id":thread,"payload":{
                        "model":selected,"prompt":"继续原任务，保留已完成操作","unified":True,
                        "resume_run_id":run_id,"confirm_workspace":True}})
                    continue
                if kind in {"turn.completed","turn.failed","turn.cancelled","error"}:
                    result["terminal"] = kind
                    result["code"] = p.get("code")
                    result["outcome"] = p.get("outcome")
                    if kind != "turn.completed":
                        result.update(status="FAIL", failure="TOOL_PERMISSION" if denied else "AGENT_FAILURE")
                    else:
                        try:
                            if case == "F-vision":
                                assert any(t["name"]=="desktop_screenshot" and t["vision_feedback"]=="image_attached" for t in result["tools"])
                                assert {t["name"] for t in result["tools"] if t["ok"]} <= {"desktop_list_windows","desktop_screenshot"}
                                assert re.search(r"\b"+expected+r"\b","".join(chunks))
                            elif case in {"F-desktop", "N"}:
                                successful = {t["name"] for t in result["tools"] if t["ok"]}
                                assert {"desktop_focus_window","desktop_inspect","desktop_click","desktop_type_text","desktop_keypress"} <= successful
                                assert result.get("foreground_switch")
                                filename = "desktop-test.txt" if case == "N" else f"benchmark-note-{expected}.txt"
                                assert (work/filename).read_text(encoding="utf-8-sig").strip() == expected
                                assert not successful & {"write_file","apply_patch","run_command"}
                            else:
                                score(work, case, result["tools"])
                                if case == "R":
                                    assert resumed and result.get("cancelled_generation")
                                    assert sum(t["ok"] and "mathbox.py" in t["changed_paths"] for t in result["tools"] if t["ok"]) == 1
                            result.update(status="PASS")
                        except ToolError as exc:
                            result.update(status="BLOCKED", failure="ENVIRONMENT_FAILURE", detail=exc.code)
                        except (AssertionError, OSError, ValueError, subprocess.SubprocessError):
                            result.update(status="FAIL", failure="TOOL_PERMISSION" if denied else "MODEL_FAILURE")
                    break
    except TimeoutError:
        result.update(status="FAIL",failure="TIMEOUT")
    except (RuntimeError, aiohttp.ClientError, TypeError) as exc:
        result.update(failure="ENVIRONMENT_FAILURE", detail=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
    finally:
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
    parser.add_argument("--continue-locked", type=P, help="Retry only desktop rounds blocked by a locked session")
    parser.add_argument("--continue-blocked-desktop", type=P,
                        help="Retry rounds blocked before dispatch by a locked session or existing Notepad")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    sandbox = P(tempfile.mkdtemp(prefix="lca-real-benchmark-")).resolve()
    binary = args.agent.resolve() if args.agent else P(sys.executable).resolve()
    report = {"version":"1.0.0","entrypoint":"source" if args.source else "installed_backend","results":[]}
    (args.output / "scratch-path.txt").write_text(str(sandbox), encoding="utf-8")
    urls = discover()
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
            url = urls.get(model)
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
                                           challenges.get((model,case,n), challenges.get((case,n)))))
                    else:
                        save({"model":model,"case":case,"repeat":n,"status":"BLOCKED","failure":"ENVIRONMENT_FAILURE"})

if __name__ == "__main__":
    asyncio.run(main())

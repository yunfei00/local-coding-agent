from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
import urllib.request
from pathlib import Path


READY_PREFIX = "LCA_AGENT_READY "


def read_lines(stream, output: queue.Queue[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            output.put(line.rstrip("\\r\\n"))
    finally:
        stream.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    executable = Path(args.executable).resolve()
    if not executable.is_file():
        raise SystemExit(f"Agent executable does not exist: {executable}")

    process = subprocess.Popen(
        [str(executable), "--port", "0"],
        cwd=str(executable.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert process.stdout is not None
    assert process.stderr is not None

    stdout_lines: queue.Queue[str] = queue.Queue()
    stderr_lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=read_lines, args=(process.stdout, stdout_lines), daemon=True).start()
    threading.Thread(target=read_lines, args=(process.stderr, stderr_lines), daemon=True).start()

    deadline = time.monotonic() + args.timeout
    ready: dict | None = None

    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                line = stdout_lines.get(timeout=0.2)
            except queue.Empty:
                continue
            print(line)
            if line.startswith(READY_PREFIX):
                ready = json.loads(line[len(READY_PREFIX) :])
                break

        if ready is None:
            stderr = []
            while not stderr_lines.empty():
                stderr.append(stderr_lines.get_nowait())
            raise RuntimeError(
                "Packaged Agent did not become ready. "
                + (" stderr=" + " | ".join(stderr) if stderr else "")
            )

        request = urllib.request.Request(
            f"http://127.0.0.1:{ready['port']}/health",
            headers={"Authorization": f"Bearer {ready['token']}"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Packaged Agent health failed: {payload}")

        shutdown = urllib.request.Request(
            f"http://127.0.0.1:{ready['port']}/shutdown",
            headers={"Authorization": f"Bearer {ready['token']}"},
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(shutdown, timeout=5) as response:
            response.read()

        exit_code = process.wait(timeout=10)
        if exit_code != 0:
            raise RuntimeError(f"Packaged Agent exited with code {exit_code}")

        print("PACKAGED_AGENT_SMOKE_OK " + json.dumps({
            "version": ready.get("version"),
            "protocol": ready.get("protocol"),
            "port": ready.get("port"),
        }, ensure_ascii=False))
        return 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())

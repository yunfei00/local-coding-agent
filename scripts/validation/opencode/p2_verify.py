"""P2 fixed fixture adapter for the existing independent VerificationEngine.

Never execute commands supplied by the model. Run an immutable copy of the
known correct fixture only after checking the actual model-created files.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from agent.core.verification import VerificationEngine

REPAIRED = "module.exports = (a, b) => a + b;\n"
TEST = (
    "const assert = require('node:assert/strict');\n"
    "const add = require('./add.cjs');\n"
    "assert.equal(add(7, 8), 15);\n"
    "assert.equal(add(-3, 2), -1);\n"
    "assert.equal(add(0, 0), 0);\n"
)
COMMAND = "node test-add.cjs"


async def verify(root: Path, node: Path):
    root = root.resolve(strict=True)
    fixture_base = (Path.cwd() / "build/opencode-p0").resolve()
    if not root.is_relative_to(fixture_base) or root.name != "project" or not root.parent.name.startswith("model-"):
        raise ValueError("Only generated P2 fixtures are permitted")
    for name, expected in (("add.cjs", REPAIRED), ("test-add.cjs", TEST)):
        file = root / name
        if file.is_symlink() or not file.is_file() or file.resolve().parent != root or file.stat().st_size > 65536:
            raise ValueError("Unsafe fixture file")
        if file.read_text(encoding="utf-8") != expected:
            raise ValueError("Fixture repair or preserved test does not match")

    if not node.is_absolute() or not node.is_file():
        raise ValueError("Absolute local Node executable required")
    with tempfile.TemporaryDirectory(prefix="lca-p2-verifier-") as tmp:
        isolated = Path(tmp)
        (isolated / "add.cjs").write_text(REPAIRED, encoding="utf-8")
        (isolated / "test-add.cjs").write_text(TEST, encoding="utf-8")

        async def execute(tool, args, *, on_raw_output, environment):
            if tool != "run_command" or args.get("command") != COMMAND:
                raise ValueError("Unapproved verifier command")
            env = {k:v for k,v in os.environ.items() if k.upper() not in {"NODE_OPTIONS","NODE_PATH"}}
            env.update(environment)
            child = await asyncio.create_subprocess_exec(
                str(node), "test-add.cjs", cwd=str(isolated), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(child.communicate(), timeout=15)
            except asyncio.TimeoutError:
                child.kill()
                await child.wait()
                return {"ok":False,"exit_code":None,"error":{"code":"COMMAND_TIMEOUT"}}
            out, err = stdout.decode(errors="replace"), stderr.decode(errors="replace")
            await on_raw_output("stdout", out)
            await on_raw_output("stderr", err)
            return {"ok":child.returncode == 0,"exit_code":child.returncode,"stdout":out,"stderr":err}

        return await VerificationEngine(root.parent / "independent-verification", execute, 15).run([COMMAND])


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("Expected generated fixture and local Node executable")
        results = asyncio.run(verify(Path(sys.argv[1]), Path(sys.argv[2])))
        print(json.dumps({"results":results}, ensure_ascii=True))
        sys.exit(0 if results and all(row["ok"] for row in results) else 1)
    except Exception as exc:
        print(json.dumps({"error":type(exc).__name__,"message":str(exc)}, ensure_ascii=True))
        sys.exit(1)

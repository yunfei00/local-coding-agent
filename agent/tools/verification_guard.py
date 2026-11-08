"""Python audit guard for ordinary project verification and Python children.

The launcher installs this as sitecustomize. This is defense in depth for
supported Python operations, not a sandbox for hostile or native code.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import sys


def install():
    root = Path(os.environ["LCA_VERIFICATION_ROOT"]).resolve()
    guard = Path(__file__).resolve().parent
    runtime = {Path(p).resolve() for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)}
    executable = Path(sys.executable).resolve()
    violations = (guard / "violations").open("a", encoding="utf-8")

    def deny(event):
        violations.write(event + "\n")
        violations.flush()
        raise PermissionError("LCA 验证隔离阻止访问或启动：" + event)

    def within(path, event, *, write=False):
        if isinstance(path, int):
            return
        path = Path(os.fsdecode(path)).resolve()
        if path.is_relative_to(root):
            return
        if not write and (path.is_relative_to(guard) or any(path.is_relative_to(p) for p in runtime)):
            return
        deny(event)

    def relative_to_descriptor(path, descriptor, event):
        if descriptor in (None, -1):
            return path
        if sys.platform != "linux":
            deny(event)
        parent = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        within(parent, event, write=True)
        return parent / os.fsdecode(path)

    def audit(event, args):
        if event == "open":
            path, _, flags = args
            within(path, event, write=bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        elif event in {"os.listdir", "os.scandir", "os.chdir", "os.fwalk"}:
            if args[0] is not None:
                within(args[0], event, write=event == "os.chdir")
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate", "os.setxattr", "os.removexattr", "shutil.rmtree"}:
            descriptor = args[-1] if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "shutil.rmtree"} else None
            within(relative_to_descriptor(args[0], descriptor, event), event, write=True)
        elif event == "os.rename":
            for path, descriptor in zip(args[:2], args[2:]):
                within(relative_to_descriptor(path, descriptor, event), event, write=True)
        elif event == "sqlite3.connect" and args[0] != ":memory:":
            if os.fsdecode(args[0]).startswith("file:"):
                deny(event)
            within(args[0], event, write=True)
        elif event == "subprocess.Popen":
            program, argv, cwd, env = args
            if isinstance(argv, str):
                argv = [part.strip('"') for part in shlex.split(argv, posix=False)]
            if not isinstance(argv, (list, tuple)) or len(argv) < 2:
                deny(event)
            selected = os.fsdecode(program or argv[0])
            binary = Path(shutil.which(selected) or selected).resolve()
            if binary != executable:
                deny(event)
            first = os.fsdecode(argv[1])
            if first not in {"-m", "-c"} and (first.startswith("-") or not first.endswith(".py")):
                deny(event)
            if cwd is not None:
                within(cwd, event, write=True)
            if env is not None or os.environ.get("PYTHONPATH") != str(guard):
                deny(event)
        elif event.startswith(("ctypes.", "winreg.", "socket.")) or event in {
            "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile", "os.startfile/2",
            "os.symlink", "os.link", "os.mknod", "os.mkfifo", "os.fork", "os.forkpty", "os.add_dll_directory",
        }:
            deny(event)
        elif event in {"os.putenv", "os.unsetenv"} and re.match(
            r"^(?:PYTHON|LCA_|TMP|TEMP|PATH$|LD_|DYLD_)", os.fsdecode(args[0]), re.I
        ):
            deny(event)

    sys.addaudithook(audit)
    sys.path.insert(0, str(Path.cwd()))
    # A .pth/site startup error must never silently disable the guard.
    sys._lca_verification_guard = True


if __name__ == "sitecustomize":
    install()

"""Conservative cross-process engine execution gate.

A single atomic directory excludes all engine execution within one application
data directory. Never reclaim automatically: an orphan may still be executing.
"""
from pathlib import Path
import os
import uuid
from contextlib import contextmanager


class EngineLeaseOccupied(RuntimeError):
    pass


@contextmanager
def engine_lease(data_dir):
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "engine-execution.lock"
    token = uuid.uuid4().hex
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise EngineLeaseOccupied("Engine execution lease occupied; verify previous execution stopped") from exc
    owner = lock / "owner"
    try:
        owner.write_text(f"{os.getpid()}:{token}", encoding="ascii")
        yield
    finally:
        # Fail closed if ownership cannot be established.
        if owner.is_file() and owner.read_text(encoding="ascii") == f"{os.getpid()}:{token}":
            owner.unlink()
            lock.rmdir()

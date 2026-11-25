import subprocess
import sys

import pytest

from agent.core.engine_lease import engine_lease


def test_cross_process_exclusion(tmp_path):
    script = (
        "import sys; from agent.core.engine_lease import engine_lease\n"
        "with engine_lease(sys.argv[1]): print('acquired')\n"
    )
    with engine_lease(tmp_path):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                                capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert "Engine execution lease occupied" in result.stderr
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "acquired" in result.stdout


def test_exception_releases_lease(tmp_path):
    with pytest.raises(ValueError):
        with engine_lease(tmp_path):
            raise ValueError("execution failure")
    with engine_lease(tmp_path):
        pass


def test_orphan_is_not_reclaimed(tmp_path):
    (tmp_path / "engine-execution.lock").mkdir()
    with pytest.raises(RuntimeError, match="lease occupied"):
        with engine_lease(tmp_path):
            pytest.fail("orphan lease must not be reclaimed")


def test_background_contention_pauses_without_execution(tmp_path, monkeypatch):
    import asyncio
    import sqlite3
    from agent.core.background import BackgroundJobs
    from agent.core.engine_lease import EngineLeaseOccupied

    monkeypatch.setenv("LCA_DATA_DIR", str(tmp_path))
    async def scenario():
        db = sqlite3.connect(":memory:")
        try:
            jobs = BackgroundJobs(db)
            jobs.add("job", "thread", "project")
            called = False
            async def operation():
                nonlocal called
                called = True
            with engine_lease(tmp_path):
                with pytest.raises(EngineLeaseOccupied):
                    await jobs.run("job", operation)
            assert not called
            assert jobs.list()[0]["state"] == "paused"
            assert not jobs.running_claims
            jobs.add("next", "thread", "project")
            await jobs.run("next", operation)
            assert called
            assert not jobs.running_claims
        finally:
            db.close()
    asyncio.run(scenario())

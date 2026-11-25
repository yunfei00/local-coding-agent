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

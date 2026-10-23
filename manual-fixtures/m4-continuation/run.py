"""CPU-only real tool/GUI acceptance, with model decisions scripted by tests."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
for suite in ('test_execution_recovery.py', 'test_m3_desktop.py', 'test_m4_gui.py'):
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', suite, '-v'], cwd=root)
    if result.returncode:
        raise SystemExit(result.returncode)

"""Path to shipped declarative skills."""
from pathlib import Path

def builtin_skill_workspace() -> Path:
    return Path(__file__).resolve().parents[2]

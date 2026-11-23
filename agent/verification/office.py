"""Read-back validation is structural, not visual certification."""
from pathlib import Path
from agent.office.engine import inspect_excel, inspect_word, inspect_ppt

def verify_office(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "reason": "File missing or empty"}
    reader = {".xlsx": inspect_excel, ".docx": inspect_word, ".pptx": inspect_ppt}.get(path.suffix.lower())
    if reader is None:
        return {"ok": False, "reason": "Unsupported file type"}
    try:
        data = reader(path)
        count = len(data.get("sheets", data.get("paragraphs", data.get("slides", []))))
        return {"ok": count > 0, "path": str(path), "items": count, "level": "structural"}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

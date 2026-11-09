"""Windows Microsoft Office integration: installed-app probe and PDF export."""
from __future__ import annotations
import sys
from pathlib import Path
from agent.office.engine import OfficeError, office_com_export_pdf

PROGIDS = {"excel": "Excel.Application", "word": "Word.Application", "powerpoint": "PowerPoint.Application"}

def detect_office() -> dict:
    if sys.platform != "win32":
        return {"available": False, "platform": sys.platform, "applications": {}, "reason": "Microsoft Office COM requires Windows"}
    try:
        import win32com.client
    except ImportError:
        return {"available": False, "platform": sys.platform, "applications": {}, "reason": "pywin32 not installed"}
    result = {}
    for kind, progid in PROGIDS.items():
        try:
            app = win32com.client.DispatchEx(progid)
            try:
                result[kind] = {"available": True, "version": str(app.Version)}
            finally:
                app.Quit()
        except Exception as exc:
            result[kind] = {"available": False, "error": type(exc).__name__}
    return {"available": any(x["available"] for x in result.values()), "platform": sys.platform, "applications": result}

def export_pdf(source: str | Path, target: str | Path) -> dict:
    source, target = Path(source).resolve(strict=True), Path(target).resolve()
    if target.exists():
        raise OfficeError("Refusing to overwrite existing PDF")
    if source.suffix.lower() not in (".xlsx", ".docx", ".pptx") or target.suffix.lower() != ".pdf":
        raise OfficeError("Unsupported Office conversion")
    office_com_export_pdf(source, target)
    if not target.is_file() or target.stat().st_size < 5:
        raise OfficeError("Office export produced no PDF")
    with target.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise OfficeError("Office export is not a valid PDF")
    return {"path": str(target), "bytes": target.stat().st_size, "verified": True}

"""Explicit, non-overwriting native Microsoft Office COM edits on Windows."""
from __future__ import annotations
import sys
from pathlib import Path
from agent.office.engine import OfficeError

def com_edit_copy(source: str | Path, target: str | Path, spec: dict) -> dict:
    if sys.platform != "win32":
        raise OfficeError("Office COM requires Windows")
    import win32com.client
    source=Path(source).resolve(strict=True)
    target=Path(target).resolve()
    if source.suffix.lower() not in {".xlsx",".docx",".pptx"} or target.suffix.lower()!=source.suffix.lower():
        raise OfficeError("Source and target must be matching macro-free Office formats")
    if target.exists() or source==target:
        raise OfficeError("COM editing must create a new file; refusing to overwrite")
    if not isinstance(spec,dict):
        raise OfficeError("Invalid COM edit specification")
    target.parent.mkdir(parents=True,exist_ok=True)
    ext=source.suffix.lower()
    progid={".xlsx":"Excel.Application",".docx":"Word.Application",".pptx":"PowerPoint.Application"}[ext]
    app=win32com.client.DispatchEx(progid)
    document=None
    try:
        app.DisplayAlerts=False
        if ext==".xlsx":
            document=app.Workbooks.Open(str(source),UpdateLinks=0,ReadOnly=True)
            for sheet_name, cells in spec.get("sheets",{}).items():
                sheet=document.Worksheets(sheet_name)
                for address,value in cells.items():
                    sheet.Range(address).Value=value
            document.SaveAs(str(target),FileFormat=51)
            document.Close(False)
            document=None
        elif ext==".docx":
            document=app.Documents.Open(str(source),ReadOnly=True,AddToRecentFiles=False)
            for item in spec.get("replace",[]):
                find=document.Content.Find
                find.ClearFormatting()
                find.Replacement.ClearFormatting()
                find.Execute(FindText=str(item["find"]),ReplaceWith=str(item["with"]),Replace=2)
            document.SaveAs2(str(target),FileFormat=16)
            document.Close(False)
            document=None
        else:
            document=app.Presentations.Open(str(source),WithWindow=False,ReadOnly=True)
            for item in spec.get("slides",[]):
                slide=document.Slides(int(item["index"])+1)
                if "title" in item:
                    slide.Shapes.Title.TextFrame.TextRange.Text=str(item["title"])
            document.SaveAs(str(target),24)
            document.Close()
            document=None
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        if document is not None:
            try:
                document.Close(False) if ext != ".pptx" else document.Close()
            except Exception:
                pass
        app.Quit()
    if not target.is_file() or target.stat().st_size==0:
        raise OfficeError("COM edit produced no file")
    return {"path":str(target),"bytes":target.stat().st_size,"source_unchanged":True}

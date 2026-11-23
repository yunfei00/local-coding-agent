"""File-based Office operations with atomic outputs and no macro execution."""
from __future__ import annotations
from pathlib import Path
import os
import tempfile

class OfficeError(RuntimeError):
    pass

def _safe_output(path: str | Path, suffix: str) -> Path:
    p = Path(path).resolve()
    if p.suffix.lower() != suffix:
        raise OfficeError(f"Expected {suffix} output")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _atomic_save(target: Path, save) -> None:
    fd, name = tempfile.mkstemp(prefix=".lca-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        save(tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

def inspect_excel(path: str | Path, *, max_rows: int = 200) -> dict:
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        result = {"type": "excel", "sheets": []}
        for sheet in book.worksheets:
            rows = [[str(value)[:2000] if value is not None else None for value in row] for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, max_rows), max_col=min(sheet.max_column, 50), values_only=True)]
            result["sheets"].append({"name": sheet.title, "rows": rows, "total_rows": sheet.max_row, "total_columns": sheet.max_column})
        return result
    finally:
        book.close()

def create_excel(path: str | Path, sheets: dict[str, list[list]], *, title_style: bool = True) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    target = _safe_output(path, ".xlsx")
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
        if title_style and rows:
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1E497D")
        sheet.freeze_panes = "A2"
    _atomic_save(target, book.save)
    return str(target)

def inspect_word(path: str | Path) -> dict:
    from docx import Document
    doc = Document(path)
    return {"type": "word", "paragraphs": [p.text for p in doc.paragraphs], "tables": [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]}

def create_word(path: str | Path, title: str, sections: list[dict]) -> str:
    from docx import Document
    target = _safe_output(path, ".docx")
    doc = Document()
    doc.add_heading(title, 0)
    for section in sections:
        if section.get("heading"):
            doc.add_heading(str(section["heading"]), level=1)
        if section.get("text"):
            doc.add_paragraph(str(section["text"]))
        if section.get("table"):
            data = section["table"]
            if data:
                table = doc.add_table(rows=0, cols=len(data[0]))
                table.style = "Table Grid"
                for row in data:
                    cells = table.add_row().cells
                    for i, value in enumerate(row):
                        cells[i].text = str(value)
    _atomic_save(target, doc.save)
    return str(target)

def inspect_ppt(path: str | Path) -> dict:
    from pptx import Presentation
    pres = Presentation(path)
    return {"type": "powerpoint", "slides": [[shape.text for shape in slide.shapes if shape.has_text_frame] for slide in pres.slides]}

def create_ppt(path: str | Path, slides: list[dict]) -> str:
    from pptx import Presentation
    from pptx.util import Inches
    target = _safe_output(path, ".pptx")
    pres = Presentation()
    pres.slide_width, pres.slide_height = Inches(13.333), Inches(7.5)
    for item in slides:
        slide = pres.slides.add_slide(pres.slide_layouts[1])
        slide.shapes.title.text = str(item.get("title", ""))
        slide.placeholders[1].text = str(item.get("body", ""))
    _atomic_save(target, pres.save)
    return str(target)

def office_com_export_pdf(source: str | Path, target: str | Path) -> str:
    """Requires Windows and installed Microsoft Office; never modifies source."""
    import sys
    if sys.platform != "win32":
        raise OfficeError("Office COM requires Windows")
    import win32com.client
    source = Path(source).resolve(strict=True)
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    extension = source.suffix.lower()
    if extension not in {".xlsx", ".docx", ".pptx"} or target.suffix.lower() != ".pdf":
        raise OfficeError("Unsupported COM conversion")
    progid = {".xlsx": "Excel.Application", ".docx": "Word.Application", ".pptx": "PowerPoint.Application"}[extension]
    app = win32com.client.DispatchEx(progid)
    try:
        app.Visible = False
        if extension == ".xlsx":
            doc = app.Workbooks.Open(str(source), UpdateLinks=0, ReadOnly=True)
            try: doc.ExportAsFixedFormat(0, str(target))
            finally: doc.Close(False)
        elif extension == ".docx":
            doc = app.Documents.Open(str(source), ReadOnly=True, AddToRecentFiles=False)
            try: doc.ExportAsFixedFormat(str(target), 17)
            finally: doc.Close(False)
        else:
            doc = app.Presentations.Open(str(source), WithWindow=False, ReadOnly=True)
            try: doc.SaveAs(str(target), 32)
            finally: doc.Close()
    finally:
        app.Quit()
    return str(target)

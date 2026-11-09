"""Safe, atomic edits of existing macro-free Office documents."""
from __future__ import annotations
from pathlib import Path
from agent.office.engine import _atomic_save, OfficeError

def edit_excel(path: str | Path, spec: dict) -> dict:
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    p = Path(path).resolve(strict=True)
    if p.suffix.lower() != ".xlsx":
        raise OfficeError("Only .xlsx workbooks are supported")
    book = load_workbook(p, keep_vba=False, keep_links=False)
    try:
        for sheet_name, changes in spec.get("sheets", {}).items():
            if not isinstance(changes, dict):
                raise OfficeError("Sheet update must be a mapping")
            sheet = book[sheet_name] if sheet_name in book else book.create_sheet(sheet_name)
            for address, value in changes.get("cells", {}).items():
                if not isinstance(address, str) or not isinstance(value, (str, int, float, bool, type(None))):
                    raise OfficeError("Invalid cell update")
                sheet[address] = value
            for address, style in changes.get("styles", {}).items():
                cell = sheet[address]
                if "bold" in style:
                    cell.font = Font(bold=bool(style["bold"]))
                if "fill" in style:
                    color = str(style["fill"])
                    if len(color) not in (6,8) or any(x not in "0123456789abcdefABCDEF" for x in color):
                        raise OfficeError("Invalid fill color")
                    cell.fill = PatternFill("solid", fgColor=color)
                if "alignment" in style:
                    if style["alignment"] not in ("left","center","right"):
                        raise OfficeError("Invalid alignment")
                    cell.alignment = Alignment(horizontal=style["alignment"])
            if changes.get("freeze"):
                sheet.freeze_panes = str(changes["freeze"])
        _atomic_save(p, book.save)
        return {"path": str(p), "sheets": book.sheetnames}
    finally:
        book.close()

def edit_word(path: str | Path, spec: dict) -> dict:
    from docx import Document
    p = Path(path).resolve(strict=True)
    if p.suffix.lower() != ".docx":
        raise OfficeError("Only .docx documents are supported")
    doc = Document(p)
    for replacement in spec.get("replace", []):
        before, after = replacement["find"], replacement["with"]
        if not isinstance(before, str) or not before:
            raise OfficeError("Invalid replacement")
        for paragraph in doc.paragraphs:
            for run in paragraph.runs:
                if before in run.text:
                    run.text = run.text.replace(before, str(after))
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            if before in run.text:
                                run.text = run.text.replace(before, str(after))
    for paragraph in spec.get("append", []):
        if isinstance(paragraph, str):
            doc.add_paragraph(paragraph)
        elif isinstance(paragraph, dict):
            doc.add_heading(str(paragraph.get("heading","")), level=1)
            if paragraph.get("text"):
                doc.add_paragraph(str(paragraph["text"]))
        else:
            raise OfficeError("Invalid paragraph")
    _atomic_save(p, doc.save)
    return {"path":str(p),"paragraphs":len(doc.paragraphs)}

def edit_ppt(path: str | Path, spec: dict) -> dict:
    from pptx import Presentation
    p = Path(path).resolve(strict=True)
    if p.suffix.lower() != ".pptx":
        raise OfficeError("Only .pptx presentations are supported")
    pres = Presentation(p)
    for change in spec.get("slides", []):
        index = change["index"]
        if not isinstance(index, int) or not 0 <= index < len(pres.slides):
            raise OfficeError("Slide index out of range")
        slide = pres.slides[index]
        if "title" in change and slide.shapes.title:
            slide.shapes.title.text = str(change["title"])
        if "body" in change:
            for shape in slide.placeholders:
                if shape.has_text_frame and shape != slide.shapes.title:
                    shape.text = str(change["body"])
                    break
    for addition in spec.get("append", []):
        slide = pres.slides.add_slide(pres.slide_layouts[1])
        slide.shapes.title.text = str(addition.get("title",""))
        slide.placeholders[1].text = str(addition.get("body",""))
    _atomic_save(p, pres.save)
    return {"path":str(p),"slides":len(pres.slides)}

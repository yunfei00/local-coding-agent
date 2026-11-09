"""Safe, atomic edits of existing macro-free Office documents."""
from __future__ import annotations
from pathlib import Path
from agent.office.engine import _atomic_save, OfficeError

def edit_excel(path: str | Path, spec: dict) -> dict:
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.chart import BarChart, LineChart, Reference
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
            for chart_spec in changes.get("charts", []):
                kind = chart_spec.get("type", "bar")
                if kind not in ("bar", "line"):
                    raise OfficeError("Unsupported chart type")
                chart = BarChart() if kind == "bar" else LineChart()
                start_row = int(chart_spec.get("start_row", 1))
                end_row = int(chart_spec["end_row"])
                column = int(chart_spec.get("value_column", 2))
                if start_row < 1 or end_row <= start_row or column < 1:
                    raise OfficeError("Invalid chart range")
                values = Reference(sheet, min_col=column, min_row=start_row, max_row=end_row)
                chart.add_data(values, titles_from_data=True)
                if column > 1:
                    categories = Reference(sheet, min_col=1, min_row=start_row+1, max_row=end_row)
                    chart.set_categories(categories)
                chart.title = str(chart_spec.get("title", ""))
                sheet.add_chart(chart, str(chart_spec.get("anchor", "E2")))
            for col, width in changes.get("column_widths", {}).items():
                width = float(width)
                if width <= 0 or width > 255:
                    raise OfficeError("Invalid column width")
                sheet.column_dimensions[col].width = width
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
    for data in spec.get("tables", []):
        if not data or not isinstance(data, list) or not isinstance(data[0], list) or not data[0]:
            raise OfficeError("Invalid table")
        table = doc.add_table(rows=0, cols=len(data[0]))
        table.style = "Table Grid"
        for values in data:
            if len(values) != len(data[0]):
                raise OfficeError("Inconsistent table columns")
            for cell, value in zip(table.add_row().cells, values):
                cell.text = str(value)
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
    for change in spec.get("slides", []):
        if "notes" in change:
            index = change["index"]
            pres.slides[index].notes_slide.notes_text_frame.text = str(change["notes"])
    for addition in spec.get("append", []):
        slide = pres.slides.add_slide(pres.slide_layouts[1])
        slide.shapes.title.text = str(addition.get("title",""))
        slide.placeholders[1].text = str(addition.get("body",""))
    _atomic_save(p, pres.save)
    return {"path":str(p),"slides":len(pres.slides)}

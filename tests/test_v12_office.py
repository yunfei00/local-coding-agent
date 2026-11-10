import tempfile
import unittest
from pathlib import Path
from agent.office.engine import create_excel, inspect_excel, create_word, inspect_word, create_ppt, inspect_ppt
from agent.verification.office import verify_office
from agent.office.validation import validate_office_spec
from agent.tools.base import ToolError

class OfficeRoundTripTests(unittest.TestCase):
    def test_excel(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"book.xlsx"
            create_excel(path,{"Data":[["Item","Amount"],["A",12],["B","=B2*2"]]})
            data=inspect_excel(path)
            self.assertEqual(data["sheets"][0]["rows"][2][1],"=B2*2")
            self.assertTrue(verify_office(path)["ok"])

    def test_word(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"report.docx"
            create_word(path,"Report",[{"heading":"Summary","text":"Hello","table":[["A","B"],[1,2]]}])
            self.assertIn("Hello",inspect_word(path)["paragraphs"])
            self.assertTrue(verify_office(path)["ok"])

    def test_ppt(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"slides.pptx"
            create_ppt(path,[{"title":"Summary","body":"Hello"}])
            self.assertIn("Summary",inspect_ppt(path)["slides"][0])
            self.assertTrue(verify_office(path)["ok"])

class OfficeSpecValidationTests(unittest.TestCase):
    def test_excel_string_rows_rejected(self):
        with self.assertRaises(ToolError) as caught:
            validate_office_spec("create", "excel", {"sheets": {"Data": "not rows"}})
        self.assertIn("spec.sheets.Data", str(caught.exception))

    def test_excel_missing_sheets_rejected(self):
        with self.assertRaises(ToolError) as caught:
            validate_office_spec("create", "excel", {})
        self.assertIn("spec.sheets", str(caught.exception))

    def test_word_invalid_sections_rejected(self):
        with self.assertRaises(ToolError):
            validate_office_spec("create", "word", {"title": "Report", "sections": "text"})

    def test_bundle_missing_sheets_rejected(self):
        with self.assertRaises(ToolError):
            validate_office_spec("bundle", None, {"excel": {}, "word": {"title": "A", "sections": []}, "ppt": {"slides": []}})

    def test_valid_bundle(self):
        validate_office_spec("bundle", None, {
            "excel": {"sheets": {"Data": [["A", 1]]}},
            "word": {"title": "Report", "sections": [{"heading": "Summary", "text": "OK"}]},
            "ppt": {"slides": [{"title": "Summary", "body": "OK"}]},
        })


if __name__=="__main__":
    unittest.main()

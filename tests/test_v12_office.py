import tempfile
import unittest
from pathlib import Path
from agent.office.engine import create_excel, inspect_excel, create_word, inspect_word, create_ppt, inspect_ppt
from agent.verification.office import verify_office

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

if __name__=="__main__":
    unittest.main()

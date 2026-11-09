import asyncio
import tempfile
import unittest
from pathlib import Path
from agent.office.engine import create_excel,create_word,create_ppt
from agent.verification.pipeline import verify_deliverables,write_report
from agent.tools.verification import DeliverableVerifyTool
from agent.tools.workspace import Workspace

class P3AcceptanceTests(unittest.TestCase):
    def test_verify_three_documents_and_chinese_report(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            create_excel(root/"data.xlsx",{"Data":[["Name","Value"],["A","=2+3"]]})
            create_word(root/"report.docx","Analysis",[{"text":"Summary 5"}])
            create_ppt(root/"deck.pptx",[{"title":"Overview","body":"5 units"}])
            spec={"files":[
                {"path":"data.xlsx","expect":{"sheets":["Data"],"cells":[{"sheet":"Data","address":"B2","value":"=2+3"}]}},
                {"path":"report.docx","expect":{"contains":["Summary 5"],"min_items":1}},
                {"path":"deck.pptx","expect":{"contains":["Overview"],"min_items":1}}
            ]}
            result=verify_deliverables(root,spec)
            self.assertTrue(result["ok"],result)
            report=write_report(root,spec,"acceptance.md")
            self.assertTrue(report["verification"]["ok"])
            self.assertIn("自动化交付验收报告",(root/"acceptance.md").read_text(encoding="utf-8"))
            tool=DeliverableVerifyTool(Workspace(root))
            self.assertTrue(asyncio.run(tool.execute({"spec":spec})).ok)

    def test_mismatch_and_workspace_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            create_excel(root/"data.xlsx",{"Data":[["X"]]})
            result=verify_deliverables(root,{"files":[{"path":"data.xlsx","expect":{"sheets":["Missing"]}}]})
            self.assertFalse(result["ok"])
            with self.assertRaises(ValueError):
                verify_deliverables(root,{"files":[{"path":"../outside.xlsx"}]})
            with self.assertRaises(ValueError):
                write_report(root,{"files":[{"path":"data.xlsx"}]},"../escape.md")
            with self.assertRaises(ValueError):
                write_report(root,{"files":[{"path":"data.xlsx"}]},"data.xlsx")

if __name__=="__main__":
    unittest.main()

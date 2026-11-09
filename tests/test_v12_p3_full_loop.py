"""End-to-end local Office bundle -> verification -> repair -> report smoke."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from agent.tools.workspace import Workspace
from agent.tools.office import OfficeTool
from agent.tools.verification import DeliverableVerifyTool

class P3FullLoopTests(unittest.TestCase):
    def test_bundle_verify_repair_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            workspace=Workspace(d)
            office=OfficeTool(workspace)
            verify=DeliverableVerifyTool(workspace)
            async def run():
                bundle=await office.execute({"operation":"bundle","path":".","name":"delivery","spec":{
                    "excel":{"sheets":{"Data":[["Name","Value"],["A",1]]}},
                    "word":{"title":"Report","sections":[{"text":"Summary"}]},
                    "ppt":{"slides":[{"title":"Overview","body":"Delivery"}]}
                }})
                self.assertTrue(bundle.ok,bundle)
                spec={"files":[
                    {"path":"delivery.xlsx","expect":{"cells":[{"sheet":"Data","address":"B2","value":5}]}},
                    {"path":"delivery.docx","expect":{"contains":["Summary"]}},
                    {"path":"delivery.pptx","expect":{"contains":["Overview"]}}
                ]}
                before=await verify.execute({"spec":spec})
                self.assertFalse(before.ok)
                repaired=await verify.execute({"spec":spec,"repair":True,"max_rounds":2})
                self.assertTrue(repaired.ok,repaired)
                report=await verify.execute({"spec":spec,"report_path":"acceptance.md"})
                self.assertTrue(report.ok,report)
                self.assertTrue((Path(d)/"acceptance.md").is_file())
            asyncio.run(run())

if __name__=="__main__":
    unittest.main()

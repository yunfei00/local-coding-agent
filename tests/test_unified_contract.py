import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from scripts.validation.unified_contract import preserves_tests

ORIGINAL='import unittest\nfrom calculator import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(3,2),5)\n'


class IndependentContractTests(unittest.TestCase):
    def test_adding_test_cases_preserves_existing_assertions(self):
        self.assertTrue(preserves_tests(ORIGINAL,ORIGINAL+' def test_extra(self): self.assertEqual(add(0,0),0)\n'))

    def test_changing_assertion_or_skipping_original_test_is_rejected(self):
        self.assertFalse(preserves_tests(ORIGINAL,ORIGINAL.replace('),5)', '),1)')))
        self.assertFalse(preserves_tests(ORIGINAL,ORIGINAL.replace(' def test_add',' @unittest.skip("skip")\n def test_add')))

    def test_candidate_monkeypatch_cannot_fool_independent_original_test(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);project=root/'project';project.mkdir();(project/'tests').mkdir()
            original=root/'original.py';original.write_text(ORIGINAL,encoding='utf-8')
            (project/'calculator.py').write_text('def add(a,b): return a-b\n',encoding='utf-8')
            candidate=ORIGINAL+' def setUp(self):\n  global add\n  add=lambda a,b:5\n'
            (project/'tests/test_calc.py').write_text(candidate,encoding='utf-8')
            self.assertTrue(preserves_tests(ORIGINAL,candidate))
            script=Path(__file__).resolve().parents[1]/'scripts/validation/unified_contract.py'
            result=subprocess.run([sys.executable,str(script),'--original',str(original),'--project',str(project)],capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,1)
            self.assertFalse(json.loads(result.stdout)['passed'])

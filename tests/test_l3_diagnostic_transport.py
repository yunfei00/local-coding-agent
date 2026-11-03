import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from agent.core.task_diagnostics import export_diagnostics
from agent.llm.router import validate_config


class DiagnosticTransportTests(unittest.TestCase):
    def test_large_history_kept_on_disk_but_bounded_on_wire(self):
        calls = [dict(id=str(i),role='executor',route='api',model='model',status='failed',
                      reserved_tokens=100,reserved_cost=0,usage={'error_code':'NETWORK_ERROR'}) for i in range(2000)]
        task = dict(status='paused',planned=True,config=validate_config({}),last_error={
            'code':'VERIFICATION_TIMEOUT','command':'uv run pytest','exit_code':124,'summary':'secret-value'},
            transitions=[{'status':'paused','reason':'timeout'}]*2000)
        plans = SimpleNamespace(executions=lambda _: [{'tool':'run_command','status':'failed'}]*2000,
                                get=lambda _: {'steps':[{'state':'blocked','description':'Run tests'}]})
        runtime = SimpleNamespace(get=lambda _:task,calls=lambda *a,**k:calls,usage=lambda *a:{'api_calls':2000},plans=plans)
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(3):
                result = export_diagnostics(runtime,'task',Path(directory),('secret-value',))
                self.assertIsInstance(result,dict)
                wire = result['diagnostics']
                self.assertEqual(len(wire['json']['calls']),8)
                self.assertEqual(len(wire['json']['transitions']),8)
                self.assertLess(len(json.dumps(wire)),20000)
                self.assertLess(len(wire['markdown'].splitlines()),100)
                self.assertNotIn('secret-value',json.dumps(result))
                self.assertIn('uv run pytest',wire['markdown'])
                full = json.loads(Path(result['paths']['json']).read_text(encoding='utf-8'))
                self.assertEqual(len(full['calls']),2000)
                self.assertEqual(full['last_error']['exit_code'],124)

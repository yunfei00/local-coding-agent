"""错误诊断单元测试；不冒充真实 Windows 窗口或冻结后端验收。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from agent.desktop import worker


class PackagedWindowDiagnosticsTests(unittest.TestCase):
    def test_packaged_identity_failure_is_environmental_not_a_code_repair_request(self):
        from agent.core.execution import failure_diagnosis
        diagnosis=failure_diagnosis('desktop_list_windows','DESKTOP_WINDOW_ENUMERATION_FAILED')
        self.assertEqual(diagnosis['category'],'environment');self.assertFalse(diagnosis['safe_probe'])
        self.assertIn('packaged_dependencies',diagnosis['action'])

    def execute(self,arguments,pid=73):
        gui=SimpleNamespace(IsWindowVisible=lambda _:True,EnumWindows=lambda callback,arg:callback(1,arg))
        process=SimpleNamespace(GetWindowThreadProcessId=lambda _:(1,pid))
        with patch.object(worker,'initialize'),patch.object(worker,'gui',gui,create=True),patch.object(worker,'process',process,create=True):
            return worker.execute({'operation':'desktop_list_windows','arguments':arguments})

    def test_missing_dynamic_dependency_is_not_silently_reported_as_no_windows(self):
        problem=ModuleNotFoundError('private text must not be logged',name='win32timezone')
        with patch.object(worker,'identity',side_effect=problem):
            with self.assertRaises(worker.DesktopError) as caught:self.execute({'pid':73})
        self.assertEqual(caught.exception.code,'DESKTOP_WINDOW_ENUMERATION_FAILED')
        self.assertIn('win32timezone',caught.exception.message)
        self.assertNotIn('private text',caught.exception.message)

    def test_expected_security_denial_is_preserved_for_requested_pid(self):
        with patch.object(worker,'identity',side_effect=worker.DesktopError('DESKTOP_ELEVATION_DENIED','No elevated targets')):
            with self.assertRaises(worker.DesktopError) as caught:self.execute({'pid':73})
        self.assertEqual(caught.exception.code,'DESKTOP_ELEVATION_DENIED')

    def test_pid_filter_does_not_read_other_process_identity(self):
        with patch.object(worker,'identity',Mock(side_effect=AssertionError('unrelated process'))) as identity:
            result=self.execute({'pid':73},pid=99)
        identity.assert_not_called();self.assertEqual(result['windows'],[])
        self.assertEqual(result['diagnostics']['matched_visible'],0)

    def test_caption_activation_never_clicks_occluder_or_client_controls(self):
        for hit,region in [(99,2),(1,1),(1,20)]:
            gui=SimpleNamespace(GetWindowRect=lambda _:(0,0,400,200),WindowFromPoint=lambda _:hit,GetAncestor=lambda hwnd,_:hwnd,SendMessage=lambda *_:region)
            api=SimpleNamespace(SetCursorPos=Mock())
            with patch.object(worker,'check',return_value=1),patch.object(worker,'gui',gui,create=True),patch.object(worker,'api',api,create=True),patch.object(worker,'input_batch') as send:
                self.assertFalse(worker.caption_focus_click({}));send.assert_not_called()

    def test_caption_activation_uses_one_complete_mouse_batch_on_bound_window(self):
        gui=SimpleNamespace(GetWindowRect=lambda _:(0,0,400,200),WindowFromPoint=lambda _:1,GetAncestor=lambda hwnd,_:hwnd,SendMessage=lambda *_:2)
        api=SimpleNamespace(SetCursorPos=Mock())
        with patch.object(worker,'check',return_value=1),patch.object(worker,'gui',gui,create=True),patch.object(worker,'api',api,create=True),patch.object(worker,'input_batch') as send:
            self.assertTrue(worker.caption_focus_click({}));send.assert_called_once_with([(0,0,2),(0,0,4)])


if __name__=='__main__':unittest.main()

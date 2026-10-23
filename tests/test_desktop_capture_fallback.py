"""Regression coverage for guarded desktop capture and loop diagnostics."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from agent.desktop import worker
from agent.core.agent_loop import ToolLoopGuard


class DesktopCaptureFallbackTests(unittest.TestCase):
    def test_document_editor_mask_does_not_cover_chromium_root_document(self):
        editable=SimpleNamespace(element_info=SimpleNamespace(control_type='Document',class_name='RichEditD2DPT'))
        self.assertTrue(worker.private_editor(editable))
        readonly=SimpleNamespace(element_info=SimpleNamespace(control_type='Document',class_name='Chrome_RenderWidgetHostHWND'),iface_value=SimpleNamespace(CurrentIsReadOnly=True))
        self.assertFalse(worker.private_editor(readonly))
        editable.element_info.class_name='GenericDocument'
        editable.iface_value=SimpleNamespace(CurrentIsReadOnly=False)
        self.assertTrue(worker.private_editor(editable))

    def test_printwindow_black_placeholder_is_blank(self):
        self.assertTrue(worker._capture_looks_blank(Image.new("RGB", (200, 100), (0, 0, 0))))
        self.assertTrue(worker._capture_looks_blank(Image.new("RGB", (200, 100), (2, 2, 3))))
        self.assertFalse(worker._capture_looks_blank(Image.new("RGB", (200, 100), (255, 255, 255))))

    def test_foreground_guard_blocks_screen_read(self):
        gui = SimpleNamespace(GetForegroundWindow=lambda: 200, IsIconic=lambda hwnd: False)
        with patch.object(worker, "gui", gui, create=True):
            with self.assertRaises(worker.DesktopError) as captured:
                worker._capture_visible_client_only(100)
        self.assertEqual(captured.exception.code, "DESKTOP_CAPTURE_FOREGROUND_REQUIRED")

    def test_overlapping_window_blocks_screen_read(self):
        class FakeGUI:
            @staticmethod
            def GetForegroundWindow():
                return 100

            @staticmethod
            def IsIconic(hwnd):
                return False

            @staticmethod
            def IsWindowVisible(hwnd):
                return True

            @staticmethod
            def GetWindowRect(hwnd):
                return (20, 20, 50, 50)

            @staticmethod
            def EnumWindows(callback, extra):
                callback(200, extra)

        class FakeUser:
            @staticmethod
            def GetSystemMetrics(index):
                return {76: 0, 77: 0, 78: 1920, 79: 1080}[index]

        with patch.object(worker, "gui", FakeGUI, create=True), \
                patch.object(worker, "user", FakeUser, create=True), \
                patch.object(worker, "geometry", return_value={"client_origin": [10, 10], "client_size": [100, 100]}):
            with self.assertRaises(worker.DesktopError) as captured:
                worker._capture_visible_client_only(100)
        self.assertEqual(captured.exception.code, "DESKTOP_CAPTURE_OCCLUDED")


class CycleTraceTests(unittest.TestCase):
    def test_tool_names_retained_without_arguments(self):
        guard = ToolLoopGuard()
        guard.register_call("desktop_list_windows", {"pid": 123})
        guard.register_call("desktop_screenshot", {"window_id": "private-window"})
        self.assertEqual(guard.recent_tool_names, ["desktop_list_windows", "desktop_screenshot"])
        self.assertNotIn("private-window", " ".join(guard.recent_tool_names))


if __name__ == "__main__":
    unittest.main()

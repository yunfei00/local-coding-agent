"""Real API readiness probe. CI requires GUI execution, never a silent skip."""
import os
import unittest
from agent.desktop.session import require_interactive_session
from agent.tools.base import ToolError
from agent.desktop.resources import require_resources,MIB


def require_test_desktop():
    try:
        require_resources(minimum_available=1024*MIB,minimum_commit=1024*MIB)
        require_interactive_session()
    except ToolError as exc:
        if os.getenv('LCA_REQUIRE_INTERACTIVE_DESKTOP') == '1':
            raise
        raise unittest.SkipTest(exc.code + ': real interactive desktop unavailable; no GUI PASS claimed') from exc

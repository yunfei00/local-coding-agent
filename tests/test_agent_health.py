import unittest

from agent.core.version import APP_VERSION, PROTOCOL_VERSION
from agent.server.main import build_health_payload


class AgentHealthPayloadTests(unittest.TestCase):
    def test_health_payload_matches_runtime_version_contract(self) -> None:
        payload = build_health_payload(8765)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "local-coding-agent")
        self.assertEqual(payload["port"], 8765)
        self.assertEqual(payload["protocol"], PROTOCOL_VERSION)
        self.assertEqual(payload["version"], APP_VERSION)


if __name__ == "__main__":
    unittest.main()

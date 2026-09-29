import unittest

from agent.server.main import build_health_payload


class AgentHealthPayloadTests(unittest.TestCase):
    def test_health_payload_contains_phase9_contract(self) -> None:
        payload = build_health_payload(8765)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "local-coding-agent")
        self.assertEqual(payload["port"], 8765)
        self.assertEqual(payload["protocol"], "phase9")
        self.assertEqual(payload["version"], "0.1.0")


if __name__ == "__main__":
    unittest.main()

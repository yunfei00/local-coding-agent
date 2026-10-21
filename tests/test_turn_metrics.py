import unittest
from agent.core.turn_metrics import TurnMetrics


class TurnMetricsTests(unittest.TestCase):
    def test_metrics_are_bounded_and_argument_free(self):
        metrics = TurnMetrics()
        metrics.model_steps = 3
        metrics.retries = 1
        metrics.record_tool(12, ok=True)
        metrics.record_tool(-10, ok=False)
        summary = metrics.summary()
        self.assertEqual(summary["model_steps"], 3)
        self.assertEqual(summary["tool_calls"], 2)
        self.assertEqual(summary["tool_failures"], 1)
        self.assertEqual(summary["tool_duration_ms"], 12)
        self.assertEqual(summary["provider_retries"], 1)
        self.assertGreaterEqual(summary["elapsed_ms"], 0)
        self.assertNotIn("arguments", summary)
        self.assertNotIn("output", summary)


if __name__ == "__main__":
    unittest.main()

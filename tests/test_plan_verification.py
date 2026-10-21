import unittest

from agent.plan_verification import verification_passed


class PlanVerificationTests(unittest.TestCase):
    def test_empty_evidence_and_incomplete_loop(self):
        self.assertFalse(verification_passed("a", "", [], loop_complete=True))
        self.assertFalse(verification_passed(
            "a", "", [{"step_id": "a", "ok": True, "tool": "read_file"}],
            loop_complete=False))

    def test_other_step_command_cannot_verify_current_step(self):
        evidence = [
            {"step_id": "previous", "ok": True, "tool": "shell"},
            {"step_id": "current", "ok": True, "tool": "read_file"},
        ]
        self.assertFalse(verification_passed(
            "current", "run tests", evidence, loop_complete=True))

    def test_failed_tool_does_not_verify(self):
        self.assertFalse(verification_passed(
            "a", "run tests",
            [{"step_id": "a", "ok": False, "tool": "shell"}],
            loop_complete=True))

    def test_successful_command_satisfies_command_gate(self):
        self.assertTrue(verification_passed(
            "a", "run tests",
            [{"step_id": "a", "ok": True, "tool": "shell"}],
            loop_complete=True))

    def test_no_command_required_allows_successful_read(self):
        self.assertTrue(verification_passed(
            "a", "",
            [{"step_id": "a", "ok": True, "tool": "read_file"}],
            loop_complete=True))


if __name__ == "__main__":
    unittest.main()

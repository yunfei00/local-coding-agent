import unittest

from agent.server.protocol import envelope, validate_client_message
from agent.server.state import InMemoryState


class ProtocolTests(unittest.TestCase):
    def test_envelope_contains_required_fields(self) -> None:
        message = envelope(
            "turn.delta",
            {"delta": "abc"},
            request_id="req_1",
            thread_id="thread_1",
            turn_id="turn_1",
        )

        self.assertEqual(message["type"], "turn.delta")
        self.assertEqual(message["request_id"], "req_1")
        self.assertEqual(message["thread_id"], "thread_1")
        self.assertEqual(message["turn_id"], "turn_1")
        self.assertEqual(message["payload"]["delta"], "abc")
        self.assertTrue(message["timestamp"])

    def test_validate_rejects_invalid_payload(self) -> None:
        valid, reason = validate_client_message({"type": "thread.create", "payload": []})
        self.assertFalse(valid)
        self.assertEqual(reason, "payload_must_be_object")

    def test_thread_state_create_and_list(self) -> None:
        state = InMemoryState()
        first = state.create_thread("First")
        second = state.create_thread("Second")

        self.assertIsNotNone(state.get_thread(first.id))
        ids = {thread.id for thread in state.list_threads()}
        self.assertEqual(ids, {first.id, second.id})


if __name__ == "__main__":
    unittest.main()

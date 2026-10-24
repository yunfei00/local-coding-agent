"""Slow UIA probes must not turn observed input into false mismatch evidence."""
import unittest
from unittest.mock import patch

from agent.desktop.worker import acknowledge_edit, DesktopError


class InputAcknowledgementTests(unittest.TestCase):
    def test_second_matching_rpc_crossing_deadline_is_successful_observation(self):
        clock={'now':0}
        readings=iter([(1,'expected'),(4,'expected')])
        def read():
            clock['now'],value=next(readings)
            return value
        with patch('agent.desktop.worker.time.monotonic',side_effect=lambda:clock['now']), \
             patch('agent.desktop.worker.time.sleep'):
            acknowledge_edit(read,lambda:None,'expected',timeout=3)
        self.assertEqual(clock['now'],4)

    def test_late_nonmatching_rpc_fails_with_lengths_only(self):
        clock={'now':0}
        def read():
            clock['now']=4
            return 'PRIVATE_OBSERVED_TEXT'
        with patch('agent.desktop.worker.time.monotonic',side_effect=lambda:clock['now']), \
             patch('agent.desktop.worker.time.sleep'), self.assertRaises(DesktopError) as caught:
            acknowledge_edit(read,lambda:None,'PRIVATE_REQUESTED_TEXT')
        self.assertEqual(caught.exception.code,'DESKTOP_VALUE_MISMATCH')
        self.assertIn('observed_length=',caught.exception.message)
        self.assertNotIn('PRIVATE_',caught.exception.message)

    def test_focus_loss_between_matching_reads_cannot_be_accepted(self):
        calls=[]
        def focus():
            calls.append('focus')
            if len(calls)==3:
                raise DesktopError('DESKTOP_FOCUS_FAILED','Lost exact input focus')
        def read():
            calls.append('read')
            return 'expected'
        with patch('agent.desktop.worker.time.sleep'), self.assertRaises(DesktopError) as caught:
            acknowledge_edit(read,focus,'expected')
        self.assertEqual(caught.exception.code,'DESKTOP_FOCUS_FAILED')
        self.assertEqual(calls,['focus','read','focus'])

    def test_clear_requires_two_consecutive_empty_values_before_typing(self):
        values=iter(['old','','old','',''])
        reads=[]
        def read():
            value=next(values);reads.append(value);return value
        with patch('agent.desktop.worker.time.sleep'):
            acknowledge_edit(read,lambda:None,'',timeout=2,stage='clear')
        self.assertEqual(reads,['old','','old','',''])

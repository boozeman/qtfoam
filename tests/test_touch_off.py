import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from qtfoam.backend import DemoBackend, LinuxCNCBackend

class TouchOffTests(unittest.TestCase):
    def ready(self):
        b = DemoBackend()
        b.execute('reset')
        b.execute('on')
        return b

    def test_demo_zero_preserves_machine_and_invalidates_preview(self):
        b = self.ready()
        original = b.data['machine'].copy()
        context = b.preview_context('G0 X0')
        b.execute('touch_off')
        self.assertEqual(b.data['machine'], original)
        self.assertEqual(b.data['work'], dict.fromkeys('XYUV', 0.))
        self.assertFalse(b.preview_matches(context))
        self.assertEqual(b.preview_context('M2')['baseline']['g5x'][6], original['U'])

    def test_interlocks_and_explicit_g54_selection(self):
        b = DemoBackend()
        with self.assertRaises(ValueError):
            b.execute('touch_off')
        b = self.ready()
        b.data['wcs'] = 2
        with self.assertRaises(ValueError):
            b.execute('touch_off')
        b.execute('work_g54')
        b.execute('touch_off')
        b.data['pending'] = True
        with self.assertRaises(ValueError):
            b.execute('touch_off')

    def test_linuxcnc_command_has_no_motion_and_mode_failure_blocks(self):
        b = LinuxCNCBackend.__new__(LinuxCNCBackend)
        b.programs = Mock()
        b.api = SimpleNamespace(MODE_MDI=3, RCS_DONE=1)
        b.command = Mock(serial=42)
        b.command.wait_complete.return_value = 1
        b.snapshot = lambda: self.ready().snapshot()
        b.execute('touch_off')
        b.command.mdi.assert_called_once_with('G10 L20 P1 X0 Y0 U0 V0')
        self.assertEqual(b.pending, 42)
        b.command.reset_mock()
        b.command.wait_complete.return_value = -1
        with self.assertRaises(RuntimeError):
            b.execute('touch_off')
        b.command.mdi.assert_not_called()
        self.assertTrue(b.blocked)

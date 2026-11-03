import math
from types import SimpleNamespace
import unittest
from qtfoam.model import positions, permissions, validate_mdi
from qtfoam.backend import DemoBackend, LinuxCNCBackend
from unittest.mock import Mock


class ModelTests(unittest.TestCase):
    def test_sparse_uv_coordinates_and_rotated_work_offsets(self):
        s = SimpleNamespace(actual_position=[10,20,999,0,0,0,70,80,0],
                            g5x_offset=[1,2,0,0,0,0,7,8,0],
                            tool_offset=[0]*9, g92_offset=[0]*9, rotation_xy=90)
        machine, work = positions(s)
        self.assertEqual(machine, {'X':10.,'Y':20.,'U':70.,'V':80.})
        self.assertAlmostEqual(work['X'],18)
        self.assertAlmostEqual(work['Y'],-9)
        self.assertEqual(work['U'],63)
        s.actual_position[6] = math.nan
        with self.assertRaises(ValueError):
            positions(s)

    def test_mdi_gates_and_input(self):
        backend = DemoBackend()
        self.assertFalse(permissions(backend.snapshot())['mdi'])
        backend.execute('reset')
        backend.execute('on')
        backend.execute('mdi_mode')
        self.assertTrue(permissions(backend.snapshot())['mdi'])
        backend.data['homed'][3] = False
        self.assertFalse(permissions(backend.snapshot())['mdi'])
        for text in ('', 'G0\nX1', 'G1\tX2', 'G0ä', 'G'*255):
            with self.assertRaises(ValueError):
                validate_mdi(text)
        self.assertEqual(validate_mdi(' G90 '),'G90')
        self.assertFalse(any(permissions(None).values()))

    def test_pending_blocks_mdi_but_safety_requests_do_not_poll(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        backend.api = SimpleNamespace(STATE_ESTOP=1, STATE_OFF=2)
        backend.command = Mock()
        backend.snapshot = Mock(side_effect=RuntimeError('status lost'))
        for action in ('estop','off','abort'):
            backend.execute(action)
        backend.snapshot.assert_not_called()
        backend.command.abort.assert_called_once()
        backend.command.state.assert_any_call(1)
        backend.command.state.assert_any_call(2)

    def test_homing_uses_joint_index_and_stops_if_mode_unconfirmed(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        backend.api = SimpleNamespace(RCS_DONE=1)
        data = DemoBackend().snapshot()
        data.update(estop=False,enabled=True)
        backend.snapshot = lambda: data
        backend.command = Mock(serial=12)
        backend.command.wait_complete.return_value = 1
        backend.execute('home',axis='U')
        backend.command.home.assert_called_once_with(2)
        backend.command.wait_complete.return_value = -1
        backend.command.home.reset_mock()
        with self.assertRaises(RuntimeError):
            backend.execute('home',axis='V')
        backend.command.home.assert_not_called()


if __name__ == '__main__':
    unittest.main()

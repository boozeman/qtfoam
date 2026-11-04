import math
from types import SimpleNamespace
import unittest
from qtfoam.model import positions, permissions, validate_mdi, expand_mdi_shortcut
from qtfoam.backend import DemoBackend, LinuxCNCBackend
from unittest.mock import Mock
from collections import deque


class ModelTests(unittest.TestCase):
    def test_switch_status_reads_exact_hal_signals_and_missing_values(self):
        from qtfoam.backend import switch_status
        values = {'joint-0-home': True, 'pos-limit-joint-2': True}
        def read(name):
            if name == 'joint-3-home':
                raise RuntimeError('missing')
            return values.get(name, False)
        read_hal = Mock(side_effect=read)
        self.assertEqual(switch_status(read_hal),
                         {'home': [True, False, False, None],
                          'pos_limit': [False, False, True, False]})
        self.assertEqual(read_hal.call_count, 8)
        self.assertEqual(switch_status(), {'home': [None]*4, 'pos_limit': [None]*4})

    def limit_backend(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        backend.api = SimpleNamespace(STATE_ESTOP=1, STATE_ESTOP_RESET=2)
        backend.status = SimpleNamespace(estop=False)
        backend.command = Mock(serial=42)
        backend.programs = Mock()
        backend.halted_axes = [False]*4
        backend.pending = None
        backend.blocked = False
        backend.read_hal = Mock(return_value=False)
        return backend

    def test_positive_limit_latches_stops_and_requires_released_readable_reset(self):
        backend = self.limit_backend()
        backend.read_hal.side_effect = lambda name: name == 'pos-limit-joint-2'
        switches = backend.poll_switches()
        self.assertEqual(switches['halted'], [False, False, True, False])
        backend.command.state.assert_called_once_with(backend.api.STATE_ESTOP)
        backend.programs.cancel.assert_called()
        self.assertIsNone(backend.programs.running)
        backend.status.estop = True
        backend.poll_switches()
        self.assertEqual(backend.command.state.call_count, 1)
        data = DemoBackend().snapshot().copy()
        data.update(estop=True, switches=switches)
        backend.snapshot = lambda: data
        with self.assertRaises(ValueError):
            backend.execute('reset')
        with self.assertRaises(ValueError):
            backend.execute('run')
        data['switches']['pos_limit'][2] = None
        with self.assertRaises(ValueError):
            backend.execute('reset')
        backend.read_hal.side_effect = None
        backend.read_hal.return_value = False
        data['switches'] = backend.poll_switches()
        self.assertTrue(backend.halted_axes[2])
        backend.execute('reset')
        backend.command.state.assert_called_with(backend.api.STATE_ESTOP_RESET)
        self.assertFalse(any(backend.halted_axes))
        # A later limit activation must trip again.
        backend.read_hal.side_effect = lambda name: name == 'pos-limit-joint-0'
        backend.poll_switches()
        self.assertTrue(backend.halted_axes[0])
        backend.command.state.assert_called_with(backend.api.STATE_ESTOP)

    def test_limit_latches_before_command_failure_and_before_status_poll(self):
        backend = self.limit_backend()
        backend.read_hal.side_effect = lambda name: name == 'pos-limit-joint-1'
        backend.command.state.side_effect = RuntimeError('channel failed')
        with self.assertRaises(RuntimeError):
            backend.snapshot()
        self.assertTrue(backend.halted_axes[1])
        backend.command.state.side_effect = None
        backend.status.poll = Mock(side_effect=RuntimeError('poll failed'))
        with self.assertRaises(RuntimeError):
            backend.snapshot()
        backend.command.state.assert_called_with(backend.api.STATE_ESTOP)
        self.assertTrue(backend.halted_axes[1])

    def test_limit_snapshot_cancels_program_before_it_can_advance(self):
        backend = self.limit_backend()
        backend.read_hal.side_effect = lambda name: name == 'pos-limit-joint-3'
        backend.status = SimpleNamespace(
            estop=False, poll=Mock(), axis_mask=195, joints=4,
            actual_position=[0.]*9, g5x_offset=[0.]*9, tool_offset=[0.]*9,
            g92_offset=[0.]*9, rotation_xy=0., ini_filename='/machine.ini',
            linear_units=1., echo_serial_number=0, interp_state=1,
            homed=[True]*4, joint=[{} for _ in range(4)], enabled=True,
            paused=False, task_mode=1, file='', motion_line=0)
        backend.api.MODE_MANUAL, backend.api.MODE_AUTO, backend.api.MODE_MDI = 1, 2, 3
        backend.api.INTERP_IDLE = 1
        backend._geometry_key = ('/machine.ini', 1.)
        backend.geometry, backend.geometry_error = None, ''
        backend.poll_messages = Mock()
        backend.programs.phase = None
        backend.programs.control_serial = None
        backend.programs.describe.return_value = {}
        backend.programs.update.side_effect = lambda *args: self.assertIsNone(backend.programs.running)
        data = backend.snapshot()
        self.assertTrue(data['estop'])
        self.assertFalse(data['enabled'])
        self.assertEqual(data['switches']['halted'], [False, False, False, True])
        backend.command.state.assert_called_once_with(backend.api.STATE_ESTOP)

    def test_xu_shortcut_only_expands_a_whole_numeric_input(self):
        for text, value in [('400XU','400'), ('  -10xu  ','-10'),
                            ('125,50 XU','125.5'), ('.5XU','0.5'),
                            ('+00400.0XU','400'), ('-0XU','0')]:
            with self.subTest(text=text):
                self.assertEqual(expand_mdi_shortcut(text), f'G21 G90 G0 X{value} U{value}')
        for text in ('G0 X400 U400', 'G91 G1 X10 U10 F80', '(400XU)', 'M8'):
            self.assertIsNone(expand_mdi_shortcut(text))
        for text in ('nanXU', 'infXU', '1e3XU', '400..5XU', 'G0 400XU', '400\nXU'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                expand_mdi_shortcut(text)

    def test_linuxcnc_messages_keep_repeated_events_and_only_errors_cancel_start(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        backend.api = SimpleNamespace(NML_ERROR=1, OPERATOR_ERROR=2,
                                      NML_DISPLAY=3, OPERATOR_DISPLAY=4)
        backend.linuxcnc_messages = deque(maxlen=100)
        backend.message_serial = 0
        backend.programs = Mock()
        backend.errors = Mock()
        backend.errors.poll.side_effect = [(3, 'Heat wire'), (5, 'Ready'),
                                           (5, 'Ready'), None]
        backend.poll_messages()
        backend.programs.cancel.assert_not_called()
        self.assertEqual([m[2:] for m in backend.linuxcnc_messages],
                         [('DISPLAY', 'Heat wire'), ('INFO', 'Ready'), ('INFO', 'Ready')])
        backend.errors.poll.side_effect = [(2, 'Limit reached'), None]
        backend.poll_messages()
        backend.programs.cancel.assert_called_once()
        self.assertEqual(backend.linuxcnc_messages[-1][2:], ('ERROR', 'Limit reached'))
        backend.errors.poll.side_effect = [(5, 'Repeated')] * 100
        backend.poll_messages()
        self.assertEqual(len(backend.linuxcnc_messages), 100)
        self.assertEqual(backend.linuxcnc_messages[-1][0], 104)

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

    def test_home_all_requires_home_sequence_before_any_machine_command(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        ini = Mock()
        ini.find.return_value = None
        backend.api = SimpleNamespace(RCS_DONE=1, ini=Mock(return_value=ini))
        backend.status = SimpleNamespace(ini_filename='/machine.ini')
        data = DemoBackend().snapshot()
        data.update(estop=False, enabled=True)
        backend.snapshot = lambda: data
        backend.command = Mock(serial=12)
        backend.command.wait_complete.return_value = 1
        with self.assertRaisesRegex(ValueError, 'Have you defined HOME_SEQUENCE'):
            backend.execute('home')
        self.assertIn('HOME_SEQUENCE', backend.message)
        self.assertEqual(backend.command.mock_calls, [])
        self.assertEqual(ini.find.call_count, 4)
        # Zero and negative sequences are valid; individual homing needs no sequence.
        for sequence in ('0', '-1'):
            ini.find.return_value = sequence
            backend.command.reset_mock()
            backend.execute('home')
            backend.command.teleop_enable.assert_called_once_with(False)
            backend.command.home.assert_called_once_with(-1)
        ini.find.return_value = None
        backend.command.reset_mock()
        backend.execute('home', axis='X')
        backend.command.home.assert_called_once_with(0)


if __name__ == '__main__':
    unittest.main()

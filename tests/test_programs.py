from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from qtfoam.programs import ProgramRunner
from qtfoam.preview import prepare_context
from qtfoam.backend import LinuxCNCBackend


class Command:
    def __init__(self):
        self.serial = 0
        self.calls = []
    def record(self, name, *args):
        self.serial += 1
        self.calls.append((name,*args))
    def mode(self, mode): self.record('mode',mode)
    def program_open(self, path): self.record('open',path)
    def auto(self, *args): self.record('auto',*args)
    def abort(self): self.record('abort')
    def state(self, state): self.record('state',state)


class ProgramTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.api = SimpleNamespace(MODE_MANUAL=1,MODE_AUTO=2,MODE_MDI=3,INTERP_IDLE=1,
                                   AUTO_RUN=0,AUTO_PAUSE=1,AUTO_RESUME=2,STATE_ESTOP=1,STATE_OFF=2,
                                   ini=lambda path:SimpleNamespace(find=lambda *args:None))
        self.s = SimpleNamespace(actual_position=[0.]*9,g5x_offset=[0.]*9,g92_offset=[0.]*9,
                                 tool_offset=[0.]*9,rotation_xy=0.,g5x_index=1,linear_units=1.,
                                 enabled=True,estop=False,homed=[1]*4,joint=[{} for _ in range(4)],
                                 interp_state=1,paused=False,task_mode=1,echo_serial_number=0,
                                 file='',motion_line=0,ini_filename='/machine.ini',axis_mask=195,joints=4,
                                 current_vel=0.,inpos=True)
        self.c = Command()
        self.runner = ProgramRunner(self.api,self.c,Path(self.folder.name)/'programs')
        self.context = prepare_context(self.s,'G1 X10 U20 F100\nM2')
        self.runner.save(self.context,self.s)

    def started(self):
        self.runner.start(self.s)
        self.s.task_mode = self.api.MODE_AUTO
        self.s.echo_serial_number = self.c.serial
        self.runner.update(self.s)
        self.s.file = str(self.runner.record['path'])
        self.s.echo_serial_number = self.c.serial
        self.runner.update(self.s)
        self.s.echo_serial_number = self.c.serial
        self.s.interp_state = 2

    def test_requires_separate_mode_and_open_ack_and_runs_once(self):
        self.runner.start(self.s)
        self.runner.update(self.s)
        self.assertEqual(self.c.calls,[('mode',2)])
        self.s.echo_serial_number = self.c.serial
        self.s.task_mode = 2
        self.runner.update(self.s)
        self.assertEqual(self.c.calls[-1],('open',str(self.runner.record['path'])))
        self.runner.update(self.s)
        self.assertEqual(len(self.c.calls),2)
        self.s.file = str(self.runner.record['path'])
        self.s.echo_serial_number = self.c.serial
        self.runner.update(self.s)
        self.assertEqual(self.c.calls[-1],('auto',0,0))
        self.assertTrue(self.runner.record['used'])
        self.s.echo_serial_number = self.c.serial
        self.runner.update(self.s)
        with self.assertRaises(ValueError):
            self.runner.start(self.s)
        self.assertEqual(len([c for c in self.c.calls if c == ('auto',0,0)]),1)
        self.assertEqual(self.runner.record['path'].read_text(),self.context['text'])

    def test_homing_position_offsets_and_pending_gate_start(self):
        for change in ('homed','position','offset','pending','estop','moving'):
            with self.subTest(change=change):
                self.s.homed = [1]*4
                self.s.actual_position = [0.]*9
                self.s.g92_offset = [0.]*9
                self.s.estop = False
                self.s.current_vel = 0.
                if change == 'homed': self.s.homed[3] = 0
                if change == 'position': self.s.actual_position[6] = 1
                if change == 'offset': self.s.g92_offset[6] = 1
                if change == 'estop': self.s.estop = True
                if change == 'moving': self.s.current_vel = .5
                with self.assertRaises(ValueError):
                    self.runner.start(self.s,pending=change=='pending')
        self.assertEqual(self.c.calls,[])

    def test_changed_copy_or_context_cannot_reach_run(self):
        self.runner.start(self.s)
        self.s.echo_serial_number = self.c.serial
        self.s.task_mode = 2
        self.runner.record['path'].write_text('G0 X999')
        self.runner.update(self.s)
        self.assertIsNone(self.runner.phase)
        self.assertEqual(len(self.c.calls),1)
        self.assertIn('changed',self.runner.message)

    def test_wrong_loaded_file_and_timeout_never_run(self):
        self.runner.start(self.s)
        self.s.echo_serial_number = self.c.serial
        self.s.task_mode = 2
        self.runner.update(self.s)
        self.s.echo_serial_number = self.c.serial
        self.s.file = '/another.ngc'
        self.runner.update(self.s)
        self.assertIsNone(self.runner.phase)
        self.assertFalse(any(c[0]=='auto' for c in self.c.calls))
        self.runner.start(self.s)
        with patch('qtfoam.programs.time.monotonic',return_value=self.runner.deadline+1):
            self.runner.update(self.s)
        self.assertIn('timed out',self.runner.message)
        self.assertFalse(any(c[0]=='auto' for c in self.c.calls))

    def test_uncertain_run_is_consumed_before_api_call(self):
        self.runner.start(self.s)
        self.s.task_mode = 2
        self.s.echo_serial_number = self.c.serial
        self.runner.update(self.s)
        self.s.file = str(self.runner.record['path'])
        self.s.echo_serial_number = self.c.serial
        def uncertain(*args):
            self.assertTrue(self.runner.record['used'])
            self.c.record('auto',*args)
            raise RuntimeError('response lost')
        self.c.auto = uncertain
        self.runner.update(self.s)
        self.runner.update(self.s)
        self.assertEqual(len([c for c in self.c.calls if c[0]=='auto']),1)
        with self.assertRaises(ValueError):
            self.runner.start(self.s)

    def test_pause_resume_m0_and_loaded_program_identity(self):
        self.started()
        self.assertTrue(self.runner.describe(self.s)['pause'])
        self.runner.control('pause',self.s)
        with self.assertRaises(ValueError):
            self.runner.control('pause',self.s)
        self.s.echo_serial_number = self.c.serial
        self.s.paused = True
        self.runner.update(self.s)
        self.assertTrue(self.runner.describe(self.s)['resume'])
        self.runner.control('resume',self.s)
        self.assertEqual(self.c.calls[-1],('auto',self.api.AUTO_RESUME))
        self.s.file = '/unrelated.ngc'
        self.s.echo_serial_number = self.c.serial
        self.runner.update(self.s)
        with self.assertRaises(ValueError):
            self.runner.control('resume',self.s)

    def test_native_backend_advances_only_during_fresh_status_polls(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        backend.api,backend.command,backend.status = self.api,self.c,self.s
        backend.programs = self.runner
        backend.pending = None
        backend.blocked = False
        backend.message = ''
        backend.errors = SimpleNamespace(poll=lambda:None)
        self.s.poll = lambda:None
        backend.execute('run')
        self.assertTrue(backend.snapshot()['pending'])
        self.assertEqual(self.c.calls,[('mode',2)])
        self.s.task_mode = 2
        self.s.echo_serial_number = self.c.serial
        backend.snapshot()
        self.assertEqual(self.c.calls[-1][0],'open')
        self.s.file = str(self.runner.record['path'])
        self.s.echo_serial_number = self.c.serial
        self.assertTrue(backend.snapshot()['pending'])
        self.assertEqual(self.c.calls[-1],('auto',0,0))
        self.s.echo_serial_number = self.c.serial
        self.s.interp_state = 2
        self.assertTrue(backend.snapshot()['program']['pause'])
        backend.execute('pause')
        self.assertTrue(backend.snapshot()['pending'])
        self.s.echo_serial_number = self.c.serial
        self.s.paused = True
        self.assertTrue(backend.snapshot()['program']['resume'])

    def test_safety_cancels_preparation_before_status_can_advance_it(self):
        backend = LinuxCNCBackend.__new__(LinuxCNCBackend)
        backend.api, backend.command, backend.status = self.api,self.c,self.s
        backend.programs = self.runner
        backend.pending = None
        backend.blocked = False
        backend.message = ''
        self.runner.start(self.s)
        self.s.echo_serial_number = self.c.serial
        self.s.task_mode = 2
        backend.execute('abort')
        self.runner.update(self.s)
        self.assertEqual(self.c.calls,[('mode',2),('abort',)])
        self.assertIsNone(self.runner.phase)


if __name__ == '__main__':
    unittest.main()

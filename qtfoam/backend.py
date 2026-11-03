"""Local LinuxCNC bridge. No network, Docker or Foamomatic service required."""
import time
from .model import JOINTS, permissions, positions, validate_mdi


class LinuxCNCBackend:
    def __init__(self):
        import linuxcnc
        self.api = linuxcnc
        self.status = linuxcnc.stat()
        self.command = linuxcnc.command()
        # This screen has no ScreenOptions widget; it owns its error consumer.
        self.errors = linuxcnc.error_channel()
        self.pending = None
        self.pending_since = 0
        self.blocked = False
        self.message = ''

    def snapshot(self):
        s = self.status
        s.poll()
        if s.axis_mask != 195 or s.joints != 4:
            raise ValueError('QtFoam requires exactly X/Y/U/V and four joints in X/Y/U/V order')
        machine, work = positions(s)
        error = self.errors.poll()
        if error:
            self.message = str(error[1])
        if self.pending is not None and s.echo_serial_number >= self.pending and s.interp_state == self.api.INTERP_IDLE:
            self.pending = None
        if (self.pending is not None and s.echo_serial_number < self.pending
                and time.monotonic() - self.pending_since > 10):
            self.blocked = True
            self.message = 'Command completion uncertain. Inspect LinuxCNC; use Abort before further commands.'
        names = {self.api.MODE_MANUAL: 'Manual', self.api.MODE_AUTO: 'Auto', self.api.MODE_MDI: 'MDI'}
        return {'connected': True, 'machine': machine, 'work': work,
                'homed': list(s.homed)[:4],
                'homing': [bool(j.get('homing', False)) for j in s.joint[:4]],
                'enabled': bool(s.enabled), 'estop': bool(s.estop),
                'idle': s.interp_state == self.api.INTERP_IDLE,
                'paused': bool(s.paused), 'mode': names.get(s.task_mode, 'Unknown'),
                'pending': self.pending is not None or self.blocked,
                'file': s.file, 'line': s.motion_line, 'message': self.message,
                'units': 'mm' if abs(s.linear_units - 1) < 1e-6 else 'machine units'}

    def execute(self, action, axis=None, text=None):
        # Safety requests bypass a failed status poll or a pending command.
        if action in ('estop', 'off', 'abort'):
            if action == 'abort':
                self.command.abort()
            else:
                self.command.state(self.api.STATE_ESTOP if action == 'estop' else self.api.STATE_OFF)
            self.blocked = False
            self.pending = None
            self.message = ''
            return
        data = self.snapshot()
        if not permissions(data).get(action, False):
            raise ValueError('Command unavailable in the current machine state')
        if action == 'reset':
            self.command.state(self.api.STATE_ESTOP_RESET)
        elif action == 'on':
            self.command.state(self.api.STATE_ON)
        elif action in ('manual', 'mdi_mode'):
            self.command.mode(self.api.MODE_MANUAL if action == 'manual' else self.api.MODE_MDI)
        elif action == 'home':
            joint = -1 if axis is None else JOINTS[axis]
            # Explicit joint mode, with confirmed completion, before homing.
            self.command.teleop_enable(False)
            if self.command.wait_complete(1) != self.api.RCS_DONE:
                raise RuntimeError('Could not confirm joint mode; homing was not submitted')
            self.command.home(joint)
        elif action == 'mdi':
            self.command.mdi(validate_mdi(text))
        else:
            raise ValueError('Unknown command')
        self.pending = self.command.serial
        self.pending_since = time.monotonic()


class DemoBackend:
    """Never imports LinuxCNC; all controls affect this object only."""
    def __init__(self):
        self.data = {'connected': True, 'machine': {'X': 125., 'Y': 90., 'U': 210., 'V': 65.},
                     'work': {'X': 125., 'Y': 90., 'U': 210., 'V': 65.},
                     'homed': [True]*4, 'homing': [False]*4, 'enabled': False,
                     'estop': True, 'idle': True, 'paused': False, 'mode': 'Manual',
                     'pending': False, 'file': '', 'line': 0, 'units': 'mm',
                     'message': 'DEMO — no connection to machinery'}

    def snapshot(self):
        return self.data

    def execute(self, action, axis=None, text=None):
        if not permissions(self.data).get(action, False):
            raise ValueError('Command unavailable in demo machine state')
        if action == 'estop':
            self.data.update(estop=True, enabled=False)
        elif action == 'reset':
            self.data['estop'] = False
        elif action in ('on', 'off'):
            self.data['enabled'] = action == 'on'
        elif action in ('manual', 'mdi_mode'):
            self.data['mode'] = 'Manual' if action == 'manual' else 'MDI'
        elif action == 'home':
            for name, index in JOINTS.items():
                if axis is None or name == axis:
                    self.data['homed'][index] = True
                    self.data['machine'][name] = self.data['work'][name] = 0.
        elif action == 'mdi':
            self.data['message'] = 'DEMO: accepted ' + validate_mdi(text)

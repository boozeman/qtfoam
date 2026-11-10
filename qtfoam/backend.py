"""Local LinuxCNC bridge. No network, Docker or Foamomatic service required."""
import time
from collections import deque
from datetime import datetime
from .model import JOINTS, permissions, positions, validate_mdi


def switch_status(read_hal=None):
    """Read the configured HAL switch signals without changing their polarity."""
    result = {'home': [], 'pos_limit': []}
    for index in range(4):
        for key, name in (('home', f'joint-{index}-home'),
                          ('pos_limit', f'pos-limit-joint-{index}')):
            try:
                value = bool(read_hal(name)) if read_hal else None
            except (RuntimeError, ValueError):
                value = None
            result[key].append(value)
    return result


class LinuxCNCBackend:
    def __init__(self):
        import linuxcnc
        import hal
        self.read_hal = hal.get_value
        self.halted_axes = [False]*4
        self._limit_estop_sent = False
        self.api = linuxcnc
        self.status = linuxcnc.stat()
        self.command = linuxcnc.command()
        # This screen has no ScreenOptions widget; it owns its error consumer.
        self.errors = linuxcnc.error_channel()
        self.linuxcnc_messages = deque(maxlen=100)
        self.message_serial = 0
        self.pending = None
        self.pending_since = 0
        self.blocked = False
        self.message = ''
        from .programs import ProgramRunner
        self.programs = ProgramRunner(self.api,self.command)

    def poll_switches(self):
        switches = switch_status(getattr(self, 'read_hal', None))
        previous = getattr(self, 'halted_axes', [False]*4)
        self.halted_axes = [latched or bool(active)
                            for latched, active in zip(previous, switches['pos_limit'])]
        if any(self.halted_axes):
            # Latch before sending, so a command-channel failure cannot erase the fault.
            if not getattr(self, '_limit_estop_sent', False) or not self.status.estop:
                self.execute('estop')
                self._limit_estop_sent = True
            axes = ', '.join(axis for axis, halted in zip(JOINTS, self.halted_axes) if halted)
            self.message = 'Positive limit: ' + axes + ' — Halted. Release limits, then Reset E-stop.'
        switches['halted'] = list(self.halted_axes)
        return switches

    def snapshot(self):
        # Check HAL before NML polling/geometry/program work, even if those fail.
        switches = self.poll_switches()
        s = self.status
        try:
            s.poll()
        except Exception:
            self.programs.clear()
            self.programs.running = None
            raise
        if s.axis_mask != 195 or s.joints != 4:
            self.programs.cancel('Machine configuration changed; start cancelled')
            raise ValueError('QtFoam requires exactly X/Y/U/V and four joints in X/Y/U/V order')
        machine, work = positions(s)
        geometry_key = (s.ini_filename, s.linear_units)
        if getattr(self, '_geometry_key', None) != geometry_key:
            from .geometry import read_geometry
            try:
                self.geometry = read_geometry(self.api.ini(s.ini_filename), s.linear_units)
                self.geometry_error = ''
            except Exception as exc:
                self.geometry = None
                self.geometry_error = 'Visualization unavailable: ' + str(exc)
            self._geometry_key = geometry_key
        self.poll_messages()
        if self.pending is not None and s.echo_serial_number >= self.pending and s.interp_state == self.api.INTERP_IDLE:
            self.pending = None
        if (self.pending is not None and s.echo_serial_number < self.pending
                and time.monotonic() - self.pending_since > 10):
            self.blocked = True
            self.message = 'Command completion uncertain. Inspect LinuxCNC; use Abort before further commands.'
        manual_pending = self.pending is not None or self.blocked
        self.programs.update(s,manual_pending)
        program = self.programs.describe(s,manual_pending)
        program_pending = bool(self.programs.phase or self.programs.control_serial is not None or
                               (self.programs.running and s.echo_serial_number < self.programs.run_serial))
        names = {self.api.MODE_MANUAL: 'Manual', self.api.MODE_AUTO: 'Auto', self.api.MODE_MDI: 'MDI'}
        return {'connected': True, 'machine': machine, 'work': work,
                'wcs': getattr(s, 'g5x_index', 1),
                'switches': switches,
                'homed': list(s.homed)[:4],
                'homing': [bool(j.get('homing', False)) for j in s.joint[:4]],
                'enabled': bool(s.enabled) and not any(self.halted_axes),
                'estop': bool(s.estop) or any(self.halted_axes),
                'idle': s.interp_state == self.api.INTERP_IDLE,
                'paused': bool(s.paused), 'mode': names.get(s.task_mode, 'Unknown'),
                'pending': manual_pending or program_pending, 'program':program,
                'file': s.file, 'line': s.motion_line, 'message': self.message,
                'execution_line': getattr(s, 'motion_id', 0) or s.motion_line,
                'linuxcnc_messages': list(getattr(self, 'linuxcnc_messages', ())),
                'geometry': self.geometry, 'geometry_error': self.geometry_error,
                'units': 'mm' if abs(s.linear_units - 1) < 1e-6 else 'machine units'}

    def poll_messages(self):
        # Bound each poll so a busy channel cannot stall the UI.
        for _ in range(100):
            event = self.errors.poll()
            if event is None:
                break
            kind, text = event
            is_error = kind in (self.api.NML_ERROR, self.api.OPERATOR_ERROR)
            display = kind in (self.api.NML_DISPLAY, self.api.OPERATOR_DISPLAY)
            severity = 'ERROR' if is_error else 'DISPLAY' if display else 'INFO'
            self.message_serial += 1
            self.linuxcnc_messages.append((self.message_serial, datetime.now().strftime('%H:%M:%S'),
                                          severity, str(text)))
            if is_error:
                self.programs.cancel('LinuxCNC reported an error during preparation: ' + str(text))

    def preview_context(self, text):
        from .preview import prepare_context
        data = self.snapshot()
        if any(getattr(self, 'halted_axes', ())):
            raise ValueError('Positive limit latched; release limits, then Reset E-stop')
        if (not data['idle'] or data['paused'] or data['pending'] or any(data['homing'])):
            raise ValueError('Preview requires an idle machine without homing or pending commands')
        return prepare_context(self.status, text)

    def preview_matches(self, context):
        from .preview import matches
        data = self.snapshot()
        return (not any(getattr(self, 'halted_axes', ())) and data['idle'] and not data['paused'] and not data['pending']
                and not any(data['homing']) and matches(context['baseline'], self.status))

    def register_preview(self, context, data):
        if not self.preview_matches(context):
            raise ValueError('Machine state changed; preview again')
        self.programs.save(context,self.status)

    def clear_preview(self):
        self.programs.clear()

    def cancel_program_start(self):
        self.programs.cancel()

    def execute(self, action, axis=None, text=None):
        # Safety requests bypass a failed status poll or a pending command.
        programs = getattr(self,'programs',None)
        if programs and action not in ('run','pause','resume'):
            programs.cancel()
        if action in ('estop', 'off', 'abort'):
            if programs:
                programs.running = None
                programs.control_serial = None
            if action == 'abort':
                self.command.abort()
            else:
                self.command.state(self.api.STATE_ESTOP if action == 'estop' else self.api.STATE_OFF)
            self.blocked = False
            self.pending = None
            self.message = ''
            return
        data = self.snapshot()
        if any(getattr(self, 'halted_axes', ())):
            if action != 'reset':
                raise ValueError('Positive limit latched; release limits, then Reset E-stop')
            if not all(value is False for value in data['switches']['pos_limit']):
                raise ValueError('Cannot reset: positive limits must be released and readable')
        if action in ('run','pause','resume'):
            if action == 'run':
                self.programs.start(self.status,self.pending is not None or self.blocked)
            else:
                self.programs.control(action,self.status,self.pending is not None or self.blocked)
            return
        if not permissions(data).get(action, False):
            raise ValueError('Command unavailable in the current machine state')
        if action == 'reset':
            self.command.state(self.api.STATE_ESTOP_RESET)
            self.halted_axes = [False]*4
            self._limit_estop_sent = False
            self.message = ''
        elif action == 'on':
            self.command.state(self.api.STATE_ON)
        elif action in ('manual', 'mdi_mode'):
            self.command.mode(self.api.MODE_MANUAL if action == 'manual' else self.api.MODE_MDI)
        elif action == 'home':
            joint = -1 if axis is None else JOINTS[axis]
            if axis is None:
                ini = self.api.ini(self.status.ini_filename)
                if not any(ini.find(f'JOINT_{index}', 'HOME_SEQUENCE') is not None
                           for index in JOINTS.values()):
                    self.message = ('Have you defined HOME_SEQUENCE in the machine INI file? '
                                    'Home All requires HOME_SEQUENCE in the [JOINT_n] sections.')
                    raise ValueError(self.message)
            # Explicit joint mode, with confirmed completion, before homing.
            self.command.teleop_enable(False)
            if self.command.wait_complete(1) != self.api.RCS_DONE:
                raise RuntimeError('Could not confirm joint mode; homing was not submitted')
            self.command.home(joint)
        elif action in ('touch_off', 'work_g54'):
            if action == 'touch_off' and data['wcs'] != 1:
                raise ValueError('Select G54 before Touch Off')
            self.command.mode(self.api.MODE_MDI)
            if self.command.wait_complete(1) != self.api.RCS_DONE:
                self.pending = self.command.serial
                self.pending_since = time.monotonic()
                self.blocked = True
                raise RuntimeError('Could not confirm MDI mode; use Abort before retrying')
            self.command.mdi('G10 L20 P1 X0 Y0 U0 V0' if action == 'touch_off' else 'G54')
            self.clear_preview()
        elif action == 'mdi':
            self.command.mdi(validate_mdi(text))
        else:
            raise ValueError('Unknown command')
        self.pending = self.command.serial
        self.pending_since = time.monotonic()


class DemoBackend:
    """Never imports LinuxCNC; all controls affect this object only."""
    def __init__(self):
        from .geometry import demo_geometry
        self.work_offset = dict.fromkeys('XYUV', 0.)
        self.program_context = None
        self.program_used = False
        self.program_running = False
        self.data = {'connected': True, 'machine': {'X': 125., 'Y': 90., 'U': 210., 'V': 65.},
                     'geometry': demo_geometry(),
                     'work': {'X': 125., 'Y': 90., 'U': 210., 'V': 65.},
                     'homed': [True]*4, 'homing': [False]*4, 'enabled': False,
                     'estop': True, 'idle': True, 'paused': False, 'mode': 'Manual',
                     'wcs': 1, 'pending': False, 'file': '', 'line': 0, 'units': 'mm',
                     'message': 'DEMO — no connection to machinery'}

    def snapshot(self):
        self.data['program'] = self.program_description()
        self.data['program_text'] = (self.program_context['text']
                                     if self.program_context and self.data['file'] else None)
        return self.data

    def register_preview(self, context, data):
        import copy
        if not context.get('demo') or not self.preview_matches(context):
            raise ValueError('Expected a matching demo preview')
        self.program_context = copy.deepcopy(context)
        self.program_used = False

    def clear_preview(self):
        self.program_context = None

    def cancel_program_start(self):
        pass

    def program_description(self):
        d = self.data
        ready = (d['enabled'] and not d['estop'] and all(d['homed']) and not any(d['homing']))
        valid = False
        if ready and d['idle'] and not d['paused'] and self.program_context and not self.program_used:
            valid = self.preview_matches(self.program_context)
        return {'run':bool(valid), 'pause':bool(ready and self.program_running and not d['paused']),
                'resume':bool(ready and self.program_running and d['paused']), 'preparing':False,
                'source_line':0, 'message': 'DEMO: program controls only; no motion or M codes.' if self.program_running else
                'DEMO: ready. Run changes controls only.' if valid else
                'DEMO: preview again after a run; enable and home before starting.'}

    def preview_context(self, text):
        from types import SimpleNamespace
        from .preview import prepare_context
        from .model import AXES
        if not self.data['idle'] or self.data['paused'] or any(self.data['homing']):
            raise ValueError('Demo machine must be idle for preview')
        position = [0.] * 9
        for axis, index in AXES.items():
            position[index] = self.data['machine'][axis]
        offset = [0.] * 9
        for axis, index in AXES.items():
            offset[index] = self.work_offset[axis]
        status = SimpleNamespace(actual_position=position, g5x_offset=offset,
                                 g92_offset=[0.]*9, tool_offset=[0.]*9,
                                 rotation_xy=0., g5x_index=self.data['wcs'], linear_units=1.)
        context = prepare_context(status, text)
        context['demo'] = True
        return context

    def preview_matches(self, context):
        from .preview import matches
        from types import SimpleNamespace
        current = self.preview_context('M2')
        b = current['baseline']
        status = SimpleNamespace(actual_position=b['position'], g5x_offset=b['g5x'],
                                 g92_offset=b['g92'], tool_offset=b['tool'], rotation_xy=b['rotation'],
                                 g5x_index=b['wcs'], linear_units=b['units'])
        return matches(context['baseline'], status)

    def execute(self, action, axis=None, text=None):
        if action in ('run','pause','resume'):
            if not self.program_description()[action]:
                raise ValueError('Program command unavailable in demo state')
            if action == 'run':
                self.program_used = self.program_running = True
                self.data.update(idle=False, paused=False, mode='Auto', file='DEMO / previewed program')
            else:
                self.data['paused'] = action == 'pause'
            return
        if not permissions(self.data).get(action, False):
            raise ValueError('Command unavailable in demo machine state')
        if action in ('estop','off','abort'):
            self.program_running = False
            self.data.update(idle=True,paused=False)
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
                    self.data['machine'][name] = 0.
                    self.data['work'][name] = -self.work_offset[name]
        elif action in ('touch_off', 'work_g54'):
            if action == 'touch_off':
                if self.data['wcs'] != 1:
                    raise ValueError('Select G54 before Touch Off')
                self.work_offset = self.data['machine'].copy()
                self.data['work'] = dict.fromkeys('XYUV', 0.)
            self.data.update(wcs=1, mode='MDI')
            self.clear_preview()
        elif action == 'mdi':
            self.data['message'] = 'DEMO: accepted ' + validate_mdi(text)

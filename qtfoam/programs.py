"""Preview-bound AUTO sequence. Advance only on fresh LinuxCNC status samples."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from .preview import matches


class ProgramRunner:
    def __init__(self, api, command, directory=None):
        self.api, self.command = api, command
        self.directory = Path(directory) if directory else Path.home()/'.local/share/qtfoam/programs'
        self.records = []
        self.record = self.running = None
        self.phase = None
        self.serial = None
        self.deadline = 0
        self.run_serial = None
        self.control_serial = None
        self.message = 'Preview a file first.'

    def cancel(self, message='Program preparation cancelled'):
        if self.phase:
            self.message = message
        self.phase = None

    def clear(self):
        self.cancel()
        self.record = None
        if not self.running:
            self.message = 'Preview a file first.'

    def save(self, context, status):
        self.cancel()
        if context.get('demo'):
            raise ValueError('A demo preview cannot authorize a real program run')
        if not matches(context['baseline'],status):
            raise ValueError('Starting position or offsets changed; preview again')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        for record in list(self.records):
            if str(record['path']) != status.file and record is not self.running:
                record['path'].unlink(missing_ok=True)
                self.records.remove(record)
        path = self.directory/(uuid.uuid4().hex + '.ngc')
        text = context['text']
        with path.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(text)
        path.chmod(0o600)
        self.record = {'path':path, 'digest':hashlib.sha256(text.encode('utf-8')).hexdigest(),
                       'baseline':json.loads(json.dumps(context['baseline'],allow_nan=False)), 'used':False}
        self.records.append(self.record)
        self.message = 'Preview ready. Run executes the program and its M codes on the machine.'

    def ready(self, s, pending=False, paused=False):
        if s.estop or not s.enabled:
            raise ValueError('Reset E-stop and enable the machine')
        if not all(s.homed[:4]) or len(s.homed) < 4:
            raise ValueError('Home all four joints before running')
        if pending or any(j.get('homing',False) for j in s.joint[:4]):
            raise ValueError('Wait for manual commands or homing to finish')
        if not paused and (abs(getattr(s,'current_vel',0.)) > 1e-9 or not getattr(s,'inpos',True)):
            raise ValueError('Wait for motion to stop before starting')
        if not paused and (s.interp_state != self.api.INTERP_IDLE or s.paused):
            raise ValueError('The interpreter must be idle')

    def verify(self, record, s):
        if record is None:
            raise ValueError('Preview a file first')
        if record['used']:
            raise ValueError('Preview again before another run')
        if not matches(record['baseline'],s):
            raise ValueError('Starting position or offsets changed; preview again')
        if hashlib.sha256(record['path'].read_bytes()).hexdigest() != record['digest']:
            raise ValueError('Prepared program changed; preview again')

    def start(self, s, pending=False):
        if self.phase or self.running:
            raise ValueError('A program is already preparing or running')
        self.ready(s,pending)
        self.verify(self.record,s)
        if self.api.ini(s.ini_filename).find('RS274NGC','REMAP'):
            raise ValueError('Machine-specific REMAP is not supported by preview/run')
        self.phase = 'mode'
        self.deadline = time.monotonic()+5
        self.message = 'Selecting AUTO mode...'
        try:
            self.command.mode(self.api.MODE_AUTO)
            self.serial = self.command.serial
        except Exception:
            self.cancel('AUTO mode request failed; inspect machine status')
            raise

    def update(self, s, pending=False):
        if self.control_serial is not None and s.echo_serial_number >= self.control_serial:
            self.control_serial = None
        if self.running:
            if (s.estop or not s.enabled or s.task_mode != self.api.MODE_AUTO
                    or s.file != str(self.running['path'])):
                self.running = None
                self.control_serial = None
            elif s.echo_serial_number >= self.run_serial and s.interp_state == self.api.INTERP_IDLE and not s.paused:
                self.running = None
                self.control_serial = None
                self.message = 'Program finished. Preview again before another run.'
        if not self.phase:
            return
        try:
            self.ready(s,pending)
            self.verify(self.record,s)
            if time.monotonic() > self.deadline:
                raise ValueError('Program preparation timed out; no automatic retry')
            if s.echo_serial_number < self.serial:
                return
            if s.task_mode != self.api.MODE_AUTO:
                raise ValueError('AUTO mode was not confirmed; start cancelled')
            if self.phase == 'mode':
                self.phase = 'open'
                self.deadline = time.monotonic()+5
                self.message = 'Opening the exact previewed copy...'
                self.command.program_open(str(self.record['path']))
                self.serial = self.command.serial
            else:
                if s.file != str(self.record['path']):
                    raise ValueError('Previewed program was not loaded; start cancelled')
                # Consume before issuing AUTO_RUN. Never retry an uncertain start.
                self.record['used'] = True
                self.running = self.record
                self.phase = None
                self.message = 'Run submitted. Check machine status.'
                try:
                    self.command.auto(self.api.AUTO_RUN,0)
                finally:
                    self.run_serial = self.command.serial
        except Exception as exc:
            self.cancel()
            self.message = str(exc)

    def control(self, action, s, pending=False):
        self.ready(s,pending,paused=True)
        if (not self.running or s.task_mode != self.api.MODE_AUTO
                or s.file != str(self.running['path'])):
            raise ValueError('This QtFoam program is not running')
        if self.control_serial is not None:
            raise ValueError('Wait for the preceding program command acknowledgement')
        if action == 'resume':
            if not s.paused:
                raise ValueError('Program is not paused')
            if hashlib.sha256(self.running['path'].read_bytes()).hexdigest() != self.running['digest']:
                raise ValueError('Prepared file changed; abort and preview again')
        elif s.paused or s.interp_state == self.api.INTERP_IDLE:
            raise ValueError('Program is not executing')
        self.command.auto(self.api.AUTO_RESUME if action == 'resume' else self.api.AUTO_PAUSE)
        self.control_serial = self.command.serial

    def describe(self, s, pending=False):
        result = {'run':False,'pause':False,'resume':False,'preparing':bool(self.phase),
                  'message':self.message,'source_line':0}
        if self.running:
            try:
                self.ready(s,pending,paused=True)
                owned = s.task_mode == self.api.MODE_AUTO and s.file == str(self.running['path'])
                result['pause'] = owned and not s.paused and s.interp_state != self.api.INTERP_IDLE and self.control_serial is None
                result['resume'] = owned and s.paused and self.control_serial is None
                result['message'] = 'Paused / M0: press Resume.' if s.paused else 'Program running in LinuxCNC.'
                result['source_line'] = max(0,s.motion_line-1) if owned else 0
            except ValueError as exc:
                result['message'] = str(exc)
        elif not self.phase:
            try:
                self.ready(s,pending)
                self.verify(self.record,s)
                result['run'] = True
            except (ValueError,OSError) as exc:
                result['message'] = str(exc)
        return result

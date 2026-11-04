"""Shared native screen, hosted by QtVCP or the disconnected demo."""
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from .model import AXES, permissions, validate_mdi, expand_mdi_shortcut
from .wire import WireView
from .preview import read_source
from .preview_job import PreviewJob
from .dro import DROView


def label(text, name=None):
    widget = QtWidgets.QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def card():
    frame = QtWidgets.QFrame()
    frame.setObjectName('card')
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    return frame, layout


class Screen(QtWidgets.QWidget):
    def __init__(self, backend, demo=False):
        super().__init__()
        self.backend, self.demo = backend, demo
        self.buttons = {}
        self.data = None
        self.history = []
        self.settings = QtCore.QSettings('QtFoam', 'Demo' if demo else 'QtFoam')
        self.macros = []
        for index in range(4):
            name = str(self.settings.value(f'macros/{index}/name', f'Macro {index+1}'))
            command = str(self.settings.value(f'macros/{index}/command', ''))
            try:
                command = validate_mdi(command) if command else ''
            except ValueError:
                command = ''
            self.macros.append((name[:24] or f'Macro {index+1}', command))
        self.closing = False
        self.preview_context = None
        self.preview_source = []
        self.preview_job = PreviewJob(self)
        self.preview_job.succeeded.connect(self.preview_finished)
        self.preview_job.failed.connect(self.preview_failed)
        self.preview_job.busy_changed.connect(self.preview_busy_changed)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(12)
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(label('QTFOAM  /  XY · UV', 'brand'))
        heading.addStretch()
        self.badge = label('DEMO · no machinery' if demo else 'Connecting to LinuxCNC', 'badge')
        heading.addWidget(self.badge)
        outer.addLayout(heading)
        safety = QtWidgets.QHBoxLayout()
        for action, title in [('estop','E-STOP'),('reset','Reset E-stop'),('on','Machine On'),
                              ('off','Machine Off'),('abort','Abort')]:
            safety.addWidget(self.button(title, action, danger=action == 'estop'))
        outer.addLayout(safety)
        self.message = label('DEMO — hardware disconnected' if demo else 'Waiting for status', 'muted')
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(25)
        outer.addWidget(self.message)
        outer.addWidget(self.io_panel())
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.status_page(), 'Machine Status')
        self.tabs.addTab(self.toolpath_page(), 'Toolpath')
        self.tabs.addTab(self.mdi_page(), 'MDI')
        self.dro_view = DROView()
        self.tabs.addTab(self.dro_view, 'DRO')
        outer.addWidget(self.tabs, 1)
        outer.addWidget(label('LINUXCNC MESSAGES', 'muted'))
        self.linuxcnc_messages = QtWidgets.QPlainTextEdit()
        self.linuxcnc_messages.setReadOnly(True)
        self.linuxcnc_messages.setMaximumBlockCount(300)
        self.linuxcnc_messages.setFixedHeight(78)
        self.linuxcnc_messages.setPlaceholderText('DEMO — no LinuxCNC message channel' if demo else 'No LinuxCNC messages')
        self.last_linuxcnc_message = 0
        outer.addWidget(self.linuxcnc_messages)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(200)
        self.refresh()

    def io_panel(self):
        panel = QtWidgets.QFrame()
        panel.setObjectName('card')
        grid = QtWidgets.QGridLayout(panel)
        grid.setContentsMargins(12, 6, 12, 6)
        grid.setVerticalSpacing(3)
        self.io_leds = {}
        grid.addWidget(label('STATUS I/O', 'muted'), 0, 0)
        for column, (key, title, source) in enumerate((
                ('heater', 'Heater', 'flood (M8/M9)'),
                ('amp', 'Amp enable', 'joint[0].enabled')), 1):
            led = label('')
            grid.addWidget(led, 0, 1 if column == 1 else 5, 1, 4)
            self.io_leds[key] = (led, title, source)
        for row, key in enumerate(('din', 'dout'), 1):
            grid.addWidget(label('IN' if key == 'din' else 'OUT', 'muted'), row, 0)
            for index in range(16):
                led = label('')
                led.setAlignment(QtCore.Qt.AlignCenter)
                grid.addWidget(led, row, index + 1)
                self.io_leds[(key, index)] = (led, str(index), f'{key}[{index}]')
        panel.setToolTip('LinuxCNC status values, as in linuxcnctop. '
                         'IN/OUT numbers are NML channels, not INI OUTPUT_n mappings. '
                         'Green = 1, dark = 0, ? = unavailable. No hardware inversion applied.')
        return panel

    def update_io(self):
        values = self.data.get('io', {}) if self.data else {}
        for key, (led, title, source) in self.io_leds.items():
            if isinstance(key, tuple):
                group, index = key
                channels = values.get(group, ())
                value = channels[index] if index < len(channels) else None
            else:
                value = values.get(key)
            state = 'unknown' if value is None else 'on' if value else 'off'
            led.setObjectName('io_' + state)
            led.setText(('? ' if value is None else '● ' if value else '○ ') + title)
            led.setToolTip(source + ': ' + ('unavailable' if value is None else str(int(bool(value)))))
            led.style().unpolish(led)
            led.style().polish(led)

    def button(self, title, action, axis=None, danger=False):
        button = QtWidgets.QPushButton(title)
        button.setAutoRepeat(False)
        if danger:
            button.setObjectName('danger')
        button.clicked.connect(lambda checked=False: self.send(action, axis))
        self.buttons[(action, axis)] = button
        return button

    def status_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        homing = QtWidgets.QHBoxLayout()
        homing.addWidget(self.button('Select Manual', 'manual'))
        homing.addWidget(self.button('Home All', 'home'))
        for axis in AXES:
            homing.addWidget(self.button('Home ' + axis, 'home', axis))
        layout.addLayout(homing)
        coordinates = QtWidgets.QHBoxLayout()
        self.dro = {}
        for title, axes in [('LEFT SIDE  /  XY', 'XY'), ('RIGHT SIDE  /  UV', 'UV')]:
            frame, body = card()
            body.addWidget(label(title, 'muted'))
            grid = QtWidgets.QGridLayout()
            for column, text in enumerate(('Axis', 'Machine', 'Work', 'Homing')):
                grid.addWidget(label(text, 'muted'), 0, column)
            for row, axis in enumerate(axes, 1):
                grid.addWidget(label(axis, 'brand'), row, 0)
                for column, key in enumerate(('machine','work','homed'), 1):
                    value = label('—', 'value' if key != 'homed' else 'muted')
                    grid.addWidget(value, row, column)
                    self.dro[(axis,key)] = value
            body.addLayout(grid)
            coordinates.addWidget(frame)
        layout.addLayout(coordinates)
        facts = QtWidgets.QHBoxLayout()
        self.facts = {}
        for key, title in [('estop','E-STOP'),('power','MACHINE POWER'),('mode','TASK MODE'),('program','PROGRAM STATE')]:
            frame, body = card()
            body.addWidget(label(title, 'muted'))
            value = label('—', 'value')
            body.addWidget(value)
            self.facts[key] = value
            facts.addWidget(frame)
        layout.addLayout(facts)
        frame, body = card()
        body.addWidget(label('PROGRAM FILE / EXECUTING LINE', 'muted'))
        self.file = label('No program loaded')
        self.file.setWordWrap(True)
        body.addWidget(self.file)
        layout.addWidget(frame)
        self.units = label('Coordinates use the configured machine units.', 'muted')
        layout.addWidget(self.units)
        layout.addStretch()
        return page

    def toolpath_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(label('XYUV TOOLPATH / wire and swept surface', 'muted'))
        header.addStretch()
        reset = QtWidgets.QPushButton('Reset View')
        header.addWidget(reset)
        layout.addLayout(header)
        middle = QtWidgets.QHBoxLayout()
        sidebar, body = card()
        sidebar.setMaximumWidth(310)
        sidebar.setMinimumWidth(245)
        body.addWidget(label('G-CODE PREVIEW', 'muted'))
        self.preview_load = QtWidgets.QPushButton('Load and Preview')
        self.preview_load.clicked.connect(self.choose_preview)
        body.addWidget(self.preview_load)
        self.preview_clear = QtWidgets.QPushButton('Cancel / Clear')
        self.preview_clear.clicked.connect(self.clear_preview)
        body.addWidget(self.preview_clear)
        self.preview_file = label('No file selected', 'muted')
        self.preview_file.setWordWrap(True)
        self.preview_file.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        body.addWidget(self.preview_file)
        self.preview_message = label('Select a UTF-8 .nc or .ngc file. Preview never starts the machine.', 'muted')
        self.preview_message.setWordWrap(True)
        body.addWidget(self.preview_message)
        body.addStretch()
        middle.addWidget(sidebar)
        self.wire = WireView()
        reset.clicked.connect(self.wire.reset)
        middle.addWidget(self.wire, 1)
        layout.addLayout(middle,1)
        frame, body = card()
        body.setSpacing(6)
        body.setContentsMargins(18,10,18,10)
        program_row = QtWidgets.QHBoxLayout()
        for title,action in (('Run Program','run'),('Pause','pause'),('Resume','resume'),('Abort Run','abort_run')):
            program_row.addWidget(self.button(title,action))
        body.addLayout(program_row)
        self.program_message = label('Preview a file first.', 'muted')
        self.program_message.setWordWrap(True)
        body.addWidget(self.program_message)
        self.preview_line = label('Preview position / no preview', 'muted')
        body.addWidget(self.preview_line)
        self.preview_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.preview_slider.setRange(0,0)
        self.preview_slider.setEnabled(False)
        self.preview_slider.valueChanged.connect(self.select_preview_step)
        body.addWidget(self.preview_slider)
        self.preview_code = QtWidgets.QPlainTextEdit()
        self.preview_code.setReadOnly(True)
        self.preview_code.setMaximumHeight(48)
        self.preview_code.setPlaceholderText('Selected source line')
        body.addWidget(self.preview_code)
        layout.addWidget(frame)
        legend = label('Drag to rotate | XY blue / UV purple | G0 dashed orange | Preview wire gold / live wire white', 'muted')
        legend.setWordWrap(True)
        layout.addWidget(legend)
        return page

    def choose_preview(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Preview G-code', '',
                            'G-code (*.nc *.ngc *.tap *.gcode);;All files (*)')
        if filename:
            self.start_preview(filename)

    def start_preview(self, filename):
        if self.preview_job.busy:
            return
        self.clear_preview()
        try:
            source = read_source(filename)
            context = self.backend.preview_context(source)
            self.preview_context = context
            self.preview_source = source.splitlines()
            self.preview_file.setText(Path(filename).name)
            self.preview_file.setToolTip(str(filename))
            self.preview_message.setText('Interpreting in a separate process...')
            self.preview_job.start(context)
        except Exception as exc:
            self.preview_failed(str(exc))

    def preview_busy_changed(self, busy):
        self.preview_load.setEnabled(not busy)
        if hasattr(self, 'timer') and not self.closing:
            self.refresh()

    def preview_finished(self, data):
        if self.closing:
            return
        try:
            if self.preview_context is None or not self.backend.preview_matches(self.preview_context):
                raise ValueError('Machine position, offsets or state changed during preview. Preview again while idle.')
            self.backend.register_preview(self.preview_context,data)
            self.wire.set_preview(data)
            self.preview_slider.setRange(0,len(data['segments']))
            self.preview_slider.setValue(0)
            self.preview_slider.setEnabled(True)
            self.select_preview_step(0)
            prefix = 'DEMO geometry only. ' if self.demo else ''
            self.preview_message.setText(prefix + str(len(data['segments'])) +
                                         ' segments. Preview generated without motion. G0/G1 only; no heater or travel-limit validation.')
            self.preview_message.setToolTip(data.get('warning',''))
            self.refresh()
        except Exception as exc:
            self.preview_failed(str(exc))

    def preview_failed(self, message):
        if self.closing:
            return
        self.backend.clear_preview()
        self.wire.set_preview(None)
        self.preview_slider.setEnabled(False)
        self.preview_slider.setRange(0,0)
        self.preview_line.setText('Preview unavailable')
        self.preview_code.clear()
        self.preview_message.setText(str(message))

    def clear_preview(self):
        self.preview_job.cancel()
        self.preview_context = None
        self.preview_source = []
        self.backend.clear_preview()
        self.wire.set_preview(None)
        self.preview_slider.setEnabled(False)
        self.preview_slider.setRange(0,0)
        self.preview_file.setText('No file selected')
        self.preview_line.setText('Preview position / no preview')
        self.preview_code.clear()
        self.preview_message.setText('Select a UTF-8 .nc or .ngc file. Preview never starts the machine.')

    def select_preview_step(self, step):
        data = self.wire.preview
        if not data:
            return
        self.wire.set_preview_step(step)
        if step == 0:
            self.preview_line.setText('Starting wire / captured machine position')
            self.preview_code.clear()
        else:
            segment = data['segments'][step-1]
            line = segment['line']
            self.preview_line.setText('Move %s / %s | Source line %s | %s' %
                (step,len(data['segments']),line,'G0 rapid' if segment['kind']=='rapid' else 'G1 feed'))
            self.preview_code.setPlainText(self.preview_source[line-1] if line <= len(self.preview_source) else '')

    def cleanup(self):
        self.closing = True
        self.timer.stop()
        self.backend.cancel_program_start()
        self.preview_job.shutdown()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def mdi_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        frame, body = card()
        body.setSpacing(8)
        body.setContentsMargins(16,12,16,12)
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(label('MANUAL G-CODE INPUT', 'muted'))
        heading.addStretch()
        heading.addWidget(self.button('Select MDI', 'mdi_mode'))
        body.addLayout(heading)
        heater = QtWidgets.QHBoxLayout()
        self.heater_buttons = []
        for title, command in [('Heater On · M8', 'M8'), ('Heater Off · M9', 'M9')]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False, command=command: self.send('mdi', text_override=command))
            heater.addWidget(button)
            self.heater_buttons.append(button)
        body.addLayout(heater)
        self.mdi = QtWidgets.QLineEdit()
        self.mdi.setMaxLength(254)
        self.mdi.setPlaceholderText('G-code or X/U target, e.g. 400XU')
        shortcut_hint = ('X/U shortcut: 400XU → G21 G90 G0 X400 U400. '
                         'First Enter expands; second Enter sends. '
                         'Rapid move to 400 mm from the active work zero, not an incremental move. '
                         'Decimals and negative targets are supported, e.g. 125.5XU or -10XU.')
        self.mdi.setToolTip(shortcut_hint)
        self.mdi.returnPressed.connect(lambda: self.send('mdi'))
        body.addWidget(self.mdi)
        hint = label('400XU → X/U 400 mm · Enter to expand, Enter again to send', 'muted')
        hint.setWordWrap(True)
        hint.setToolTip(shortcut_hint)
        body.addWidget(hint)
        keyboard = QtWidgets.QHBoxLayout()
        self.mdi_keys = []
        self.mdi_number_grid = QtWidgets.QGridLayout()
        letters = QtWidgets.QGridLayout()
        for grid, rows in ((letters,('GM','XY','UV','FS')),
                           (self.mdi_number_grid,('789','456','123','-0.'))):
            for row, keys in enumerate(rows):
                for column, key in enumerate(keys):
                    button = QtWidgets.QPushButton(key)
                    button.setFocusPolicy(QtCore.Qt.NoFocus)
                    button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    button.clicked.connect(lambda checked=False, key=key: self.mdi.insert(key))
                    grid.addWidget(button,row,column)
                    self.mdi_keys.append(button)
        keyboard.addLayout(letters,2)
        keyboard.addSpacing(12)
        keyboard.addLayout(self.mdi_number_grid,3)
        body.addLayout(keyboard)
        body.addSpacing(6)
        edit = QtWidgets.QHBoxLayout()
        for title, callback in [('Space', lambda: self.mdi.insert(' ')),('Delete', self.mdi.backspace),('Clear', self.mdi.clear)]:
            button = QtWidgets.QPushButton(title)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.clicked.connect(callback)
            self.mdi_keys.append(button)
            edit.addWidget(button)
        edit.addWidget(self.button('Enter · Send', 'mdi'))
        body.addLayout(edit)
        self.mdi_help = label('Enable and home all joints, then select MDI mode.', 'muted')
        self.mdi_help.setWordWrap(True)
        body.addWidget(self.mdi_help)
        body.addStretch()
        layout.addWidget(frame, 2)
        frame, body = card()
        macro_heading = QtWidgets.QHBoxLayout()
        macro_heading.addWidget(label('MDI MACROS', 'muted'))
        edit_macros = QtWidgets.QPushButton('Edit macros')
        edit_macros.clicked.connect(self.edit_macros)
        macro_heading.addWidget(edit_macros)
        body.addLayout(macro_heading)
        macro_grid = QtWidgets.QGridLayout()
        self.macro_buttons = []
        for index in range(4):
            button = QtWidgets.QPushButton()
            button.clicked.connect(lambda checked=False, index=index: self.load_macro(index))
            macro_grid.addWidget(button, index // 2, index % 2)
            self.macro_buttons.append(button)
        self.update_macro_buttons()
        body.addLayout(macro_grid)
        body.addWidget(label('SESSION SUBMISSIONS', 'muted'))
        self.history_view = QtWidgets.QListWidget()
        self.history_view.itemDoubleClicked.connect(self.recall_mdi)
        self.history_view.setToolTip('Double-click a command to edit it, then press Enter to send.')
        body.addWidget(self.history_view)
        body.addWidget(label('Submission is not motion completion.', 'muted'))
        layout.addWidget(frame, 1)
        return page

    def recall_mdi(self, item):
        self.mdi.setText(item.text())
        self.mdi.setFocus(QtCore.Qt.MouseFocusReason)

    def update_macro_buttons(self):
        for button, (name, command) in zip(self.macro_buttons, self.macros):
            button.setText(name)
            button.setToolTip(command + '\nLoad into input; press Enter to send.' if command else 'Configure with Edit macros.')
            button.setEnabled(bool(command))

    def load_macro(self, index):
        self.mdi.setText(self.macros[index][1])
        self.mdi.setFocus(QtCore.Qt.MouseFocusReason)

    def edit_macros(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Edit MDI macros')
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(label('Each macro loads one G-code line into the input. Enter sends it.'))
        grid = QtWidgets.QGridLayout()
        grid.addWidget(label('Button name'), 0, 0)
        grid.addWidget(label('G-code line'), 0, 1)
        fields = []
        for row, (name, command) in enumerate(self.macros, 1):
            name_input = QtWidgets.QLineEdit(name)
            name_input.setMaxLength(24)
            command_input = QtWidgets.QLineEdit(command)
            command_input.setMaxLength(254)
            command_input.setMinimumWidth(320)
            grid.addWidget(name_input, row, 0)
            grid.addWidget(command_input, row, 1)
            fields.append((name_input, command_input))
        layout.addLayout(grid)
        error = label('', 'muted')
        layout.addWidget(error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        def save():
            macros = []
            try:
                for index, (name_input, command_input) in enumerate(fields):
                    command = command_input.text()
                    macros.append((name_input.text().strip() or f'Macro {index+1}',
                                   validate_mdi(command) if command.strip() else ''))
            except ValueError as exc:
                error.setText(str(exc))
                return
            for index, (name, command) in enumerate(macros):
                self.settings.setValue(f'macros/{index}/name', name)
                self.settings.setValue(f'macros/{index}/command', command)
            self.settings.sync()
            if self.settings.status() != QtCore.QSettings.NoError:
                error.setText('Could not save macro settings.')
                return
            self.macros = macros
            self.update_macro_buttons()
            dialog.accept()
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()

    def send(self, action, axis=None, text_override=None):
        if action == 'abort_run':
            action = 'abort'
        try:
            if self.preview_job.busy:
                if action not in ('estop','off','abort'):
                    raise ValueError('Wait for preview interpretation or cancel it first')
                self.preview_job.cancel('Preview cancelled by machine control')
            text = (self.mdi.text() if text_override is None else text_override) if action == 'mdi' else None
            if action == 'mdi' and text_override is None:
                expanded = expand_mdi_shortcut(text)
                if expanded is not None:
                    self.mdi.setText(expanded)
                    self.mdi.setFocus(QtCore.Qt.OtherFocusReason)
                    self.message.setText('X/U rapid target expanded. Review the G-code and press Enter to send.')
                    return
            self.backend.execute(action, axis=axis, text=text)
            self.message.setText(('DEMO · ' if self.demo else '') + 'Submitted: ' + action + (' ' + axis if axis else ''))
            if action == 'mdi':
                self.history.insert(0, text)
                self.history = self.history[:30]
                self.history_view.clear()
                self.history_view.addItems(self.history)
                if text_override is None:
                    self.mdi.clear()
        except Exception as exc:
            self.message.setText(str(exc))
        self.refresh()

    def refresh(self):
        try:
            self.data = self.backend.snapshot()
        except Exception as exc:
            self.data = None
            self.message.setText('Status unavailable: ' + str(exc))
        available = permissions(self.data)
        self.update_io()
        self.dro_view.update_status(self.data)
        program = self.data.get('program',{}) if self.data else {}
        available.update({action: bool(program.get(action)) for action in ('run','pause','resume')})
        available['abort_run'] = available['abort']
        program_text = program.get('message','Program status unavailable')
        if program.get('source_line',0) > 0:
            program_text += ' | Executing source line ' + str(program['source_line'])
        self.program_message.setText(program_text)
        self.preview_load.setEnabled(bool(self.data and self.data['idle'] and not self.data['paused']
                                          and not self.data['pending'] and not self.preview_job.busy))
        if self.preview_job.busy:
            for action in available:
                if action not in ('estop','off','abort','abort_run'):
                    available[action] = False
            if self.data is None or not self.data['idle'] or self.data['paused'] or any(self.data['homing']):
                self.preview_job.cancel('Machine status became unavailable or active during preview')
        for (action, axis), button in self.buttons.items():
            # Safety commands remain callable against existing API channels.
            button.setEnabled(available.get(action, False) or
                              (not self.demo and action in ('estop','off','abort','abort_run')))
        self.mdi.setEnabled(available['mdi'])
        for button in self.heater_buttons:
            button.setEnabled(available['mdi'])
        for button in self.mdi_keys:
            button.setEnabled(available['mdi'])
        data = self.data
        self.wire.set_geometry(data.get('geometry') if data else None,
                               data.get('geometry_error', '') if data else 'Status unavailable')
        for serial, timestamp, severity, text in data.get('linuxcnc_messages', ()) if data else ():
            if serial > self.last_linuxcnc_message:
                self.linuxcnc_messages.appendPlainText(f'{timestamp}  {severity}  {text}')
                self.last_linuxcnc_message = serial
        self.badge.setText('DEMO · no machinery' if self.demo else ('LinuxCNC · local' if data else 'Status unavailable'))
        if not data:
            for value in (*self.dro.values(), *self.facts.values()):
                value.setText('—')
            self.file.setText('Status unavailable')
            self.wire.set_positions(None)
            return
        for axis in AXES:
            for kind in ('machine','work'):
                value = data[kind][axis]
                self.dro[(axis,kind)].setText(f'{0.0 if abs(value) < .0005 else value:.3f}')
            index = list(AXES).index(axis)
            self.dro[(axis,'homed')].setText('Homing' if data['homing'][index] else
                                           'Homed' if data['homed'][index] else 'Not homed')
        self.facts['estop'].setText('Active' if data['estop'] else 'Reset')
        self.facts['power'].setText('On' if data['enabled'] else 'Off')
        self.facts['mode'].setText(data['mode'])
        self.facts['program'].setText('Paused' if data['paused'] else 'Idle' if data['idle'] else 'Running')
        self.file.setText((data['file'] or 'No program loaded') + '  ·  Line ' + str(data['line']))
        self.units.setText('Machine/work coordinates · ' + data['units'])
        self.wire.set_positions(data['machine'] if data['units'] == 'mm' else None)
        self.mdi_help.setText('MDI active · commands operate on the machine.' if available['mdi'] else
                              'Requires enable, all joints homed, idle interpreter and MDI mode.')
        if data.get('message'):
            self.message.setText(data['message'])

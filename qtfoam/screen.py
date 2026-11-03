"""Shared native screen, hosted by QtVCP or the disconnected demo."""
from PyQt5 import QtCore, QtWidgets
from .model import AXES, permissions
from .wire import WireView


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
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.status_page(), 'Machine Status')
        self.tabs.addTab(self.toolpath_page(), 'Toolpath')
        self.tabs.addTab(self.mdi_page(), 'MDI')
        outer.addWidget(self.tabs, 1)
        outer.addWidget(label('XYUV · Native LinuxCNC screen     |     Proof of concept · Software controls', 'muted'))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(200)
        self.refresh()

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
        header.addWidget(label('LIVE WIRE  /  independent XY and UV endpoints', 'muted'))
        header.addStretch()
        reset = QtWidgets.QPushButton('Reset View')
        header.addWidget(reset)
        layout.addLayout(header)
        self.wire = WireView()
        reset.clicked.connect(self.wire.reset)
        layout.addWidget(self.wire, 1)
        layout.addWidget(label('Drag to rotate · White wire = actual machine position', 'muted'))
        frame, body = card()
        body.addWidget(label('G-CODE PREVIEW AND EXECUTION', 'muted'))
        info = label('Next development stage: interpreted XYUV preview, source-line inspection and verified program start.\n'
                     'This first version only displays live positions; it cannot load or run program files.')
        info.setWordWrap(True)
        body.addWidget(info)
        layout.addWidget(frame)
        return page

    def mdi_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        frame, body = card()
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(label('MANUAL G-CODE INPUT', 'muted'))
        heading.addStretch()
        heading.addWidget(self.button('Select MDI', 'mdi_mode'))
        body.addLayout(heading)
        self.mdi = QtWidgets.QLineEdit()
        self.mdi.setMaxLength(254)
        self.mdi.setPlaceholderText('For example, G90')
        self.mdi.returnPressed.connect(lambda: self.send('mdi'))
        body.addWidget(self.mdi)
        grid = QtWidgets.QGridLayout()
        for row, keys in enumerate(('GMFSXYUV', '789456', '1230-.')):
            for column, key in enumerate(keys):
                button = QtWidgets.QPushButton(key)
                button.setFocusPolicy(QtCore.Qt.NoFocus)
                button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
                button.clicked.connect(lambda checked=False, key=key: self.mdi.insert(key))
                grid.addWidget(button, row, column)
        body.addLayout(grid)
        edit = QtWidgets.QHBoxLayout()
        for title, callback in [('Space', lambda: self.mdi.insert(' ')),('Delete', self.mdi.backspace),('Clear', self.mdi.clear)]:
            button = QtWidgets.QPushButton(title)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.clicked.connect(callback)
            edit.addWidget(button)
        edit.addWidget(self.button('Enter · Send', 'mdi'))
        body.addLayout(edit)
        self.mdi_help = label('Enable and home all joints, then select MDI mode.', 'muted')
        self.mdi_help.setWordWrap(True)
        body.addWidget(self.mdi_help)
        body.addStretch()
        layout.addWidget(frame, 2)
        frame, body = card()
        body.addWidget(label('SESSION SUBMISSIONS', 'muted'))
        self.history_view = QtWidgets.QListWidget()
        body.addWidget(self.history_view)
        body.addWidget(label('Submission is not motion completion.', 'muted'))
        layout.addWidget(frame, 1)
        return page

    def send(self, action, axis=None):
        try:
            text = self.mdi.text() if action == 'mdi' else None
            self.backend.execute(action, axis=axis, text=text)
            self.message.setText(('DEMO · ' if self.demo else '') + 'Submitted: ' + action + (' ' + axis if axis else ''))
            if action == 'mdi':
                self.history.insert(0, text)
                self.history = self.history[:30]
                self.history_view.clear()
                self.history_view.addItems(self.history)
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
        for (action, axis), button in self.buttons.items():
            # Safety commands remain callable against existing API channels.
            button.setEnabled(available.get(action, False) or
                              (not self.demo and action in ('estop','off','abort')))
        self.mdi.setEnabled(available['mdi'])
        data = self.data
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

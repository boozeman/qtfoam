"""Read-only coordinates and the program actually loaded in LinuxCNC."""
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
from .preview import MAX_BYTES


class DROView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        coordinates = QtWidgets.QHBoxLayout()
        self.coordinates = {}
        for axis in 'XYUV':
            value = QtWidgets.QLabel(axis + ' —')
            value.setObjectName('value')
            coordinates.addWidget(value)
            self.coordinates[axis] = value
        layout.addLayout(coordinates)
        self.file = QtWidgets.QLabel('No program loaded in LinuxCNC')
        self.file.setWordWrap(True)
        layout.addWidget(self.file)
        row = QtWidgets.QHBoxLayout()
        self.state = QtWidgets.QLabel('Idle')
        row.addWidget(self.state, 1)
        self.follow = QtWidgets.QCheckBox('Follow execution')
        self.follow.setChecked(True)
        self.follow.toggled.connect(self.follow_changed)
        row.addWidget(self.follow)
        layout.addLayout(row)
        self.code = QtWidgets.QPlainTextEdit()
        self.code.setReadOnly(True)
        self.code.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        font.setPointSize(12)
        self.code.setFont(font)
        self.code.setStyleSheet('QPlainTextEdit { font-family: "DejaVu Sans Mono", "Consolas", monospace; font-size: 16px; }')
        self.code.setPlaceholderText('The loaded program will appear here when LinuxCNC opens it.')
        layout.addWidget(self.code, 1)
        self.source_key = None
        self.line_count = 0
        self.active_line = 0
        self.load_error = ''

    def follow_changed(self, enabled):
        if enabled and self.active_line:
            self.scroll_to_line(self.active_line)

    def scroll_to_line(self, line):
        cursor = QtGui.QTextCursor(self.code.document().findBlockByNumber(line-1))
        self.code.setTextCursor(cursor)
        self.code.centerCursor()

    def update_status(self, data):
        self.code.setExtraSelections([])
        previous_line = self.active_line
        self.active_line = 0
        for axis, value in self.coordinates.items():
            value.setText(f"{axis} {data['work'][axis]:.3f}" if data else axis + ' —')
        if not data:
            self.state.setText('Status unavailable — execution tracking stopped')
            return
        path = data.get('file', '')
        demo_text = data.get('program_text')
        key = (path, demo_text)
        try:
            if path and demo_text is None:
                stat = Path(path).stat()
                key = (path, stat.st_mtime_ns, stat.st_size)
            if key != self.source_key:
                self.source_key = key
                self.code.clear()
                self.line_count = 0
                self.load_error = ''
                if path:
                    if demo_text is not None:
                        text = demo_text
                    else:
                        # Prepared copies add a short preamble to the preview size limit.
                        with Path(path).open('rb') as stream:
                            raw = stream.read(MAX_BYTES + 2049)
                        if len(raw) > MAX_BYTES + 2048:
                            raise ValueError('Program display exceeds 258 KiB')
                        text = raw.decode('utf-8-sig')
                    if '\0' in text:
                        raise ValueError('Program contains NUL characters')
                    lines = text.splitlines()
                    self.line_count = len(lines)
                    digits = len(str(self.line_count))
                    self.code.setPlainText('\n'.join(f'{index:>{digits}}  {line}'
                                                    for index, line in enumerate(lines, 1)))
        except (OSError, UnicodeError, ValueError) as exc:
            self.source_key = None
            self.line_count = 0
            self.code.clear()
            self.load_error = 'Cannot display program: ' + str(exc)
        self.file.setText(path or 'No program loaded in LinuxCNC')
        self.file.setToolTip(path)
        active = data.get('mode') == 'Auto' and (not data['idle'] or data['paused'])
        state = 'Paused' if data['paused'] else 'Running' if active else 'Idle'
        self.state.setText(self.load_error or f"{state} · Work coordinates · {data['units']}")
        line = data.get('execution_line', data.get('line', 0)) if active else 0
        if self.load_error or not 1 <= line <= self.line_count:
            return
        self.active_line = line
        selection = QtWidgets.QTextEdit.ExtraSelection()
        selection.cursor = QtGui.QTextCursor(self.code.document().findBlockByNumber(line-1))
        selection.format.setBackground(QtGui.QColor('#346951'))
        selection.format.setForeground(QtGui.QColor('#ffffff'))
        selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        self.code.setExtraSelections([selection])
        self.state.setText(f'{state} · Loaded file line {line} · Work coordinates · {data["units"]}')
        if self.follow.isChecked() and (line != previous_line or key != getattr(self, '_last_follow_key', None)):
            self.scroll_to_line(line)
        self._last_follow_key = key

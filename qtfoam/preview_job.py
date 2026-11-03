"""Event-driven, bounded interpreter process; leaves the Qt event loop responsive."""
import json
from pathlib import Path
import sys
import tempfile
from PyQt5 import QtCore
from .preview import validate_result


class PreviewJob(QtCore.QObject):
    succeeded = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    busy_changed = QtCore.pyqtSignal(bool)
    MAX_OUTPUT = 8 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QtCore.QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        self.process.started.connect(self._started)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timeout = QtCore.QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.cancel('Preview interpreter exceeded 20 seconds'))
        self.busy = False
        self.output = bytearray()
        self.reason = None
        self.workspace = None

    def start(self, context):
        if self.busy:
            raise ValueError('A preview is already being interpreted')
        self.workspace = tempfile.TemporaryDirectory(prefix='qtfoam-preview-')
        context = dict(context, temporary_directory=self.workspace.name)
        try:
            self.payload = json.dumps(context, allow_nan=False).encode('utf-8')
        except Exception:
            self.workspace.cleanup()
            self.workspace = None
            raise
        self.output.clear()
        self.reason = None
        self.busy = True
        self.busy_changed.emit(True)
        self.timeout.start(20000)
        self.process.start(sys.executable, ['-B','-m','qtfoam.preview_worker'])

    def _started(self):
        if self.reason:
            self.process.kill()
            return
        self.process.write(self.payload)
        self.process.closeWriteChannel()

    def _read(self):
        chunk = bytes(self.process.readAllStandardOutput())
        if len(self.output) + len(chunk) > self.MAX_OUTPUT:
            self.cancel('Preview interpreter output exceeds 8 MiB')
        elif not self.reason:
            self.output.extend(chunk)

    def cancel(self, reason='Preview cancelled'):
        if not self.busy:
            return
        self.reason = reason
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill()

    def _error(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self._complete(None, 'Could not start preview interpreter: ' + self.process.errorString())

    def _finished(self, code, exit_status):
        if not self.busy:
            return
        self._read()
        try:
            if self.reason:
                raise ValueError(self.reason)
            if code != 0 or exit_status != QtCore.QProcess.NormalExit:
                raise ValueError('Preview interpreter terminated unexpectedly')
            result = json.loads(bytes(self.output))
            if not result.get('ok'):
                raise ValueError(result.get('error','Preview interpretation failed'))
            data = validate_result(result['data'])
        except Exception as exc:
            self._complete(None, str(exc))
        else:
            self._complete(data, None)

    def _complete(self, data, error):
        if not self.busy:
            return
        self.timeout.stop()
        if self.workspace is not None:
            self.workspace.cleanup()
            self.workspace = None
        self.busy = False
        self.busy_changed.emit(False)
        if error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(data)

    def shutdown(self):
        self.cancel()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.waitForFinished(1000)

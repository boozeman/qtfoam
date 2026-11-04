import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import unittest
try:
    from PyQt5 import QtWidgets
    from qtfoam.dro import DROView
    from qtfoam.backend import DemoBackend
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'PyQt5 not installed')
class DROTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.view = DROView()
        self.addCleanup(self.view.close)
        self.data = dict(DemoBackend().snapshot())
        self.data.update(file='prepared.ngc', program_text='G21 G90\nM8\nM0\n\nN100 G1 X10\nM2\n',
                         mode='Auto', idle=False, paused=False, execution_line=3)

    def test_tracks_file_lines_including_preamble_blank_lines_and_n_words(self):
        self.view.update_status(self.data)
        self.assertEqual(self.view.active_line, 3)
        self.assertEqual(self.view.code.extraSelections()[0].cursor.blockNumber(), 2)
        self.assertIn('3  M0', self.view.code.toPlainText())
        self.data.update(execution_line=5, paused=True)
        self.view.update_status(self.data)
        self.assertEqual(self.view.active_line, 5)
        self.assertIn('Paused', self.view.state.text())
        self.assertIn('5  N100', self.view.code.toPlainText())
        self.assertTrue(self.view.code.isReadOnly())

    def test_clears_tracking_for_idle_manual_status_loss_and_out_of_range(self):
        for change in ({'idle':True}, {'mode':'MDI'}, {'execution_line':99}):
            self.view.update_status(self.data)
            self.view.update_status(dict(self.data, **change))
            self.assertEqual(self.view.active_line, 0)
            self.assertEqual(self.view.code.extraSelections(), [])
        self.view.update_status(self.data)
        text = self.view.code.toPlainText()
        self.view.update_status(None)
        self.assertEqual(self.view.active_line, 0)
        self.assertEqual(self.view.code.toPlainText(), text)
        self.assertIn('unavailable', self.view.state.text())

    def test_loads_actual_file_and_replaces_stale_code_on_failure_or_unload(self):
        path = Path(__file__).resolve().parent.parent/'examples/xyuv-preview.ngc'
        self.data.update(file=str(path), program_text=None)
        self.view.update_status(self.data)
        self.assertGreater(self.view.line_count, 0)
        self.assertIn(path.read_text().splitlines()[0], self.view.code.toPlainText())
        self.data['file'] = str(path.with_name('does-not-exist.ngc'))
        self.view.update_status(self.data)
        self.assertEqual(self.view.code.toPlainText(), '')
        self.assertIn('Cannot display program', self.view.state.text())
        self.data['file'] = ''
        self.view.update_status(self.data)
        self.assertEqual(self.view.line_count, 0)
        self.assertEqual(self.view.file.text(), 'No program loaded in LinuxCNC')

    def test_follow_can_be_disabled_without_stopping_highlight(self):
        self.view.follow.setChecked(False)
        self.view.update_status(self.data)
        self.assertEqual(self.view.active_line, 3)
        self.assertEqual(self.view.code.textCursor().blockNumber(), 0)
        self.view.follow.setChecked(True)
        self.assertEqual(self.view.code.textCursor().blockNumber(), 2)

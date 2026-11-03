import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
import time
from pathlib import Path
try:
    from PyQt5 import QtWidgets, QtGui, QtTest
    from qtfoam.screen import Screen
    from qtfoam.backend import DemoBackend
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'PyQt5 not installed')
class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if os.name == 'nt':
            for name in ('arial.ttf', 'consola.ttf'):
                QtGui.QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot']) / 'Fonts' / name))
        cls.app.setStyleSheet((Path(__file__).resolve().parent.parent / 'qtfoam.qss').read_text())

    def test_demo_controls_and_no_overflow(self):
        screen = Screen(DemoBackend(), demo=True)
        screen.resize(1200,740)
        screen.show()
        self.app.processEvents()
        self.assertIn('DEMO',screen.badge.text())
        screen.send('reset')
        screen.send('on')
        screen.send('mdi_mode')
        screen.mdi.setText('G90')
        screen.send('mdi')
        self.assertEqual(screen.history,['G90'])
        self.assertTrue(screen.mdi.isEnabled())
        for index in range(3):
            screen.tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertLessEqual(screen.minimumSizeHint().width(),1200)
            self.assertLessEqual(screen.minimumSizeHint().height(),740)
        screen.timer.stop()
        screen.close()

    def wait_preview(self, screen):
        deadline = time.monotonic() + 6
        while screen.preview_job.busy and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertFalse(screen.preview_job.busy, 'Preview subprocess did not complete')

    def test_demo_preview_subprocess_slider_and_source_mapping(self):
        screen = Screen(DemoBackend(),demo=True)
        self.addCleanup(screen.cleanup)
        path = Path(__file__).resolve().parent.parent/'examples/devwing-preview.nc'
        screen.start_preview(path)
        self.assertTrue(screen.preview_job.busy)
        self.assertFalse(screen.preview_load.isEnabled())
        self.wait_preview(screen)
        self.assertIsNotNone(screen.wire.preview,screen.preview_message.text())
        self.assertTrue(screen.preview_slider.isEnabled())
        screen.preview_slider.setValue(2)
        self.assertIn('Source line 11',screen.preview_line.text())
        self.assertIn('F1.4428',screen.preview_code.toPlainText())
        self.assertEqual(screen.wire.preview_step,2)
        screen.clear_preview()
        self.assertIsNone(screen.wire.preview)
        screen.close()

    def test_stale_preview_and_parse_failure_discard_all_segments(self):
        backend = DemoBackend()
        screen = Screen(backend,demo=True)
        self.addCleanup(screen.cleanup)
        path = Path(__file__).resolve().parent.parent/'examples/xyuv-preview.ngc'
        screen.start_preview(path)
        backend.data['machine']['U'] += 10
        self.wait_preview(screen)
        self.assertIsNone(screen.wire.preview)
        self.assertIn('changed',screen.preview_message.text())
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder)/'unsupported.nc'
            bad.write_text('G1 X2 F100\nG2 X3 I2')
            screen.start_preview(bad)
            self.wait_preview(screen)
        self.assertIsNone(screen.wire.preview)
        self.assertFalse(screen.preview_slider.isEnabled())
        self.assertIn('requires the live LinuxCNC interpreter',screen.preview_message.text())
        screen.close()

    def test_preview_timeout_stops_worker_and_cleans_workspace(self):
        screen = Screen(DemoBackend(),demo=True)
        self.addCleanup(screen.cleanup)
        path = Path(__file__).resolve().parent.parent/'examples/xyuv-preview.ngc'
        screen.start_preview(path)
        workspace = Path(screen.preview_job.workspace.name)
        # Invoke the timer immediately rather than waiting 20 seconds in a test.
        screen.preview_job.timeout.start(1)
        self.wait_preview(screen)
        self.assertIsNone(screen.wire.preview)
        self.assertIn('20 seconds',screen.preview_message.text())
        self.assertFalse(workspace.exists())
        screen.close()

    def test_cancel_does_not_leave_preview_or_disable_safety(self):
        screen = Screen(DemoBackend(),demo=True)
        self.addCleanup(screen.cleanup)
        path = Path(__file__).resolve().parent.parent/'examples/xyuv-preview.ngc'
        screen.start_preview(path)
        self.assertTrue(screen.buttons[('estop',None)].isEnabled())
        workspace = Path(screen.preview_job.workspace.name)
        screen.send('estop')
        self.wait_preview(screen)
        self.assertFalse(workspace.exists())
        self.assertIsNone(screen.wire.preview)
        self.assertTrue(screen.preview_load.isEnabled())
        screen.close()

    def test_lost_status_clears_wire_and_disables_mdi(self):
        backend = DemoBackend()
        screen = Screen(backend,demo=True)
        def unavailable():
            raise RuntimeError('test disconnect')
        backend.snapshot = unavailable
        screen.refresh()
        self.assertIsNone(screen.wire.positions)
        self.assertFalse(screen.mdi.isEnabled())
        self.assertEqual(screen.dro[('U','machine')].text(),'—')
        screen.timer.stop()
        screen.close()


if __name__ == '__main__':
    unittest.main()

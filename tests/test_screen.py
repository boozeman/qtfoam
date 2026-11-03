import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from pathlib import Path
try:
    from PyQt5 import QtWidgets, QtGui
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

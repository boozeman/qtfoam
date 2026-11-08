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
    def test_toolpath_rotation_controls_and_rendering(self):
        from PyQt5 import QtCore
        screen = Screen(DemoBackend(), demo=True)
        self.addCleanup(screen.cleanup)
        wire = screen.wire
        wire.resize(700, 400)
        wire.set_preview({'initial_position': dict.fromkeys('XYUV', 0.),
                          'segments': [{'start': [0., 0., 0., 0.],
                                        'end': [100., 50., 120., 60.], 'kind': 'feed'}]})
        def drag(button, end, modifiers=QtCore.Qt.NoModifier):
            wire.mousePressEvent(QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,
                QtCore.QPointF(100, 100), button, button, modifiers))
            wire.mouseMoveEvent(QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                QtCore.QPointF(*end), QtCore.Qt.NoButton, button, modifiers))
            wire.mouseReleaseEvent(QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease,
                QtCore.QPointF(*end), button, QtCore.Qt.NoButton, modifiers))

        drag(QtCore.Qt.LeftButton, (140, 140))
        self.assertNotEqual(wire.yaw, -.65)
        self.assertEqual(wire.pitch, .42)
        yaw = wire.yaw
        drag(QtCore.Qt.RightButton, (140, 140))
        self.assertEqual(wire.yaw, yaw)
        self.assertGreater(wire.pitch, .42)
        drag(QtCore.Qt.RightButton, (100, 10000))
        self.assertLess(wire.pitch, 1.57)
        drag(QtCore.Qt.RightButton, (100, -10000))
        self.assertEqual(wire.pitch, 0.)
        drag(QtCore.Qt.MiddleButton, (100, 50))
        self.assertGreater(wire.zoom, 1.)
        self.assertFalse(wire.grab().isNull())
        cache_key = wire.path_cache[0]
        drag(QtCore.Qt.LeftButton, (140, 120), QtCore.Qt.ShiftModifier)
        self.assertEqual(wire.pan, QtCore.QPointF(40, 20))
        wire.grab()
        self.assertNotEqual(wire.path_cache[0], cache_key)
        anchor = QtCore.QPointF(250, 150)
        center = QtCore.QPointF(wire.width()/2, wire.height()/2)
        before = (anchor - center - wire.pan) / wire.zoom
        zoom = wire.zoom
        wire.wheelEvent(QtGui.QWheelEvent(anchor, anchor, QtCore.QPoint(),
            QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
            QtCore.Qt.NoScrollPhase, False))
        self.assertGreater(wire.zoom, zoom)
        after = (anchor - center - wire.pan) / wire.zoom
        self.assertAlmostEqual(before.x(), after.x())
        self.assertAlmostEqual(before.y(), after.y())
        wire.zoom_by(10000)
        self.assertEqual(wire.zoom, 20.)
        wire.zoom_by(-10000)
        self.assertGreaterEqual(wire.zoom, .25)
        wire.reset()
        self.assertEqual((wire.yaw, wire.pitch, wire.zoom), (-.65, .42, 1.))
        self.assertEqual(wire.pan, QtCore.QPointF())
        self.assertIsNone(wire.drag)
        self.assertIsNone(wire.drag_mode)

    def test_axis_home_highlight_and_latched_halt_priority(self):
        backend = DemoBackend()
        backend.data['switches'] = {'home': [True, True, False, None],
                                    'pos_limit': [False]*4,
                                    'halted': [False, True, False, False]}
        backend.data['homed'] = [False, True, True, False]
        screen = Screen(backend, demo=True)
        self.addCleanup(screen.cleanup)
        self.assertFalse(hasattr(screen, 'io_leds'))
        self.assertEqual(screen.dro[('X', 'homed')].text(), 'Homed')
        self.assertEqual(screen.dro[('X', 'homed')].objectName(), 'axis_home')
        self.assertEqual(screen.dro[('Y', 'homed')].text(), 'Halted')
        self.assertEqual(screen.dro[('Y', 'homed')].objectName(), 'axis_halted')
        backend.data['switches']['home'][0] = False
        screen.refresh()
        self.assertEqual(screen.dro[('X', 'homed')].text(), 'Not homed')
        self.assertEqual(screen.dro[('X', 'homed')].objectName(), 'muted')
        from unittest.mock import Mock
        backend.snapshot = Mock(side_effect=RuntimeError('lost'))
        screen.refresh()
        self.assertEqual(screen.dro[('Y', 'homed')].text(), 'Halted')
        self.assertEqual(screen.dro[('X', 'homed')].text(), '\u2014')

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
        for index in range(screen.tabs.count()):
            screen.tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertLessEqual(screen.minimumSizeHint().width(),1200)
            self.assertLessEqual(screen.minimumSizeHint().height(),740)
        screen.timer.stop()
        screen.close()

    def test_work_and_mdi_layout_and_coordinates(self):
        screen = Screen(DemoBackend(), demo=True)
        self.addCleanup(screen.cleanup)
        self.addCleanup(screen.close)
        screen.resize(1200, 740)
        screen.show()
        self.app.processEvents()
        self.assertEqual([screen.tabs.tabText(i) for i in range(screen.tabs.count())],
                         ['Work', 'MDI'])
        self.assertTrue(screen.wire.isVisible())
        self.assertTrue(screen.preview_slider.isVisible())
        self.assertFalse(hasattr(screen, 'preview_code'))
        self.assertFalse(hasattr(screen, 'preview_line'))
        self.assertGreaterEqual(screen.dro_view.code.height(),
                                2 * screen.dro_view.code.fontMetrics().lineSpacing() + 24)
        self.assertTrue(screen.dro_view.isVisible())
        self.assertTrue(screen.preview_load.isVisible())
        self.assertGreater(screen.wire.width(), 600)
        screen.wire.yaw = .3
        screen.tabs.setCurrentIndex(1)
        screen.backend.data['work']['X'] = 123.456
        screen.refresh()
        self.assertEqual(screen.mdi_coordinates['X'].text(), 'X 123.456')
        self.assertEqual(screen.mdi_coordinates['X'].text(),
                         screen.dro_view.coordinates['X'].text())
        screen.tabs.setCurrentIndex(0)
        self.assertEqual(screen.wire.yaw, .3)

    def test_status_messages_are_logged_once_and_coordinates_leave_preview(self):
        screen = Screen(DemoBackend(), demo=True)
        self.addCleanup(screen.close)
        screen.resize(1200, 740)
        screen.show()
        self.app.processEvents()
        for value in screen.dro_view.coordinates.values():
            self.assertFalse(value.isVisible())
        for value in (screen.message, screen.program_message, screen.preview_message,
                      screen.mdi_help, screen.dro_view.state):
            self.assertFalse(value.isVisible())
        before = screen.linuxcnc_messages.toPlainText()
        screen.refresh()
        screen.refresh()
        self.assertEqual(screen.linuxcnc_messages.toPlainText(), before)
        screen.set_status('preview_message', 'Preview failed: example error')
        self.assertIn('Preview failed: example error', screen.linuxcnc_messages.toPlainText())
        screen.send('reset')
        self.assertIn('Submitted: reset', screen.linuxcnc_messages.toPlainText())
        self.assertGreater(screen.wire.height(), 250)

    def wait_preview(self, screen):
        deadline = time.monotonic() + 6
        while screen.preview_job.busy and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertFalse(screen.preview_job.busy, 'Preview subprocess did not complete')

    def test_xu_shortcut_expands_then_sends_only_the_reviewed_line(self):
        from unittest.mock import Mock
        from PyQt5 import QtCore
        backend = DemoBackend()
        screen = Screen(backend, demo=True)
        self.addCleanup(screen.cleanup)
        screen.send('reset')
        screen.send('on')
        screen.send('mdi_mode')
        backend.execute = Mock(wraps=backend.execute)
        screen.mdi.setText('400XU')
        QtTest.QTest.keyClick(screen.mdi, QtCore.Qt.Key_Return)
        backend.execute.assert_not_called()
        self.assertEqual(screen.mdi.text(), 'G21 G90 G0 X400 U400')
        self.assertEqual(screen.history, [])
        # Edits made after expansion, rather than a cached shortcut, are executed.
        screen.mdi.setText('G21 G90 G0 X350 U350')
        screen.buttons[('mdi',None)].click()
        backend.execute.assert_called_once_with('mdi', axis=None, text='G21 G90 G0 X350 U350')
        self.assertEqual(screen.history, ['G21 G90 G0 X350 U350'])
        self.assertEqual(screen.mdi.text(), '')
        backend.execute.reset_mock()
        screen.mdi.setText('nanXU')
        screen.send('mdi')
        backend.execute.assert_not_called()
        self.assertEqual(screen.mdi.text(), 'nanXU')
        backend.execute.reset_mock()
        screen.mdi.setText('50YV')
        QtTest.QTest.keyClick(screen.mdi, QtCore.Qt.Key_Return)
        backend.execute.assert_not_called()
        self.assertEqual(screen.mdi.text(), 'G21 G90 G0 Y50 V50')
        QtTest.QTest.keyClick(screen.mdi, QtCore.Qt.Key_Return)
        backend.execute.assert_called_once_with('mdi', axis=None, text='G21 G90 G0 Y50 V50')
        self.assertEqual(screen.history[-1], 'G21 G90 G0 Y50 V50')
        self.assertEqual(screen.mdi.text(), '')

    def test_macro_loads_without_sending_and_heater_preserves_draft(self):
        from unittest.mock import Mock
        backend = DemoBackend()
        screen = Screen(backend, demo=True)
        self.addCleanup(screen.cleanup)
        screen.send('reset')
        screen.send('on')
        screen.send('mdi_mode')
        backend.execute = Mock(wraps=backend.execute)
        screen.macros = [('Cut', 'G1 X100 U100 F200'), ('Return', 'G0 X0 U0'),
                         ('Empty', ''), ('Empty', '')]
        screen.update_macro_buttons()
        screen.mdi.setText('G90')
        screen.macro_buttons[0].click()
        self.assertEqual(screen.mdi.text(), 'G1 X100 U100 F200')
        screen.macro_buttons[1].click()
        self.assertEqual(screen.mdi.text(), 'G0 X0 U0')
        backend.execute.assert_not_called()
        for button, command in zip(screen.heater_buttons, ('M8', 'M9')):
            button.click()
            backend.execute.assert_called_with('mdi', axis=None, text=command)
            self.assertEqual(screen.mdi.text(), 'G0 X0 U0')
            self.assertEqual(screen.history[0], command)
        screen.send('mdi')
        backend.execute.assert_called_with('mdi', axis=None, text='G0 X0 U0')
        self.assertEqual(screen.mdi.text(), '')
        screen.send('off')
        self.assertTrue(all(not button.isEnabled() for button in screen.heater_buttons))

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
        self.assertIn('Source line 11',screen.preview_slider.toolTip())
        self.assertIn('F1.4428',screen.preview_slider.toolTip())
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

    def test_numeric_keypad_rows_and_demo_program_controls(self):
        screen = Screen(DemoBackend(),demo=True)
        self.addCleanup(screen.cleanup)
        for row, expected in enumerate(('789','456','123','-0.')):
            actual = ''.join(screen.mdi_number_grid.itemAtPosition(row,col).widget().text() for col in range(3))
            self.assertEqual(actual,expected)
        screen.send('reset')
        screen.send('on')
        screen.start_preview(Path(__file__).resolve().parent.parent/'examples/xyuv-preview.ngc')
        self.wait_preview(screen)
        screen.refresh()
        self.assertTrue(screen.buttons[('run',None)].isEnabled())
        screen.send('run')
        self.assertFalse(screen.buttons[('run',None)].isEnabled())
        self.assertTrue(screen.buttons[('pause',None)].isEnabled())
        screen.send('pause')
        self.assertTrue(screen.buttons[('resume',None)].isEnabled())
        screen.send('resume')
        self.assertTrue(screen.buttons[('pause',None)].isEnabled())
        screen.send('abort_run')
        self.assertFalse(screen.buttons[('run',None)].isEnabled())
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

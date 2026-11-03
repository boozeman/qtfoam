import unittest
from types import SimpleNamespace
from qtfoam.preview import context_for, MAX_BYTES

class PreviewTests(unittest.TestCase):
    def status(self):
        return SimpleNamespace(linear_units=1,g5x_index=1,actual_position=[1,2,0,0,0,0,6,7,0],
            g5x_offset=[10,20,0,0,0,0,60,70,0],g92_offset=[0]*9,rotation_xy=0)
    def test_sparse_uv_offsets_and_start_position(self):
        context=context_for(self.status(),"G21 G90\nG1 X2 Y3 U7 V8 F100\nM2")
        self.assertEqual(context["position"]["U"],6)
        self.assertEqual(context["parameters"]["5227"],"60")
        self.assertEqual(context["parameters"]["5228"],"70")
        self.assertAlmostEqual(context["position_inches"][6],6/25.4)
    def test_upload_limits(self):
        for text in ("", "x"*(MAX_BYTES+1),None):
            with self.assertRaises(ValueError):context_for(self.status(),text)
    def test_imperial_initial_position(self):
        status=self.status();status.linear_units=1/25.4
        self.assertAlmostEqual(context_for(status,"M2")["position_mm"]["U"],152.4)
if __name__=="__main__":unittest.main()

class PreviewWorkerTests(unittest.TestCase):
    def test_callback_pipeline_preserves_uv_and_does_not_modify_machine_var(self):
        import sys
        import tempfile
        from pathlib import Path
        from types import ModuleType
        from unittest.mock import patch
        from qtfoam.preview_worker import parse
        status=PreviewTests().status()
        status.axis_mask=195
        status.joints=4
        status.tool_offset=[0]*9
        class Translated:
            def rotate_and_translate(self,*args): return args
        class StatMixin:
            def __init__(self,*args): pass
        fake_interpret=ModuleType("rs274.interpret")
        fake_interpret.Translated=Translated
        fake_interpret.StatMixin=StatMixin
        fake_linuxcnc=ModuleType("linuxcnc")
        fake_linuxcnc.stat=lambda:status
        fake_gcode=ModuleType("gcode")
        fake_gcode.MIN_ERROR=1
        def run(filename,canon,initcodes,interp):
            self.assertIn("G53 G0 X1 Y2 U6 V7",initcodes)
            # LinuxCNC invokes these even for ordinary G17/G1 programs.
            canon.set_plane(1)
            canon.set_traverse_rate(100)
            canon.comment("AXIS,UV_Z_POS,998")
            canon.set_feed_rate(900)
            canon.set_feed_rate(1.4428)  # G93 changes timing, not endpoints
            self.assertEqual(canon.plane, 1)
            canon.next_line(SimpleNamespace(sequence_number=1))
            try:
                canon.arc_feed()
            except ValueError:
                pass
            self.assertIn("arc_feed, line 1", canon.callback_error)
            canon.callback_error = None
            canon.next_line(SimpleNamespace(sequence_number=4))
            canon.straight_feed(1,2,0,0,0,0,8,9,0)
            return 0,4
        fake_gcode.parse=run
        with tempfile.TemporaryDirectory() as folder:
            original=Path(folder)/"machine.var"
            original.write_text("5221 999\n")
            status.ini_filename=str(Path(folder)/"machine.ini")
            status.poll=lambda:None
            fake_linuxcnc.ini=lambda _:SimpleNamespace(find=lambda section,key: str(original) if key == "PARAMETER_FILE" else None)
            with patch.dict(sys.modules,{"linuxcnc":fake_linuxcnc,"gcode":fake_gcode,
                                        "rs274":ModuleType("rs274"),"rs274.interpret":fake_interpret}):
                result=parse(context_for(status,"G1 U8 V9"))
            self.assertEqual(original.read_text(),"5221 999\n")
            self.assertEqual(result["segments"][0]["end"],[25.4,50.8,203.2,228.6])
            self.assertEqual(result["segments"][0]["line"],4)

class InitialPositionCodeTests(unittest.TestCase):
    def test_homing_roundoff_never_generates_e_words(self):
        from qtfoam.preview_worker import initial_position_code
        line = initial_position_code({"X":-3.885780586188048e-16,
                                     "Y":1.1379786002407855e-15,"U":0.0,"V":0.0})
        self.assertEqual(line, "G53 G0 X0 Y0 U0 V0")
        self.assertNotIn("e", line.lower())

    def test_decimal_coordinates_and_invalid_values(self):
        from qtfoam.preview_worker import initial_position_code
        self.assertEqual(initial_position_code({"X":280.125,"Y":-0.000001,"U":710,"V":120}),
                         "G53 G0 X280.125 Y-0.000001 U710 V120")
        with self.assertRaises(ValueError):
            initial_position_code({"X":float("nan"),"Y":0,"U":0,"V":0})

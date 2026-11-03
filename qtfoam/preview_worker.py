"""Isolated, read-only LinuxCNC RS274 preview. No linuxcnc.command or HAL."""
import json
from contextlib import nullcontext
import math
from pathlib import Path
import sys
import tempfile

MAX_SEGMENTS = 12000


def initial_position_code(position):
    """RS274 numbers must use decimal notation, never Python's e-notation."""
    words = []
    for axis in ("X", "Y", "U", "V"):
        value = position[axis]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Invalid initial coordinate: " + axis)
        number = format(value, ".12f").rstrip("0").rstrip(".")
        words.append(axis + ("0" if number in ("", "-0") else number))
    return "G53 G0 " + " ".join(words)

def parse(context):
    import linuxcnc
    import gcode
    from rs274.interpret import Translated, StatMixin

    s = linuxcnc.stat()
    s.poll()
    if s.axis_mask != 195 or s.joints != 4:
        raise ValueError("Preview requires four-joint XYUV configuration")
    if any(abs(v) > 1e-9 for v in s.tool_offset):
        raise ValueError("Disable tool length compensation before preview")
    class Canon(Translated, StatMixin):
        def __init__(self):
            StatMixin.__init__(self, s, 0)
            self.lo = tuple(context["position_inches"])
            self.line = 0
            self.segments = []
            self.parameter_file = ""
            self.callback_error = None
            # The C extension can overwrite callback exceptions with
            # "parse_file interp_error". Preserve the original failure.
            for name in ("next_line", "straight_traverse", "straight_feed",
                         "arc_feed", "straight_probe", "rigid_tap", "tool_offset",
                         "set_plane", "set_traverse_rate", "set_feed_rate",
                         "set_g5x_offset", "set_g92_offset", "set_xy_rotation",
                         "get_axis_mask", "get_tool", "get_block_delete",
                         "get_external_length_units", "get_external_angular_units"):
                callback = getattr(self, name, None)
                if callback is not None:
                    setattr(self, name, self.guard(name, callback))
        def guard(self, name, callback):
            def invoke(*args):
                try:
                    return callback(*args)
                except Exception as exc:
                    self.callback_error = "%s, line %s: %s: %s" % (
                        name, max(0,self.line-context.get("source_offset",0)), type(exc).__name__, exc)
                    raise
            return invoke
        def next_line(self, state):
            self.line = state.sequence_number
            self.state = state
        def move(self, kind, args):
            target = tuple(self.rotate_and_translate(*args))
            if not all(math.isfinite(v) for v in target):
                raise ValueError("Non-finite coordinates")
            if any(abs(target[i] - self.lo[i]) > 1e-9 for i in (2,3,4,5,8)):
                raise ValueError("Only X/Y/U/V motion is supported")
            # Initial positioning is supplied as initcode, never rendered.
            if self.line > 0 and target != self.lo:
                if len(self.segments) >= MAX_SEGMENTS:
                    raise ValueError("Preview exceeds 12000 segments")
                indices = (0,1,6,7)
                start = [round(self.lo[i]*25.4, 6) for i in indices]
                end = [round(target[i]*25.4, 6) for i in indices]
                self.segments.append({"start":start,"end":end,"kind":kind,"line":max(0,self.line-context.get("source_offset",0))})
            self.lo = target
        def straight_traverse(self,*args): self.move("rapid",args)
        def straight_feed(self,*args): self.move("feed",args)
        def arc_feed(self,*args):
            raise ValueError("G2/G3 arcs are not supported by XYUV preview yet")
        def straight_probe(self,*args):
            raise ValueError("Probing is not supported by XYUV preview")
        def rigid_tap(self,*args):
            raise ValueError("Rigid tapping is not supported by XYUV preview")
        def tool_offset(self,*args):
            if any(abs(v)>1e-9 for v in args):
                raise ValueError("Tool offsets are not supported by XYUV preview")
        def set_feed_rate(self,*args): pass
        def set_spindle_rate(self,*args): pass
        def set_plane(self, plane):
            self.plane = plane
        def select_plane(self, plane):
            self.set_plane(plane)
        def set_traverse_rate(self, rate): pass
        def dwell(self,*args): pass
        def comment(self,*args): pass
        def message(self,*args): pass
        def check_abort(self): pass
        def user_defined_function(self,*args): pass

    workspace = (nullcontext(context["temporary_directory"]) if context.get("temporary_directory")
                 else tempfile.TemporaryDirectory(prefix="qtfoam-preview-"))
    with workspace as temp:
        directory = Path(temp)
        parameter = directory / "preview.var"
        existing = {}
        ini = linuxcnc.ini(s.ini_filename)
        if ini.find("RS274NGC", "REMAP"):
            raise ValueError("Machine-specific REMAP is not supported by this preview")
        original = ini.find("RS274NGC", "PARAMETER_FILE")
        if original:
            original = Path(original).expanduser()
            if not original.is_absolute():
                original = Path(s.ini_filename).parent / original
            if original.is_file():
                for line in original.read_text().splitlines():
                    fields = line.split()
                    if len(fields) == 2:
                        existing[fields[0]] = fields[1]
        # Patch fresh offsets captured by the parent; never write the machine var file.
        existing.update(context["parameters"])
        parameter.write_text("".join(str(k)+" "+str(v)+"\n" for k,v in sorted(existing.items(), key=lambda item:int(item[0]))))
        program = directory / "preview.ngc"
        program.write_text(context["text"], encoding="utf-8")
        canon = Canon()
        canon.parameter_file = str(parameter)
        code = "G21" if context["linear_units"] == 1 else "G20"
        initial = initial_position_code(context["position"])
        wcs = {1:"G54",2:"G55",3:"G56",4:"G57",5:"G58",6:"G59",7:"G59.1",8:"G59.2",9:"G59.3"}[context["g5x_index"]]
        try:
            result, line = gcode.parse(str(program), canon, [code, "G90", wcs, initial], "")
        except Exception as exc:
            detail = canon.callback_error or str(exc)
            raise ValueError("Preview interpreter: " + detail) from exc
        if result > gcode.MIN_ERROR:
            raise ValueError("Line %s: %s" % (max(0,line-context.get("source_offset",0)),gcode.strerror(result)))
        return {"segments":canon.segments,"units":"mm","frame":"machine",
                "initial_position":context["position_mm"],
                "warning":"G0/G1 only; standard interpreter, no machine remaps or external subroutine paths. Offsets are a snapshot at upload time. Heater state is not modeled."}

def main():
    try:
        context = json.load(sys.stdin)
        if context.get("demo"):
            from qtfoam.demo_preview import parse_demo
            data = parse_demo(context)
        else:
            data = parse(context)
        result = {"ok":True,"data":data}
    except Exception as exc:
        result = {"ok":False,"error":str(exc)}
    print(json.dumps(result,allow_nan=False),flush=True)

if __name__ == "__main__":
    main()

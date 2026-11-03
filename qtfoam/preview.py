"""Read-only preview inputs and validation; no Qt or machine commands."""
import math
from pathlib import Path

MAX_BYTES = 256 * 1024
MAX_SEGMENTS = 12000


def read_source(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Preview file exceeds 256 KiB')
    text = raw.decode('utf-8-sig')
    if not text.strip() or '\0' in text:
        raise ValueError('Expected a nonempty UTF-8 G-code text file')
    return text


def context_for(status, text):
    if not isinstance(text,str) or len(text.encode("utf-8")) > MAX_BYTES or not text.strip():
        raise ValueError("Preview requires 1..256 KiB of UTF-8 G-code")
    if status.linear_units not in (1, 1/25.4):
        # LinuxCNC installations may expose an approximately equal inch scale.
        if not math.isclose(status.linear_units, 1/25.4):
            raise ValueError("Unsupported machine units")
    index = status.g5x_index
    if index not in range(1,10):
        raise ValueError("Invalid active coordinate system")
    position = {a:status.actual_position[i] for a,i in (("X",0),("Y",1),("U",6),("V",7))}
    mm = 1 if status.linear_units == 1 else 25.4
    parameters = {"5220":str(index), "5210":"1"}
    for i in range(9):
        parameters[str(5221+20*(index-1)+i)] = str(status.g5x_offset[i])
        parameters[str(5211+i)] = str(status.g92_offset[i])
    parameters[str(5230+20*(index-1))] = str(status.rotation_xy)
    return {"text":text,"g5x_index":index,"parameters":parameters,
            "position":position,"position_mm":{a:v*mm for a,v in position.items()},
            "position_inches":[v*mm/25.4 for v in status.actual_position],
            "linear_units":status.linear_units}


def baseline(s):
    return {'position': list(s.actual_position), 'g5x': list(s.g5x_offset),
            'g92': list(s.g92_offset), 'tool': list(s.tool_offset),
            'rotation': s.rotation_xy, 'wcs': s.g5x_index, 'units': s.linear_units}


def matches(expected, status):
    actual = baseline(status)
    if actual['wcs'] != expected['wcs'] or actual['units'] != expected['units']:
        return False
    for key in ('position', 'g5x', 'g92', 'tool'):
        if len(actual[key]) != len(expected[key]) or not all(
                math.isclose(a, b, rel_tol=0, abs_tol=.001 if key == 'position' else 1e-6)
                for a,b in zip(actual[key], expected[key])):
            return False
    return math.isclose(actual['rotation'], expected['rotation'], rel_tol=0, abs_tol=1e-6)


def prepare_context(status, text):
    if any(abs(v) > 1e-9 for v in status.tool_offset):
        raise ValueError('Disable tool length compensation before preview')
    context = context_for(status, text)
    context['baseline'] = baseline(status)
    context['source'] = text
    # Deterministic starting modes; same initialization used by Foamomatic.
    wcs = {1:'G54',2:'G55',3:'G56',4:'G57',5:'G58',6:'G59',7:'G59.1',8:'G59.2',9:'G59.3'}
    preamble = '%s G90 G94 G17 G40 G49 %s' % (
        'G21' if status.linear_units == 1 else 'G20', wcs[status.g5x_index])
    lines = text.splitlines()
    delimiters = [i for i,line in enumerate(lines) if line.strip() == '%']
    if delimiters:
        first = next((i for i,line in enumerate(lines) if line.strip()), None)
        last = next((i for i in range(len(lines)-1,-1,-1) if lines[i].strip()), None)
        if len(delimiters) != 2 or delimiters != [first, last]:
            raise ValueError('Expected matching leading/trailing percent delimiters')
        lines[first], lines[last] = '(percent start)', 'M2 (percent end)'
    context['text'] = preamble + '\n' + '\n'.join(lines) + '\nM2\n'
    context['source_offset'] = 1
    return context


def validate_result(data):
    if not isinstance(data, dict) or data.get('units') != 'mm' or data.get('frame') != 'machine':
        raise ValueError('Invalid preview coordinate frame')
    segments = data.get('segments')
    if not isinstance(segments, list) or not segments or len(segments) > MAX_SEGMENTS:
        raise ValueError('Preview must contain 1–12000 motion segments')
    initial = data.get('initial_position')
    if not isinstance(initial, dict) or not all(
            type(initial.get(a)) in (int,float) and math.isfinite(initial[a]) for a in 'XYUV'):
        raise ValueError('Invalid preview starting position')
    for segment in segments:
        if not isinstance(segment, dict) or segment.get('kind') not in ('feed','rapid'):
            raise ValueError('Invalid preview segment')
        if type(segment.get('line')) is not int or segment['line'] < 1:
            raise ValueError('Invalid preview source line')
        for key in ('start','end'):
            point = segment.get(key)
            if not isinstance(point, list) or len(point) != 4 or not all(
                    type(v) in (int,float) and math.isfinite(v) for v in point):
                raise ValueError('Invalid XYUV preview coordinates')
    return data

"""Strict geometry-only demo parser. Never imports LinuxCNC or controls a machine."""
import math
import re
from .preview import MAX_SEGMENTS

WORD = re.compile(r'([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))')


def parse_demo(context):
    position = dict(context['position_mm'])
    absolute, scale, motion = True, 1., 'rapid'
    segments = []
    for lineno, original in enumerate(context['source'].splitlines(), 1):
        line = re.sub(r'\([^()]*\)', '', original.split(';',1)[0]).strip()
        if not line or line == '%':
            continue
        words = []
        cursor = 0
        for match in WORD.finditer(line):
            if line[cursor:match.start()].strip():
                raise ValueError('Demo line %s: unsupported syntax' % lineno)
            words.append((match[1].upper(),float(match[2])))
            cursor = match.end()
        if line[cursor:].strip():
            raise ValueError('Demo line %s: unsupported syntax' % lineno)
        axes, end_program = {}, False
        for letter, value in words:
            if not math.isfinite(value):
                raise ValueError('Non-finite demo coordinate')
            if letter == 'G':
                if value in (0,1): motion = 'rapid' if value == 0 else 'feed'
                elif value in (20,21): scale = 25.4 if value == 20 else 1.
                elif value in (90,91): absolute = value == 90
                elif value not in (17,93,94):
                    raise ValueError('Demo line %s: G%s requires the live LinuxCNC interpreter' % (lineno,value))
            elif letter in 'XYUV':
                if letter in axes:
                    raise ValueError('Demo line %s: duplicate axis word' % lineno)
                axes[letter] = value
            elif letter == 'M':
                if value not in (0,1,2,3,4,5,7,8,9,30):
                    raise ValueError('Demo line %s: unsupported M code' % lineno)
                end_program = end_program or value in (2,30)
            elif letter not in ('N','F','S'):
                raise ValueError('Demo line %s: unsupported word %s' % (lineno,letter))
        if axes:
            target = position.copy()
            for axis,value in axes.items():
                target[axis] = value*scale + (0 if absolute else position[axis])
            if target != position:
                if len(segments) >= MAX_SEGMENTS:
                    raise ValueError('Preview exceeds 12000 segments')
                segments.append({'start':[position[a] for a in 'XYUV'],
                                 'end':[target[a] for a in 'XYUV'], 'kind':motion,'line':lineno})
            position = target
        if end_program:
            break
    return {'segments':segments, 'units':'mm','frame':'machine',
            'initial_position': context['position_mm'],
            'warning':'DEMO geometry only: limited G0/G1, G20/G21, G90/G91 and G93/G94 subset. '
                      'Offsets, macros and machine M-code behavior are not simulated.'}

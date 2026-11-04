"""Coordinate mapping and command permissions, independent of Qt and LinuxCNC."""
import math
import re
from decimal import Decimal
AXES = {'X': 0, 'Y': 1, 'U': 6, 'V': 7}
JOINTS = {'X': 0, 'Y': 1, 'U': 2, 'V': 3}


def positions(status):
    machine = {axis: float(status.actual_position[index]) for axis, index in AXES.items()}
    work = {axis: machine[axis] - status.g5x_offset[index] - status.tool_offset[index]
            for axis, index in AXES.items()}
    angle = math.radians(-status.rotation_xy)
    x, y = work['X'], work['Y']
    work['X'] = x * math.cos(angle) - y * math.sin(angle)
    work['Y'] = x * math.sin(angle) + y * math.cos(angle)
    work = {axis: work[axis] - status.g92_offset[index] for axis, index in AXES.items()}
    if not all(math.isfinite(v) for v in (*machine.values(), *work.values())):
        raise ValueError('Non-finite machine coordinates')
    return machine, work


def permissions(data):
    valid = bool(data and data.get('connected'))
    ready = valid and data['enabled'] and not data['estop']
    idle = ready and data['idle'] and not data['paused'] and not any(data['homing'])
    free = idle and not data.get('pending', False)
    homed = valid and all(data['homed'])
    return {'estop': valid, 'off': valid, 'abort': valid,
            'reset': valid and data['estop'],
            'on': valid and not data['estop'] and not data['enabled'],
            'manual': free and data['mode'] != 'Manual',
            'home': free and data['mode'] == 'Manual',
            'mdi_mode': free and homed and data['mode'] != 'MDI',
            'mdi': free and homed and data['mode'] == 'MDI'}


def validate_mdi(text):
    if not text or not text.strip() or not text.isascii() or len(text) > 254:
        raise ValueError('Enter 1–254 ASCII characters')
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ValueError('MDI must be a single line without control characters')
    return text.strip()


def expand_mdi_shortcut(text):
    """Return a reviewable G-code line for a whole-input XU shortcut."""
    text = validate_mdi(text)
    match = re.fullmatch(r'([+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+))\s*XU', text, re.IGNORECASE)
    if not match:
        if text.upper().endswith('XU'):
            raise ValueError('Use a number followed by XU, for example 400XU or 125.5XU')
        return None
    number = Decimal(match[1].replace(',', '.'))
    value = format(number, 'f') if number else '0'
    if '.' in value:
        value = value.rstrip('0').rstrip('.')
    return validate_mdi(f'G21 G90 G0 X{value} U{value}')

"""Read display geometry from the active LinuxCNC INI, in millimetres."""
import math


def demo_geometry():
    return {'limits': {a: (0., 710. if a in 'XU' else 260.) for a in 'XYUV'},
            'span': 1000.}


def read_geometry(ini, linear_units):
    if not math.isfinite(linear_units) or linear_units <= 0:
        raise ValueError('Invalid machine linear units')

    def number(section, key):
        try:
            value = float(ini.find(section, key)) / linear_units
        except (TypeError, ValueError):
            raise ValueError(f'Set [{section}] {key} in the machine INI file') from None
        if not math.isfinite(value):
            raise ValueError(f'Invalid [{section}] {key}')
        return value

    limits = {}
    for axis in 'XYUV':
        lower = number('AXIS_' + axis, 'MIN_LIMIT')
        upper = number('AXIS_' + axis, 'MAX_LIMIT')
        if lower >= upper:
            raise ValueError(f'[AXIS_{axis}] MIN_LIMIT must be less than MAX_LIMIT')
        limits[axis] = (lower, upper)
    span = number('QTFOAM', 'WIRE_SPAN')
    if span <= 0:
        raise ValueError('[QTFOAM] WIRE_SPAN must be positive')
    return {'limits': limits, 'span': span}

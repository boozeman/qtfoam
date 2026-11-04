import unittest
from types import SimpleNamespace
from qtfoam.geometry import read_geometry


class GeometryTests(unittest.TestCase):
    def ini(self, overrides=None):
        values = {('AXIS_' + a, key): str(value)
                  for a, bounds in {'X':(-10,710), 'Y':(-20,260),
                                    'U':(5,650), 'V':(10,240)}.items()
                  for key, value in zip(('MIN_LIMIT','MAX_LIMIT'), bounds)}
        values[('QTFOAM','WIRE_SPAN')] = '1200'
        values.update(overrides or {})
        return SimpleNamespace(find=lambda section,key: values.get((section,key)))

    def test_independent_limits_and_guide_span(self):
        geometry = read_geometry(self.ini(), 1.)
        self.assertEqual(geometry['limits'], {'X':(-10.,710.), 'Y':(-20.,260.),
                                              'U':(5.,650.), 'V':(10.,240.)})
        self.assertEqual(geometry['span'], 1200.)

    def test_inch_machine_is_converted_to_mm(self):
        geometry = read_geometry(self.ini(), 1/25.4)
        self.assertAlmostEqual(geometry['span'], 1200*25.4)
        self.assertAlmostEqual(geometry['limits']['X'][0], -254.)

    def test_missing_and_invalid_geometry_is_rejected(self):
        for key, value in [(('QTFOAM','WIRE_SPAN'), None),
                           (('QTFOAM','WIRE_SPAN'), '0'),
                           (('QTFOAM','WIRE_SPAN'), '-1'),
                           (('QTFOAM','WIRE_SPAN'), 'nan'),
                           (('AXIS_X','MIN_LIMIT'), None),
                           (('AXIS_U','MAX_LIMIT'), 'inf'),
                           (('AXIS_Y','MAX_LIMIT'), '-30')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                read_geometry(self.ini({key:value}), 1.)

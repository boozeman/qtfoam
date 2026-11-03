import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from qtfoam.preview import prepare_context, read_source, validate_result, matches, MAX_BYTES
from qtfoam.backend import DemoBackend
from qtfoam.demo_preview import parse_demo


class PreviewTests(unittest.TestCase):
    def test_source_read_limits_and_utf8_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'test.nc'
            p.write_bytes(b'\xef\xbb\xbfG90\nM2')
            self.assertEqual(read_source(p),'G90\nM2')
            for content in (b'', b'G0\0X2', b'x'*(MAX_BYTES+1), b'\xff'):
                p.write_bytes(content)
                with self.assertRaises((ValueError,UnicodeError)):
                    read_source(p)

    def test_source_mapping_and_percent_delimiters(self):
        context = DemoBackend().preview_context('%\nG1 X20 F100\n%')
        self.assertTrue(context['text'].startswith('G21 G90 G94 G17 G40 G49 G54\n'))
        self.assertEqual(context['source_offset'],1)
        self.assertIn('(percent start)\nG1 X20 F100\nM2 (percent end)',context['text'])
        for source in ('%\nG1 X2', '%\nG1 X2\n%\nG1 X3'):
            with self.assertRaises(ValueError):
                DemoBackend().preview_context(source)

    def test_devwing_g93_demo_paths_and_source_lines(self):
        path = Path(__file__).resolve().parent.parent/'examples/devwing-preview.nc'
        context = DemoBackend().preview_context(read_source(path))
        result = validate_result(parse_demo(context))
        self.assertEqual(result['segments'][0]['line'],9)
        self.assertEqual(result['segments'][1]['line'],11)
        self.assertEqual(result['segments'][1]['end'],[15.7966,36.6111,100.3729,36.6111])
        self.assertIn('DEMO',result['warning'])

    def test_incremental_inches_and_unsupported_demo_syntax(self):
        backend = DemoBackend()
        result = parse_demo(backend.preview_context('G20 G91\nG1 X1 U2 F10\nM2'))
        self.assertAlmostEqual(result['segments'][0]['end'][0],125+25.4)
        self.assertAlmostEqual(result['segments'][0]['end'][2],210+50.8)
        for source in ('G2 X10 I5', '#1=5', 'G1 Z2', 'G54 G1 X2', 'G1 X1 X2'):
            with self.assertRaises(ValueError):
                parse_demo(backend.preview_context(source))

    def test_invalid_worker_result_is_never_partial_success(self):
        result = parse_demo(DemoBackend().preview_context('G1 X10 F100'))
        self.assertIs(validate_result(result),result)
        result['segments'].append({'start':[0,0,0,0],'end':[0,0,math.nan,0],'kind':'feed','line':2})
        with self.assertRaises(ValueError):
            validate_result(result)

    def test_position_change_invalidates_context(self):
        backend = DemoBackend()
        context = backend.preview_context('G1 X10 F100')
        self.assertTrue(backend.preview_matches(context))
        backend.data['machine']['U'] += 1
        self.assertFalse(backend.preview_matches(context))


if __name__ == '__main__':
    unittest.main()

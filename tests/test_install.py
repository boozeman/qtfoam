from pathlib import Path
import tempfile
import unittest
from deploy.install_screen import install


class InstallTests(unittest.TestCase):
    def test_update_preserves_ini_and_backs_up_previous_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            target = Path(directory) / 'machine'
            root.mkdir()
            target.mkdir()
            for name in ('qtfoam.ui','qtfoam_handler.py','qtfoam.qss'):
                (root/name).write_text('new')
            (root/'qtfoam').mkdir()
            (root/'qtfoam/model.py').write_text('new model')
            (target/'machine.ini').write_text('DISPLAY = axis')
            (target/'qtfoam.ui').write_text('old')
            install(root,target)
            self.assertEqual((target/'machine.ini').read_text(),'DISPLAY = axis')
            self.assertEqual((target/'qtfoam.ui').read_text(),'new')
            backup = next(target.glob('qtfoam-backup-*'))
            self.assertEqual((backup/'qtfoam.ui').read_text(),'old')


if __name__ == '__main__':
    unittest.main()

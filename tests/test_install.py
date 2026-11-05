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
            for name in ('qtfoam.ui','qtfoam_handler.py','qtfoam.qss','LICENSE','NOTICE.txt'):
                (root/name).write_text('new')
            (root/'qtfoam').mkdir()
            (root/'qtfoam/model.py').write_text('new model')
            (target/'machine.ini').write_text('DISPLAY = axis')
            (target/'qtfoam.ui').write_text('old')
            (target/'LICENSE').write_text('machine license')
            (target/'qtfoam.LICENSE').write_text('old screen license')
            install(root,target)
            self.assertEqual((target/'machine.ini').read_text(),'DISPLAY = axis')
            self.assertEqual((target/'qtfoam.ui').read_text(),'new')
            self.assertEqual((target/'LICENSE').read_text(),'machine license')
            self.assertEqual((target/'qtfoam.LICENSE').read_text(),'new')
            self.assertEqual((target/'qtfoam.NOTICE.txt').read_text(),'new')
            backup = next(target.glob('qtfoam-backup-*'))
            self.assertEqual((backup/'qtfoam.ui').read_text(),'old')
            self.assertEqual((backup/'qtfoam.LICENSE').read_text(),'old screen license')


if __name__ == '__main__':
    unittest.main()

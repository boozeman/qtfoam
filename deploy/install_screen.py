"""Copy QtFoam into an existing LinuxCNC configuration; never edit INI/HAL."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil


def install(root, target):
    if not target.is_dir():
        raise ValueError('Configuration directory must already exist')
    files = [(name, name) for name in ('qtfoam.ui', 'qtfoam_handler.py', 'qtfoam.qss', 'qtfoam')]
    files.extend((('LICENSE', 'qtfoam.LICENSE'), ('NOTICE.txt', 'qtfoam.NOTICE.txt')))
    existing = [name for _, name in files if (target / name).exists()]
    if existing:
        backup = target / ('qtfoam-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir()
        for name in existing:
            source = target / name
            if source.is_dir():
                shutil.copytree(source, backup / name)
            else:
                shutil.copy2(source, backup / name)
    for source_name, name in files:
        source = root / source_name
        if source.is_dir():
            shutil.copytree(source, target / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(source, target / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    target = args.config_dir.expanduser().resolve()
    if root == target or root in target.parents or target in root.parents:
        parser.error('Use a separate LinuxCNC configuration directory')
    install(root, target)
    print('Installed QtFoam in ' + str(target))
    print('Set [DISPLAY] DISPLAY = qtvcp -m qtfoam in a COPY of your validated INI.')
    print('No INI/HAL settings were changed. Existing QtFoam files were backed up.')


if __name__ == '__main__':
    main()

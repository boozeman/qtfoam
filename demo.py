"""Hardware-free QtFoam layout demo: python3 demo.py."""
import sys
from pathlib import Path
from PyQt5 import QtWidgets, uic
from qtfoam.backend import DemoBackend
from qtfoam.screen import Screen


def main():
    app = QtWidgets.QApplication(sys.argv)
    root = Path(__file__).resolve().parent
    window = uic.loadUi(str(root / 'qtfoam.ui'))
    window.screen_layout.addWidget(Screen(DemoBackend(), demo=True))
    window.setStyleSheet((root / 'qtfoam.qss').read_text())
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())

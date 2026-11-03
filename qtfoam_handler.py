"""QtVCP entry point; never creates a demo backend on a live startup failure."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from qtfoam.backend import LinuxCNCBackend
from qtfoam.screen import Screen


class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.w = widgets

    def initialized__(self):
        self.screen = Screen(LinuxCNCBackend(), demo=False)
        self.w.screen_layout.addWidget(self.screen)
        self.w.setStyleSheet((ROOT / 'qtfoam.qss').read_text())

    def closing_cleanup__(self):
        self.screen.timer.stop()


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]

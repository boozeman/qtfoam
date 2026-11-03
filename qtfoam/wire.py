"""Native QPainter XYUV view: endpoints on two parallel planes."""
import math
from PyQt5 import QtCore, QtGui, QtWidgets


class WireView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 280)
        self.positions = None
        self.yaw = -0.55
        self.pitch = 0.45
        self.drag = None
        self.width_mm, self.horizontal, self.vertical = 1000., 710., 260.
        self.setToolTip('Drag to rotate. Straight wire; nominal stock width, no sag model.')

    def set_positions(self, positions):
        self.positions = positions
        self.update()

    def reset(self):
        self.yaw, self.pitch = -0.55, 0.45
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag = event.pos()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.pos() - self.drag
            self.yaw += delta.x() * .008
            self.pitch = max(-1.3, min(1.3, self.pitch + delta.y() * .008))
            self.drag = event.pos()
            self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor('#101c1c'))
        def rotated(point):
            x, depth, z = point
            x -= self.horizontal / 2
            depth -= self.width_mm / 2
            z -= self.vertical / 2
            horizontal = depth * math.cos(self.yaw) + x * math.sin(self.yaw)
            distance = -depth * math.sin(self.yaw) + x * math.cos(self.yaw)
            return horizontal, -z * math.cos(self.pitch) + distance * math.sin(self.pitch)
        corners = [(x, d, z) for d in (0, self.width_mm)
                   for x in (0, self.horizontal) for z in (0, self.vertical)]
        rotated_corners = [rotated(p) for p in corners]
        xs, ys = zip(*rotated_corners)
        scale = min((self.width()-90)/(max(xs)-min(xs)), (self.height()-100)/(max(ys)-min(ys)))
        def project(point):
            x, y = rotated(point)
            return QtCore.QPointF(self.width()/2 + x*scale, self.height()/2 + y*scale)
        def line(a, b, color, width=1):
            painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
            painter.drawLine(project(a), project(b))
        for depth in (0, self.width_mm):
            for x in range(0, int(self.horizontal)+1, 100):
                line((x,depth,0), (x,depth,self.vertical), '#263f3a')
            for z in range(0, int(self.vertical)+1, 50):
                line((0,depth,z), (self.horizontal,depth,z), '#263f3a')
            for a,b in [((0,depth,0),(self.horizontal,depth,0)),
                        ((0,depth,0),(0,depth,self.vertical)),
                        ((0,depth,self.vertical),(self.horizontal,depth,self.vertical)),
                        ((self.horizontal,depth,0),(self.horizontal,depth,self.vertical))]:
                line(a,b,'#6e9d8d',2)
            painter.setPen(QtGui.QColor('#a9c8bb'))
            painter.drawText(project((0,depth,self.vertical)) + QtCore.QPointF(-20,-14),
                             'Left · XY' if depth == 0 else 'Right · UV')
        if self.positions:
            p = self.positions
            a, b = (p['X'],0,p['Y']), (p['U'],self.width_mm,p['V'])
            line(a,b,'#f3f5e5',3)
            for point,color in ((a,'#73d4b3'),(b,'#bea4fa')):
                painter.setBrush(QtGui.QColor(color))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(project(point),5,5)
        painter.setPen(QtGui.QColor('#819d91'))
        painter.drawText(18,self.height()-16,'1000 mm nominal stock width · X/U 0–710 · Y/V 0–260 mm')

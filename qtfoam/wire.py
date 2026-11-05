"""Native QPainter XYUV view: endpoints on two parallel planes."""
import math
from PyQt5 import QtCore, QtGui, QtWidgets
from .geometry import demo_geometry


class WireView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 210)
        self.positions = None
        self.preview = None
        self.preview_step = 0
        self.path_cache = None
        self.yaw = -0.65
        self.pitch = 0.42
        self.roll = 0.
        self.rotation_axis = 'Free'
        self.drag = None
        self.geometry = demo_geometry()
        self.geometry_error = ''
        self.width_mm = self.geometry['span']
        self.setToolTip('Select Free, X, Y or Z, then drag to rotate. '
                        'View axes: X/U travel, Y guide span, Z vertical. '
                        'Straight wire between guides; no sag model.')

    def set_geometry(self, geometry, error=''):
        if geometry == self.geometry and error == self.geometry_error:
            return
        self.geometry, self.geometry_error = geometry, error
        if geometry:
            self.width_mm = geometry['span']
        self.path_cache = None
        self.update()

    def set_positions(self, positions):
        self.positions = positions
        self.update()

    def set_preview(self, data):
        self.preview = data
        self.preview_step = 0
        self.path_cache = None
        self.preview_bounds = None
        if data:
            points = [point for segment in data['segments'] for point in (segment['start'],segment['end'])]
            self.preview_bounds = (min(min(p[0],p[2]) for p in points),
                                   max(max(p[0],p[2]) for p in points),
                                   min(min(p[1],p[3]) for p in points),
                                   max(max(p[1],p[3]) for p in points))
        self.update()

    def set_preview_step(self, step):
        self.preview_step = step
        self.update()

    def reset(self):
        self.yaw, self.pitch = -0.65, 0.42
        self.roll = 0.
        self.update()

    def set_rotation_axis(self, axis):
        if axis not in ('Free', 'X', 'Y', 'Z'):
            raise ValueError('Unknown view rotation axis')
        self.rotation_axis = axis
        self.drag = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag = event.pos()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.pos() - self.drag
            angle = (delta.x() - delta.y()) * .008
            if self.rotation_axis == 'Free':
                self.yaw += delta.x() * .008
                self.pitch = max(-1.3, min(1.3, self.pitch + delta.y() * .008))
            elif self.rotation_axis == 'X':
                self.pitch += angle
            elif self.rotation_axis == 'Y':
                self.roll += angle
            else:
                self.yaw += angle
            self.drag = event.pos()
            self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor('#101c1c'))
        if not self.geometry:
            painter.setPen(QtGui.QColor('#a9c8bb'))
            painter.drawText(self.rect().adjusted(18,18,-18,-18),
                             QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                             self.geometry_error or 'Visualization geometry unavailable')
            return
        limits = self.geometry['limits']
        x_min = min(limits[a][0] for a in 'XU')
        x_max = max(limits[a][1] for a in 'XU')
        z_min = min(limits[a][0] for a in 'YV')
        z_max = max(limits[a][1] for a in 'YV')
        def rotated(point):
            x, depth, z = point
            x -= (x_min + x_max) / 2
            depth -= self.width_mm / 2
            z -= (z_min + z_max) / 2
            # Rotation about the span (view Y) before the existing Z/X orbit.
            x, z = (x * math.cos(self.roll) + z * math.sin(self.roll),
                    -x * math.sin(self.roll) + z * math.cos(self.roll))
            # Match Foamomatic: X/U zero is at the front of the cutter.
            horizontal = x * math.cos(self.yaw) - depth * math.sin(self.yaw)
            distance = x * math.sin(self.yaw) + depth * math.cos(self.yaw)
            return horizontal, -z * math.cos(self.pitch) + distance * math.sin(self.pitch)
        corners = [(x, d, z) for d, axes in ((0,'XY'), (self.width_mm,'UV'))
                   for x in limits[axes[0]] for z in limits[axes[1]]]
        if self.preview:
            x0,x1,z0,z1 = self.preview_bounds
            corners.extend((x,d,z) for x in (x0,x1) for d in (0,self.width_mm) for z in (z0,z1))
        rotated_corners = [rotated(p) for p in corners]
        xs, ys = zip(*rotated_corners)
        center_x, center_y = (max(xs)+min(xs))/2, (max(ys)+min(ys))/2
        scale = min((self.width()-90)/max(1e-9, max(xs)-min(xs)),
                    (self.height()-100)/max(1e-9, max(ys)-min(ys)))
        def project(point):
            x, y = rotated(point)
            return QtCore.QPointF(self.width()/2 + (x-center_x)*scale,
                                 self.height()/2 + (y-center_y)*scale)
        def line(a, b, color, width=1):
            painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
            painter.drawLine(project(a), project(b))
        # Reference table at the lowest vertical travel limit, between the guides.
        table = [(x_min, 0, z_min), (x_max, 0, z_min),
                 (x_max, self.width_mm, z_min), (x_min, self.width_mm, z_min)]
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(110, 157, 141, 18))
        painter.drawPolygon(QtGui.QPolygonF([project(p) for p in table]))
        painter.setBrush(QtCore.Qt.NoBrush)
        x_step = max(100, math.ceil((x_max-x_min)/10000)*100)
        depth_step = max(100, math.ceil(self.width_mm/10000)*100)
        for x in range(math.ceil(x_min/x_step)*x_step, math.floor(x_max)+1, x_step):
            line((x,0,z_min), (x,self.width_mm,z_min), '#263f3a')
        for depth in range(0, math.floor(self.width_mm)+1, depth_step):
            line((x_min,depth,z_min), (x_max,depth,z_min), '#263f3a')
        for a, b in zip(table, table[1:] + table[:1]):
            line(a, b, '#6e9d8d', 2)
        for depth, axes in ((0,'XY'), (self.width_mm,'UV')):
            x0,x1 = limits[axes[0]]
            z0,z1 = limits[axes[1]]
            x_step = max(100, math.ceil((x1-x0)/10000)*100)
            z_step = max(50, math.ceil((z1-z0)/5000)*50)
            for x in range(math.ceil(x0/x_step)*x_step, math.floor(x1)+1, x_step):
                line((x,depth,z0), (x,depth,z1), '#263f3a')
            for z in range(math.ceil(z0/z_step)*z_step, math.floor(z1)+1, z_step):
                line((x0,depth,z), (x1,depth,z), '#263f3a')
            for a,b in [((x0,depth,z0),(x1,depth,z0)),
                        ((x0,depth,z0),(x0,depth,z1)),
                        ((x0,depth,z1),(x1,depth,z1)),
                        ((x1,depth,z0),(x1,depth,z1))]:
                line(a,b,'#6e9d8d',2)
            painter.setPen(QtGui.QColor('#a9c8bb'))
            painter.drawText(project((x0,depth,z1)) + QtCore.QPointF(-20,-14),
                             'Left · XY' if depth == 0 else 'Right · UV')
        if self.preview:
            key = (self.width(),self.height(),self.yaw,self.pitch,self.roll)
            if self.path_cache is None or self.path_cache[0] != key:
                layer = QtGui.QPixmap(self.size())
                layer.fill(QtCore.Qt.transparent)
                paths = QtGui.QPainter(layer)
                paths.setRenderHint(QtGui.QPainter.Antialiasing)
                segments = self.preview['segments']
                paths.setPen(QtCore.Qt.NoPen)
                paths.setBrush(QtGui.QColor(134,112,200,22))
                for segment in segments:
                    if segment['kind'] == 'feed':
                        a,b = segment['start'],segment['end']
                        paths.drawPolygon(QtGui.QPolygonF([project((a[0],0,a[1])),project((b[0],0,b[1])),
                            project((b[2],self.width_mm,b[3])),project((a[2],self.width_mm,a[3]))]))
                paths.setBrush(QtCore.Qt.NoBrush)
                for segment in segments:
                    a,b = segment['start'],segment['end']
                    for index,depth,color in ((0,0,'#72c4dd'),(2,self.width_mm,'#bb98ed')):
                        pen = QtGui.QPen(QtGui.QColor('#e9a35c' if segment['kind']=='rapid' else color),1.5)
                        if segment['kind'] == 'rapid':
                            pen.setStyle(QtCore.Qt.DashLine)
                        paths.setPen(pen)
                        paths.drawLine(project((a[index],depth,a[index+1])),project((b[index],depth,b[index+1])))
                paths.end()
                self.path_cache = key,layer
            painter.drawPixmap(0,0,self.path_cache[1])
            if self.preview_step == 0:
                p = self.preview['initial_position']
                selected = [p[a] for a in 'XYUV']
            else:
                selected = self.preview['segments'][self.preview_step-1]['end']
            line((selected[0],0,selected[1]),(selected[2],self.width_mm,selected[3]),'#f0ce72',2)
        if self.positions:
            p = self.positions
            a, b = (p['X'],0,p['Y']), (p['U'],self.width_mm,p['V'])
            line(a,b,'#f3f5e5',3)
            for point,color in ((a,'#73d4b3'),(b,'#bea4fa')):
                painter.setBrush(QtGui.QColor(color))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(project(point),5,5)
        painter.setPen(QtGui.QColor('#819d91'))
        ranges = ' · '.join(f'{a} {limits[a][0]:g}–{limits[a][1]:g}' for a in 'XYUV')
        painter.drawText(18,self.height()-16,f'Guide span {self.width_mm:g} mm · {ranges} mm')

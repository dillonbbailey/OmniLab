"""CPU image presentation, camera gestures and USD transform manipulators."""
import math
import numpy as np

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget
from pxr import Gf, Usd, UsdGeom, UsdLux

from omnilab.core.camera import ViewCamera, scene_camera
from omnilab.usd.usd_transform_pose import gizmo_axes, manipulated_world, rows
from omnilab.usd.usd_transform_lock import is_locked


class Viewport(QWidget):
    cameraChanged = Signal()
    pickRequested = Signal(list, bool)
    transformCommitted = Signal(dict)
    transformPreviewChanged = Signal(object)
    cameraCommitted = Signal(dict)
    frameRequested = Signal(bool)
    toolChanged = Signal(str)
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 250)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.document = None
        self.camera = ViewCamera()
        self.scene_camera_path = ""
        self.image = QImage()
        self.message = "Open a USD scene or create a demo."
        self.tool = "translate"
        self.space = "world"
        self.grid = True
        self.guides = True
        self.display = "Shaded"
        self.handles = []
        self.drag = None
        self.preview_world = None
        self.edit_time = "default"
        self.depth = None
        self.depth_current = False
        self.visible_purposes = {'default', 'render'}
        self.edit_camera = False
        self.camera_gesture = None

    def render_camera(self):
        aspect = max(self.width(), 1) / max(self.height(), 1)
        if self.scene_camera_path and self.document and self.camera_gesture is None:
            return scene_camera(self.document.stage, self.scene_camera_path, self.document.frame, aspect)
        return self.camera.camera(aspect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def image_rect(self):
        if self.image.isNull():
            return QRectF(self.rect())
        scale = min(self.width() / self.image.width(), self.height() / self.image.height())
        w, h = self.image.width() * scale, self.image.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def set_frame(self, message):
        h, w, channels = message["shape"]
        if channels != 4:
            raise ValueError("Expected RGBA8 LdrColor output.")
        self.image = QImage(message["pixels"], w, h, w * 4, QImage.Format_RGBA8888).copy()
        self.depth = np.frombuffer(message['depth'], dtype=np.float32).reshape(h, w) if message.get('depth') else None
        self.depth_current = message.get('depth_current', False)
        self.message = ""
        self.update()

    def project(self, point):
        clip = self._view_projection.Transform(Gf.Vec3d(*point))
        camera_point = self._view_matrix.Transform(Gf.Vec3d(*point))
        if camera_point[2] >= 0:
            return None
        rect = self.image_rect()
        return QPointF(rect.left() + (clip[0] + 1) * .5 * rect.width(),
                       rect.top() + (1 - clip[1]) * .5 * rect.height())

    def line3d(self, painter, a, b):
        a, b = self.project(a), self.project(b)
        if a is not None and b is not None:
            # Avoid enormous raster coordinates when a line crosses the near plane.
            if max(abs(a.x()), abs(a.y()), abs(b.x()), abs(b.y())) < 1e6:
                painter.drawLine(a, b)

    def selected_world(self):
        if not self.document or not self.document.selection:
            return None
        prim = self.document.stage.GetPrimAtPath(self.document.selection[0])
        xform = UsdGeom.Xformable(prim)
        if not xform or is_locked(prim) or prim.IsInstanceProxy() or prim.IsInPrototype():
            return None
        return xform.ComputeLocalToWorldTransform(Usd.TimeCode(self.document.frame))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#24262b"))
        if not self.image.isNull():
            painter.drawImage(self.image_rect(), self.image)
        camera = self.render_camera()
        frustum = camera.frustum
        self._view_matrix = frustum.ComputeViewMatrix()
        self._view_projection = self._view_matrix * frustum.ComputeProjectionMatrix()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.image_rect())
        if self.grid:
            step = 10 ** math.floor(math.log10(max(.001, self.camera.distance / 10)))
            painter.setPen(QPen(QColor(140, 150, 165, 65), 1))
            for i in range(-10, 11):
                a, b = [i * step, 0, -10 * step], [i * step, 0, 10 * step]
                c, d = [-10 * step, 0, i * step], [10 * step, 0, i * step]
                if self.camera.up_axis == "Z":
                    a, b, c, d = ([v[0], v[2], 0] for v in (a, b, c, d))
                self.line3d(painter, a, b)
                self.line3d(painter, c, d)
        if self.document and (self.guides or self.display in ("Points", "Wire over Shaded")):
            self.draw_scene_overlays(painter)
        self.handles = []
        world = self.preview_world or self.selected_world()
        if world is not None:
            pivot = world.ExtractTranslation()
            origin = self.project(pivot)
            size = self.camera.distance * .075
            if origin is not None:
                for axis, vector in enumerate(gizmo_axes(world, self.space)):
                    end = self.project(pivot + vector * size)
                    if end is None:
                        continue
                    color = (QColor("#ff6b68"), QColor("#80dc83"), QColor("#77a8ff"))[axis]
                    painter.setPen(QPen(color, 3))
                    painter.drawLine(origin, end)
                    painter.setBrush(color)
                    if self.tool == "scale":
                        painter.drawRect(QRectF(end.x() - 4, end.y() - 4, 8, 8))
                    else:
                        painter.drawEllipse(end, 4, 4)
                    painter.drawText(end + QPointF(6, -6), "XYZ"[axis])
                    self.handles.append((axis, origin, end, size))
        if self.drag and self.drag["kind"] == "pick":
            painter.setPen(QPen(QColor("#8ab4f8"), 1, Qt.DashLine))
            painter.setBrush(QColor(100, 150, 240, 25))
            painter.drawRect(QRectF(self.drag["start"], self.drag["last"]).normalized())
        painter.setClipping(False)
        painter.setPen(QColor("#eceff5"))
        title = self.scene_camera_path or ("Orthographic" if self.camera.orthographic else "Perspective")
        painter.drawText(12, 22, f"{title}   ·   {self.tool.title()} / {self.space.title()}")
        painter.drawText(12, self.height() - 12, "Alt+LMB orbit · MMB pan · Wheel dolly · F frame · W/E/R transform")
        if self.message:
            painter.fillRect(QRectF(0, 35, self.width(), 30), QColor(25, 28, 35, 210))
            painter.drawText(12, 55, self.message[:140])

    def draw_scene_overlays(self, painter):
        time = Usd.TimeCode(self.document.frame)
        self._overlay_budget = 100000
        for number, prim in enumerate(self.document.stage.Traverse()):
            if number > 10000:
                break
            xform = UsdGeom.Xformable(prim)
            if not xform:
                continue
            matrix = xform.ComputeLocalToWorldTransform(time)
            if self.guides and (prim.IsA(UsdGeom.Camera) or prim.HasAPI(UsdLux.LightAPI)):
                painter.setPen(QPen(QColor("#f1d48a"), 1))
                center = matrix.ExtractTranslation()
                point = self.project(center)
                if point is not None:
                    painter.drawEllipse(point, 6, 6)
                    painter.drawText(point + QPointF(8, 0), prim.GetName())
                self.line3d(painter, center, matrix.Transform(Gf.Vec3d(0, 0, -self.camera.distance * .04)))
            if self.display not in ("Points", "Wire over Shaded") or not prim.IsA(UsdGeom.Mesh) or self.depth is None or not self.depth_current or self._overlay_budget <= 0:
                continue
            mesh = UsdGeom.Mesh(prim)
            if mesh.ComputeVisibility(time) == "invisible" or mesh.ComputePurpose() not in self.visible_purposes:
                continue
            points = mesh.GetPointsAttr().Get(time)
            if points is None or len(points) > 100000:
                continue
            world = np.c_[np.asarray(points, dtype=np.float64), np.ones(len(points))] @ np.asarray(matrix)
            painter.setPen(QPen(QColor('#dde4ed') if self.display == 'Points' else QColor('#20242b'), 1.5))
            if self.display == 'Points':
                self.depth_points(painter, world)
            else:
                indices = list(mesh.GetFaceVertexIndicesAttr().Get(time) or [])
                edges, offset = set(), 0
                for count in mesh.GetFaceVertexCountsAttr().Get(time) or []:
                    face = indices[offset:offset+count]
                    offset += count
                    edges.update(tuple(sorted((a, b))) for a, b in zip(face, face[1:]+face[:1]))
                if len(edges) > 10000:
                    continue
                clip = world @ np.asarray(self._view_projection)
                for a, b in edges:
                    if self._overlay_budget <= 0:
                        break
                    if a >= len(world) or b >= len(world) or clip[a,3] <= 0 or clip[b,3] <= 0:
                        continue
                    start, end = clip[a,:2]/clip[a,3], clip[b,:2]/clip[b,3]
                    count = min(2048, max(2, int(np.max(np.abs(end-start)*np.array([self.image.width(),self.image.height()]))/2)+1))
                    t = np.linspace(0, 1, count)[:,None]
                    # Perspective-correct points at uniform screen intervals.
                    values = ((1-t)*world[a]/clip[a,3]+t*world[b]/clip[b,3])/((1-t)/clip[a,3]+t/clip[b,3])
                    self.depth_points(painter, values)

    def depth_points(self, painter, world):
        count = min(len(world), getattr(self, '_overlay_budget', 100000))
        self._overlay_budget = getattr(self, '_overlay_budget', 100000) - count
        world = world[:count]
        if not len(world):
            return
        clip = world @ np.asarray(self._view_projection)
        front = (clip[:,3] > 1e-12) & (clip[:,2] >= -clip[:,3]) & (clip[:,2] <= clip[:,3])
        if not front.any():
            return
        world, clip = world[front], clip[front]
        ndc = clip[:,:2] / clip[:,3,None]
        uv = (ndc * np.array([1.,-1.]) + 1.) * .5
        inside = ((uv >= 0) & (uv < 1)).all(axis=1)
        world, uv = world[inside], uv[inside]
        if not len(world):
            return
        height, width = self.depth.shape
        xy = (uv * [width, height]).astype(int)
        camera = np.array(self._view_matrix.GetInverse().ExtractTranslation())
        distance = np.linalg.norm(world[:,:3]-camera, axis=1) * UsdGeom.GetStageMetersPerUnit(self.document.stage)
        visible = distance <= self.depth[xy[:,1],xy[:,0]] + np.maximum(.0001, distance * .003)
        rect = self.image_rect()
        for point in uv[visible]:
            painter.drawPoint(QPointF(rect.left()+point[0]*rect.width(), rect.top()+point[1]*rect.height()))

    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position()
        kind = "pick"
        if event.button() == Qt.MiddleButton:
            kind = "pan"
        elif event.modifiers() & Qt.AltModifier:
            kind = "dolly" if event.button() == Qt.RightButton else "orbit"
        elif event.button() != Qt.LeftButton:
            return
        world = self.selected_world()
        if kind == "pick" and world is not None:
            for axis, origin, end, size in self.handles:
                delta = end - origin
                length = delta.x() ** 2 + delta.y() ** 2
                if length < 1:
                    continue
                u = max(0, min(1, ((pos - origin).x() * delta.x() + (pos - origin).y() * delta.y()) / length))
                nearest = origin + delta * u
                if (pos - nearest).manhattanLength() < 12 and u > .2:
                    self.drag = dict(kind="transform", start=pos, last=pos, axis=axis, world=world,
                                     delta=delta, length=length, size=size)
                    return
        if kind != "pick" and self.scene_camera_path:
            if not self.begin_camera_navigation():
                return
        self.drag = dict(kind=kind, start=pos, last=pos,
                         additive=bool(event.modifiers() & Qt.ControlModifier))

    def mouseMoveEvent(self, event):
        if not self.drag:
            return
        pos = event.position()
        delta = pos - self.drag["last"]
        self.drag["last"] = pos
        kind = self.drag["kind"]
        if kind == "orbit":
            self.camera.orbit(delta.x(), delta.y())
        elif kind == "pan":
            self.camera.pan(delta.x(), delta.y(), self.width())
        elif kind == "dolly":
            self.camera.dolly(delta.y() * .01)
        elif kind == "transform":
            d = pos - self.drag["start"]
            axis_delta = self.drag["delta"]
            ratio = (d.x() * axis_delta.x() + d.y() * axis_delta.y()) / self.drag["length"]
            amount = ratio * self.drag["size"] if self.tool == "translate" else ratio * 90 if self.tool == "orient" else max(.01, 1 + ratio)
            self.preview_world = manipulated_world(self.drag["world"], self.tool, self.drag["axis"], amount, self.space)
            self.transformPreviewChanged.emit(dict(path=self.document.selection[0], before=rows(self.drag['world']),
                                                   matrix=rows(self.preview_world)))
        if kind in ("orbit", "pan", "dolly"):
            self.cameraChanged.emit()
        self.update()

    def mouseReleaseEvent(self, event):
        if not self.drag:
            return
        drag, self.drag = self.drag, None
        if drag["kind"] == "transform" and self.preview_world is not None:
            self.transformCommitted.emit(dict(path=self.document.selection[0], values={"matrix": rows(self.preview_world)},
                                              space="world", representation="matrix", frame=self.document.frame, time=self.edit_time))
        elif drag["kind"] == "pick":
            rect = self.image_rect()
            selection = QRectF(drag["start"], event.position()).normalized().intersected(rect)
            if selection.width() < 3 and selection.height() < 3:
                selection = QRectF(event.position().x(), event.position().y(), 1, 1).intersected(rect)
            if not selection.isEmpty():
                values = [(selection.left() - rect.left()) / rect.width(), (selection.top() - rect.top()) / rect.height(),
                          (selection.right() - rect.left()) / rect.width(), (selection.bottom() - rect.top()) / rect.height()]
                self.pickRequested.emit(values, drag["additive"])
        if self.camera_gesture is not None:
            self.finish_camera_navigation()
        self.preview_world = None
        self.update()

    def wheelEvent(self, event):
        if self.scene_camera_path and not self.begin_camera_navigation():
            return
        self.camera.dolly(-event.angleDelta().y() / 1200)
        self.cameraChanged.emit()
        if self.camera_gesture is not None:
            self.finish_camera_navigation()
        self.update()

    def begin_camera_navigation(self):
        prim = self.document.stage.GetPrimAtPath(self.scene_camera_path)
        if self.edit_camera and is_locked(prim):
            self.message = 'The selected camera transform is locked.'
            self.update()
            return False
        camera = self.render_camera()
        self.camera = ViewCamera.from_camera(camera, self.camera.distance, self.camera.up_axis)
        if self.edit_camera:
            self.camera_gesture = self.scene_camera_path
        else:
            self.scene_camera_path = ''
        return True

    def finish_camera_navigation(self):
        path, self.camera_gesture = self.camera_gesture, None
        camera = self.camera.camera(max(self.width(), 1) / max(self.height(), 1))
        self.cameraCommitted.emit(dict(path=path, values={'matrix': rows(self.camera.matrix())}, space='world',
            representation='matrix', frame=self.document.frame, time=self.edit_time,
            apertures=[camera.horizontalAperture, camera.verticalAperture] if self.camera.orthographic else None))

    def set_tool(self, tool):
        if tool == self.tool:
            return
        if self.drag and self.drag['kind'] == 'transform':
            self.drag = self.preview_world = None
            self.transformPreviewChanged.emit(None)
        self.tool = tool
        self.toolChanged.emit(tool)
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.drag and self.drag['kind'] == 'transform':
                self.transformPreviewChanged.emit(None)
            if self.camera_gesture is not None:
                self.camera_gesture = None
                self.cameraChanged.emit()
            self.drag = None
            self.preview_world = None
            self.update()
        elif event.key() == Qt.Key_F:
            self.frameRequested.emit(bool(event.modifiers() & Qt.ShiftModifier))
        elif event.key() in (Qt.Key_W, Qt.Key_E, Qt.Key_R) and event.modifiers() == Qt.NoModifier:
            self.set_tool({Qt.Key_W: "translate", Qt.Key_E: "orient", Qt.Key_R: "scale"}[event.key()])
        else:
            super().keyPressEvent(event)

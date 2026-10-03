"""Image-space handles using the same USD pose math as the Qt viewport."""

import math
import numpy as np
from PIL import Image, ImageDraw
from pxr import Gf, Usd, UsdGeom
from omnilab.usd.usd_transform_lock import is_locked
from omnilab.usd.usd_transform_pose import gizmo_axes, manipulated_world, rows
from omnilab.render.deltas import transform_deltas


class Gizmo:
    def __init__(self, owner):
        self.owner = owner
        self.handles = []
        self.drag = None
        self.preview = None
        self.raw = None
        self.tool = "translate"
        self.space = "world"
        self.time = "default"
        self.grid = False

    def selected_world(self):
        document = self.owner.document
        if not document.selection:
            return None
        prim = document.stage.GetPrimAtPath(document.selection[0])
        xform = UsdGeom.Xformable(prim)
        if (
            not xform
            or is_locked(prim)
            or prim.IsInstanceProxy()
            or prim.IsInPrototype()
        ):
            return None
        return xform.ComputeLocalToWorldTransform(Usd.TimeCode(document.frame))

    def present(self, event=None):
        if event:
            self.raw = (
                np.frombuffer(event["pixels"], np.uint8).reshape(event["shape"]).copy()
            )
        if self.raw is None:
            return
        self.handles = []
        height, width = self.raw.shape[:2]
        camera = self.owner.get_camera(self.owner.document.frame, width / height)
        view = camera.frustum.ComputeViewMatrix()
        vp = view * camera.frustum.ComputeProjectionMatrix()

        def project(point):
            if view.Transform(point)[2] >= 0:
                return None
            clip = vp.Transform(point)
            result = ((clip[0] + 1) * width * 0.5, (1 - clip[1]) * height * 0.5)
            return result if max(map(abs, result)) < 1e6 else None

        image = Image.fromarray(self.raw)
        draw = ImageDraw.Draw(image)
        if self.grid:
            step = 10 ** math.floor(
                math.log10(max(0.001, self.owner.camera.distance / 10))
            )
            for axis in range(2):
                for i in range(-10, 11):
                    a, b = [i * step, 0, -10 * step], [i * step, 0, 10 * step]
                    if axis:
                        a, b = [a[2], 0, a[0]], [b[2], 0, b[0]]
                    if self.owner.camera.up_axis == "Z":
                        a, b = [a[0], a[2], 0], [b[0], b[2], 0]
                    pa, pb = project(Gf.Vec3d(*a)), project(Gf.Vec3d(*b))
                    if pa and pb:
                        draw.line([pa, pb], fill=(105, 110, 115, 255), width=1)
        world = self.preview if self.preview is not None else self.selected_world()
        if world is not None:
            pivot = world.ExtractTranslation()
            origin = project(pivot)
            size = self.owner.camera.distance * 0.075
            for axis, vector in enumerate(gizmo_axes(world, self.space)):
                end = project(pivot + vector * size)
                if origin and end:
                    color = ["#ff6b68", "#80dc83", "#77a8ff"][axis]
                    draw.line([origin, end], fill=color, width=3)
                    draw.ellipse(
                        (end[0] - 5, end[1] - 5, end[0] + 5, end[1] + 5), fill=color
                    )
                    draw.text((end[0] + 7, end[1] - 6), "XYZ"[axis], fill=color)
                    self.handles.append((axis, origin, end, size))
        self.owner.image.set_pixels(np.asarray(image))

    def down(self, x, y):
        uv = self.owner.image.position(x, y)
        world = self.selected_world()
        if not uv or world is None:
            return False
        height, width = self.raw.shape[:2]
        p = np.array((uv[0] * width, uv[1] * height))
        for axis, a, b, size in self.handles:
            delta = np.array(b) - a
            length = float(delta @ delta)
            if length < 1:
                continue
            u = max(0, min(1, float((p - a) @ delta) / length))
            if u > 0.2 and np.linalg.norm(p - (np.array(a) + u * delta)) < 10:
                self.drag = dict(
                    start=p,
                    delta=delta,
                    length=length,
                    axis=axis,
                    size=size,
                    world=world,
                    path=self.owner.document.selection[0],
                    revision=self.owner.document.revision,
                )
                return True
        return False

    def move(self, x, y):
        if not self.drag:
            return
        uv = self.owner.image.position(x, y)
        if not uv:
            return
        d = self.drag
        if d["revision"] != self.owner.document.revision:
            self.cancel()
            return
        h, w = self.raw.shape[:2]
        delta = np.array((uv[0] * w, uv[1] * h)) - d["start"]
        ratio = float(delta @ d["delta"]) / d["length"]
        amount = (
            ratio * d["size"]
            if self.tool == "translate"
            else ratio * 90
            if self.tool == "orient"
            else max(0.01, 1 + ratio)
        )
        self.preview = manipulated_world(
            d["world"], self.tool, d["axis"], amount, self.space
        )
        self.owner.renderer.deltas = transform_deltas(
            self.owner.document, d["path"], d["world"], self.preview
        )
        self.owner.renderer.invalidate(camera_only=True)
        self.present()

    def up(self):
        if not self.drag:
            return False
        drag, self.drag = self.drag, None
        preview, self.preview = self.preview, None
        if preview is not None:
            self.owner.execute(
                "set_transform",
                dict(
                    path=drag["path"],
                    values={"matrix": rows(preview)},
                    space="world",
                    representation="matrix",
                    frame=self.owner.document.frame,
                    time=self.time,
                ),
            )
        else:
            self.owner.renderer.invalidate()
        return True

    def cancel(self):
        self.drag = self.preview = None
        self.owner.renderer.invalidate()
        self.present()

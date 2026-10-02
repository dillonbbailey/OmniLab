"""Free camera math in USD stage units; camera state is view-only."""
from dataclasses import dataclass, field, asdict
import math

from pxr import Gf, Usd, UsdGeom


@dataclass
class ViewCamera:
    target: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    distance: float = 10.0
    yaw: float = 25.0
    pitch: float = 18.0
    orthographic: bool = False
    up_axis: str = "Y"
    focal_length: float = 50.
    horizontal_aperture: float = 36.
    roll: float = 0.
    horizontal_offset: float = 0.
    vertical_offset: float = 0.
    clipping: list | None = None

    def matrix(self):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        offset = Gf.Vec3d(math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))
        up = Gf.Vec3d(0, 1, 0)
        if self.up_axis == "Z":
            offset = Gf.Vec3d(offset[0], -offset[2], offset[1])
            up = Gf.Vec3d(0, 0, 1)
        target = Gf.Vec3d(*self.target)
        base = Gf.Matrix4d().SetLookAt(target + offset * self.distance, target, up).GetInverse()
        return Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), self.roll)) * base

    def camera(self, aspect):
        camera = Gf.Camera()
        camera.transform = self.matrix()
        camera.horizontalAperture = self.horizontal_aperture
        camera.verticalAperture = self.horizontal_aperture / max(aspect, .01)
        camera.focalLength = self.focal_length
        camera.horizontalApertureOffset = self.horizontal_offset
        camera.verticalApertureOffset = self.vertical_offset
        camera.clippingRange = Gf.Range1f(*self.clipping) if self.clipping else Gf.Range1f(max(.001, self.distance / 10000), max(1000, self.distance * 100))
        if self.orthographic:
            camera.projection = Gf.Camera.Orthographic
            camera.horizontalAperture = self.distance * 7.2
            camera.verticalAperture = camera.horizontalAperture / max(aspect, .01)
        return camera

    def frame(self, bounds):
        if bounds.IsEmpty():
            return
        self.target = list(bounds.GetMidpoint())
        self.distance = max(.01, bounds.GetSize().GetLength() * 2.0)

    def orbit(self, dx, dy):
        self.yaw -= dx * .35
        self.pitch = max(-89.5, min(89.5, self.pitch + dy * .35))

    def pan(self, dx, dy, width):
        matrix = self.matrix()
        scale = self.distance * .72 / max(width, 1)
        offset = (Gf.Vec3d(*matrix[0][:3]) * -dx + Gf.Vec3d(*matrix[1][:3]) * dy) * scale
        self.target = list(Gf.Vec3d(*self.target) + offset)

    def dolly(self, amount):
        self.distance = max(.001, min(1e12, self.distance * math.exp(max(-5, min(5, amount)))))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})

    @classmethod
    def from_camera(cls, camera, distance=10., up_axis='Y'):
        orthographic = camera.projection == Gf.Camera.Orthographic
        if orthographic:
            distance = camera.horizontalAperture / 7.2
        offset = Gf.Vec3d(*camera.transform[2][:3]).GetNormalized()
        components = (offset[0], offset[2], -offset[1]) if up_axis == 'Z' else offset
        result = cls(target=list(camera.transform.ExtractTranslation()-offset*distance), distance=distance,
            yaw=math.degrees(math.atan2(components[0], components[2])),
            pitch=math.degrees(math.asin(max(-1, min(1, components[1])))), orthographic=orthographic,
            up_axis=up_axis, focal_length=camera.focalLength, horizontal_aperture=camera.horizontalAperture,
            horizontal_offset=camera.horizontalApertureOffset, vertical_offset=camera.verticalApertureOffset,
            clipping=[camera.clippingRange.min, camera.clippingRange.max])
        local = camera.transform * result.matrix().GetInverse()
        result.roll = math.degrees(math.atan2(local[0][1], local[0][0]))
        return result


def scene_camera(stage, path, frame, aspect):
    camera = UsdGeom.Camera.Get(stage, path)
    if not camera:
        raise ValueError("The selected scene camera no longer exists.")
    result = camera.GetCamera(Usd.TimeCode(frame))
    result.verticalAperture = result.horizontalAperture / max(aspect, .01)
    return result


def camera_payload(camera):
    return dict(matrix=[list(row) for row in camera.transform],
                horizontalAperture=camera.horizontalAperture,
                verticalAperture=camera.verticalAperture, focalLength=camera.focalLength,
                horizontalApertureOffset=camera.horizontalApertureOffset, verticalApertureOffset=camera.verticalApertureOffset,
                clippingRange=[camera.clippingRange.min, camera.clippingRange.max],
                projection="orthographic" if camera.projection == Gf.Camera.Orthographic else "perspective")

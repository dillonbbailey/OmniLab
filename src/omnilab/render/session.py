"""Bounded interactive renderer scheduling, independent of either UI toolkit."""

from pathlib import Path
import tempfile

from omnilab.core.camera import camera_payload
from .process import RendererProcess
from .snapshot import publish, retire_snapshots


class InteractiveSession:
    def __init__(
        self,
        scene,
        on_frame,
        on_status=lambda text: None,
        on_pick=lambda paths, additive: None,
        profile="viewport",
    ):
        self.scene = scene  # returns (Document, Gf.Camera)
        self.on_frame, self.on_status, self.on_pick = on_frame, on_status, on_pick
        self.profile = profile
        self.scratch = tempfile.TemporaryDirectory(prefix="omnilab-interactive-")
        self.bridge = RendererProcess(Path(self.scratch.name) / "runtime")
        self.enabled = self.ready = False
        self.request = 0
        self.submitted = self.presented = -1
        self.inflight = None
        self.floor = 0
        self.structural = True
        self.snapshot = None
        self.deltas = {}
        self.resolution = (800, 500)
        self.mode = "RealTimePathTracing"
        self.samples = 16
        self.wireframe = False
        self.wireframe_mode = "shaded"
        self.frames = self.publications = 0
        self.error = ""

    def start(self):
        document, _ = self.scene()
        self.bridge.start(document.view.get("renderer_config", {}))
        self.enabled, self.ready, self.inflight = True, False, None
        self.error = ""
        self.invalidate()

    def invalidate(self, camera_only=False, discard=False):
        self.request += 1
        if not camera_only:
            self.structural = True
            self.deltas = {}
        if not camera_only or discard:
            self.floor = self.request

    def tick(self):
        for event in self.bridge.poll():
            kind = event["type"]
            if kind == "ready":
                self.ready = True
            elif kind == "loaded":
                retire_snapshots(self.scratch.name, event["path"])
            elif kind == "frame":
                request = event["request"]
                if request == self.inflight:
                    self.inflight = None
                if request >= max(self.floor, self.presented):
                    self.presented = request
                    self.frames += 1
                    self.on_frame(event)
                    if event.get("hits") is not None and request == self.request:
                        self.on_pick(event["hits"], event.get("additive", False))
                self.bridge.send(dict(type="ack"))
            elif kind == "pick":
                if event.get("request") == self.request == self.presented:
                    self.on_pick(event.get("hits", []), event.get("additive", False))
            elif kind in ("error", "stopped"):
                self.error = event.get("text", "Renderer stopped. Restart to recover.")
                self.enabled = self.ready = False
                self.inflight = None
                self.on_status(self.error)
            elif kind == "status":
                self.on_status(event.get("text", ""))
        if (
            not self.enabled
            or not self.ready
            or self.inflight is not None
            or self.submitted == self.request
        ):
            return
        try:
            document, camera = self.scene()
            if self.structural:
                self.snapshot = publish(
                    document,
                    Path(self.scratch.name) / str(self.request),
                    camera,
                    self.resolution,
                    self.mode,
                    self.samples,
                    wireframe=self.wireframe,
                    wireframe_mode=self.wireframe_mode,
                    profile=self.profile,
                )
                self.structural = False
                self.publications += 1
            self.bridge.send(
                dict(
                    type="view",
                    request=self.request,
                    snapshot=self.snapshot,
                    camera=camera_payload(camera),
                    deltas=dict(self.deltas),
                    selection=list(document.selection),
                )
            )
            self.inflight = self.submitted = self.request
        except Exception as error:
            self.error = str(error)
            self.stop()
            self.on_status(self.error + " Restart after correcting the scene.")

    def pick(self, rect, additive=False):
        if self.enabled and self.presented == self.request and self.inflight is None:
            self.bridge.send(
                dict(type="pick", request=self.request, rect=rect, additive=additive)
            )

    def stop(self):
        self.enabled = self.ready = False
        self.inflight = None
        self.bridge.stop()

    def close(self):
        self.stop()
        self.scratch.cleanup()

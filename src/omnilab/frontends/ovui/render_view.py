"""Native ovUI final-job controls and channel-aware EXR presentation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import omni.ui as ui
from omnilab.render.jobs import JobOptions, RenderJob, prepare_job, frame_range
from omnilab.render.exr_image import inspect_exr, display_exr
from .widgets import ImageSurface, field, combo, combo_index, button


class RenderView:
    def __init__(self, owner):
        self.owner = owner
        self.job = None
        self.image = ImageSurface()
        self.scratch = tempfile.TemporaryDirectory(prefix="omnilab-render-view-")
        self.path = ""
        self.metadata = None
        self.view = 0
        self.exposure = 0.0
        self.completed = []
        self.resume_view = self.resume_preview = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="exr-display")
        self.future = None
        self.display_generation = 0
        self.pending_display = False
        self.window = owner.window("RenderView", self.build, 1100, 750)
        self.window.setPosition(120, 90)
        self.state = dict(
            output=str(Path.home() / "render.exr"),
            width=1280,
            height=720,
            samples=64,
            warmup=16,
            start=owner.document.frame,
            end=owner.document.frame,
            step=1,
            region="",
            aovs="HdrColor",
            mode="PathTracing",
        )

    @property
    def active(self):
        return bool(self.job and self.job.active)

    def show(self):
        self.remember_options()
        self.window.visible = True
        self.window.frame.rebuild()

    def build(self):
        with ui.VStack(spacing=4):
            with ui.HStack(height=28):
                self.output = field(self.state["output"])
                button("Output…", self.choose_output, self.owner, width=90)
                button(
                    "Open EXR",
                    lambda: self.owner.file_dialog("Open EXR", self.open_image),
                    self.owner,
                    width=90,
                )
                button("Render", self.start, self.owner, width=70)
                button("Cancel", self.cancel, self.owner, width=70)
            with ui.HStack(height=26, spacing=4):
                self.models = {}
                for name in ("width", "height", "samples", "start", "end", "step"):
                    ui.Label(name, width=48)
                    self.models[name] = field(self.state[name], width=70)
                self.mode = combo(
                    ["PathTracing", "RealTimePathTracing"],
                    int(self.state["mode"] == "RealTimePathTracing"),
                )
            with ui.HStack(height=26, spacing=4):
                ui.Label("AOVs", width=40)
                self.aovs = field(self.state["aovs"], width=245)
                ui.Label("Region x,y,w,h", width=100)
                self.region = field(self.state["region"], width=155)
                ui.Label("RTPT warmup", width=95)
                self.warmup = field(self.state["warmup"], width=50)
                button("Job / logs", self.job_info, self.owner, width=85)
            self.image.build()
            with ui.HStack(height=27):
                views = (
                    [v["label"] for v in self.metadata["views"]]
                    if self.metadata
                    else ["No image"]
                )
                combo(views, min(self.view, len(views) - 1), self.select_view)
                ui.Label("Exposure", width=70)
                exposure = ui.SimpleFloatModel(self.exposure)
                ui.FloatField(model=exposure, width=70)
                exposure.add_end_edit_fn(lambda m: self.set_exposure(m.as_float))
                if self.completed:
                    combo(
                        [Path(p).name for p in self.completed],
                        len(self.completed) - 1,
                        lambda i: self.open_image(self.completed[i]),
                    )
            ui.Label(
                "Linear EXR source retained · display conversion only · region merges preserve outside pixels",
                height=23,
            )

    def choose_output(self):
        self.owner.file_dialog(
            "Output EXR / {frame} sequence",
            lambda p: self.output.set_value(p),
            True,
            self.output.as_string,
        )

    def start(self):
        if self.active:
            raise ValueError("A final job is already running.")
        values = {name: model.as_string for name, model in self.models.items()}
        options = JobOptions(
            output=self.output.as_string,
            resolution=(int(values["width"]), int(values["height"])),
            mode=["PathTracing", "RealTimePathTracing"][combo_index(self.mode)],
            samples=int(values["samples"]),
            warmup=int(self.warmup.as_string),
            aovs=tuple(n.strip() for n in self.aovs.as_string.split(",")),
            frames=tuple(frame_range(values["start"], values["end"], values["step"])),
            region=tuple(map(int, self.region.as_string.split(",")))
            if self.region.as_string.strip()
            else None,
        )
        self.state.update(
            values,
            output=options.output,
            mode=options.mode,
            warmup=options.warmup,
            aovs=self.aovs.as_string,
            region=self.region.as_string,
        )
        aspect = options.resolution[0] / options.resolution[1]
        job = prepare_job(
            self.owner.document,
            lambda frame: self.owner.get_camera(frame, aspect),
            options,
            self.scratch.name,
        )
        self.start_data(job)

    def start_data(self, data):
        if self.active:
            raise ValueError("A final job is already running.")
        self.resume_view, self.resume_preview = (
            self.owner.renderer.enabled,
            self.owner.materials.preview.enabled,
        )
        self.owner.renderer.stop()
        self.owner.materials.preview.stop()
        self.owner.playing = False
        self.job = RenderJob(data)
        try:
            self.job.start()
        except Exception:
            self.resume()
            raise
        self.window.visible = True
        self.owner.set_status("Final render started.")

    def resume(self):
        if self.resume_view:
            self.owner.safe(self.owner.renderer.start)
        if self.resume_preview and self.owner.materials.graph:
            self.owner.safe(self.owner.materials.preview.start)
        self.resume_view = self.resume_preview = False

    def cancel(self):
        if self.active:
            self.job.cancel()
            self.resume()
            self.owner.set_status(
                "Final render cancelled; last completed image retained."
            )

    def job_info(self):
        if self.job:
            self.owner.form(
                "Job / logs",
                {
                    "directory": self.job.data["directory"],
                    "state": self.job.data["state"],
                },
                lambda v: None,
            )

    def open_image(self, path):
        self.remember_options()
        self.metadata = inspect_exr(path)
        self.path, self.view = path, 0
        self.request_display()
        self.window.frame.rebuild()

    def remember_options(self):
        if not hasattr(self, "output"):
            return
        self.state.update(
            {name: model.as_string for name, model in self.models.items()}
        )
        self.state.update(
            output=self.output.as_string,
            aovs=self.aovs.as_string,
            region=self.region.as_string,
            warmup=self.warmup.as_string,
            mode=["PathTracing", "RealTimePathTracing"][combo_index(self.mode)],
        )

    def select_view(self, index):
        self.view = index
        self.request_display()

    def set_exposure(self, value):
        self.exposure = value
        self.request_display()

    def request_display(self):
        self.display_generation += 1
        self.pending_display = bool(self.path)

    def tick(self):
        if self.active:
            for event in self.job.poll():
                if event["type"] == "frame":
                    path = event["path"]
                    self.completed.append(path)
                    self.owner.safe(lambda: self.open_image(path))
                if event.get("text"):
                    self.owner.set_status(event["text"])
            if not self.active:
                self.resume()
                self.owner.set_status("Final render " + self.job.data["state"])
        if self.future and self.future.done():
            future, self.future = self.future, None

            def finish():
                generation, pixels = future.result()
                if generation == self.display_generation:
                    self.image.set_pixels(pixels)

            self.owner.safe(finish)
        if self.pending_display and not self.future:
            self.pending_display = False
            path, view, exposure, generation = (
                self.path,
                dict(self.metadata["views"][self.view]),
                self.exposure,
                self.display_generation,
            )
            output = Path(self.scratch.name) / "display.png"

            def convert():
                import numpy as np
                from PIL import Image

                display_exr(path, output, view, exposure=exposure)
                return generation, np.array(Image.open(output).convert("RGBA"))

            self.future = self.pool.submit(convert)

    def close(self):
        if self.active:
            self.job.cancel()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.scratch.cleanup()

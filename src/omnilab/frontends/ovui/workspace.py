"""Native ovUI composition root over OmniLab's authoritative USD document."""

import json
from pathlib import Path
import time
import traceback
import omni.ui as ui
from pxr import UsdGeom
from ovui_widgets.common import scheduler
from ovui_widgets.common.selection import SelectionBus
from .stage_window import OmniLabStageWindow
from .property_window import OmniLabPropertyWindow
from ovui_widgets.content.file_importer import FileImporterHelper
from omnilab.core.document import Document
from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera, scene_camera
from omnilab.render.session import InteractiveSession
from .adapters import DocumentStageAdapter, DocumentPropertyAdapter
from .widgets import ImageSurface, field, combo, button, track_edit, text_editing
from .value_menu import copy_value, close_clipboard
from omnilab.usd.property_actions import (
    prim_text,
    bound_material_path,
    prims_with_bound_material,
)


class Workspace:
    def __init__(self, args, appearance=None):
        self.args, self.failure = args, None
        self.exiting = False
        self.callbacks = []
        self.windows = []
        self.dialogs = []
        self.document = (
            Document.open(args.scene)
            if args.scene
            else demo_document()
            if args.demo
            else Document()
        )
        self.camera = ViewCamera.from_dict(self.document.view.get("camera", {}))
        self.camera.up_axis = str(UsdGeom.GetStageUpAxis(self.document.stage))
        if "camera" not in self.document.view:
            self.camera.frame(self.document.bounds())
        self.camera_path = ""
        self.drag = None
        self.playing = False
        self.last_play = time.monotonic()
        self.status = ui.SimpleStringModel("Ready")
        self.image = ImageSurface()
        from .gizmo import Gizmo

        self.gizmo = Gizmo(self)
        self.renderer = InteractiveSession(
            self.scene, self.on_frame, self.set_status, self.on_pick
        )
        self.restore_view()
        self.picker = FileImporterHelper()
        self.selection_bus = SelectionBus()
        scheduler.set_call_later(self.call_later)
        self.selection_sub = self.selection_bus.subscribe(self.selection_changed)
        self.stage_adapter = DocumentStageAdapter(
            self.document, self.changed, self.call_later
        )
        self.dock = ui.MainWindow()
        self.stage_window = OmniLabStageWindow(
            self.stage_adapter,
            self.selection_bus,
            lambda p, x, y: self.safe(lambda: self.prim_menu(p, x, y)),
        )
        self.property_window = OmniLabPropertyWindow(self.safe)
        self.property_window.set_property_adapter_factory(
            lambda paths: DocumentPropertyAdapter(self.document, paths, self.changed)
        )
        self.property_window.set_stage_adapter(self.stage_adapter)
        self.viewport = self.window("Viewport", self.build_viewport, 800, 600)
        self.layers = self.window("Layers", self.build_layers, 300, 260)
        from .material_editor import MaterialEditor
        from .render_view import RenderView
        from .panels import ConsolePanel, SettingsPanel
        from .appearance import Appearance
        from .appearance_panel import AppearancePanel

        self.materials = MaterialEditor(self)
        self.render_view = RenderView(self)
        self.console = ConsolePanel(self)
        self.settings = SettingsPanel(self)
        self.appearance = AppearancePanel(self, appearance or Appearance.load())
        for panel in (
            self.materials,
            self.render_view,
            self.console,
            self.settings,
            self.appearance,
        ):
            panel.window.visible = False
        self.toolbar = self.window("OmniLab", self.build_toolbar, 1000, 95)
        self.windows.extend([self.stage_window.window, self.property_window.window])
        # These form the permanent workspace; optional panels can still close.
        for window in (
            self.toolbar,
            self.viewport,
            self.layers,
            self.stage_window.window,
            self.property_window.window,
        ):
            window.flags |= ui.WINDOW_FLAGS_NO_CLOSE
        for window in self.windows:
            window.set_key_pressed_fn(self.key)
        self.selection_bus.publish(self.document.selection, source="document")
        self.inspector = None
        if args.inspect:
            import ovuiinspect

            ovuiinspect.attach_application(self)
            self.inspector = ovuiinspect

    def window(self, title, build, width=800, height=500):
        win = ui.Window(
            title,
            dockPreference=ui.DockPreference.MAIN,
            width=width,
            height=height,
            raster_policy=ui.RasterPolicy.NEVER,
        )
        win.frame.set_build_fn(build)
        self.windows.append(win)
        return win

    def call_later(self, delay, callback):
        handle = scheduler.CallbackHandle(time.monotonic() + delay, callback)
        self.callbacks.append(handle)
        return handle

    def safe(self, callback):
        try:
            return callback()
        except Exception as error:
            self.set_status(str(error))
            traceback.print_exc()

    def set_status(self, text):
        self.status.set_value(str(text)[-1500:])

    def build_toolbar(self):
        with ui.VStack(spacing=4):
            with ui.HStack(height=28, spacing=4):
                for name, fn in [
                    ("New", lambda: self.replace_guard(Document)),
                    ("Demo", lambda: self.replace_guard(demo_document)),
                    ("Open", self.open_dialog),
                    ("Save", self.save),
                    ("Save As", lambda: self.save(True)),
                    ("Undo", lambda: self.execute("restore")),
                    ("Redo", lambda: self.execute("restore", redo=True)),
                    ("Materials", self.materials.show),
                    ("RenderView", self.render_view.show),
                    ("Python", self.console.show),
                    ("RTX settings", self.settings.show),
                    ("Appearance", self.appearance.show),
                ]:
                    button(name, fn, self)
            ui.StringField(model=self.status, read_only=True, height=25)

    def build_viewport(self):
        with ui.VStack(spacing=3):
            with ui.HStack(height=26, spacing=4):
                self.mode = combo(
                    ["RealTimePathTracing", "PathTracing"],
                    int(self.renderer.mode == "PathTracing"),
                    changed=self.set_mode,
                )
                combo(
                    ["Shaded", "Wire shaded", "Wire unlit"],
                    (2 if self.renderer.wireframe_mode == "unlit" else 1)
                    if self.renderer.wireframe
                    else 0,
                    changed=self.set_wire,
                )
                button("Start / restart", self.start_renderer, self)
                button("Stop", self.renderer.stop, self)
                button("Frame", self.frame_selected, self, width=55)
                button("Ortho", self.orthographic, self, width=55)
            with ui.HStack(height=24, spacing=4):
                ui.Label("Camera", width=55)
                cameras = ["Free"] + [
                    str(p.GetPath())
                    for p in self.document.stage.Traverse()
                    if p.IsA(UsdGeom.Camera)
                ]
                combo(
                    cameras,
                    cameras.index(self.camera_path)
                    if self.camera_path in cameras
                    else 0,
                    changed=lambda index: self.choose_camera(cameras[index]),
                )
                self.frame_model = track_edit(ui.SimpleFloatModel(self.document.frame))
                ui.FloatField(model=self.frame_model, width=95)
                self.frame_model.add_end_edit_fn(lambda m: self.set_frame(m.as_float))
                button("Play / pause", self.play, self, width=100)
            with ui.HStack(height=26, spacing=4):
                combo(
                    ["Move", "Rotate", "Scale"],
                    changed=lambda i: setattr(
                        self.gizmo, "tool", ["translate", "orient", "scale"][i]
                    ),
                )
                combo(
                    ["World", "Local"],
                    changed=lambda i: setattr(
                        self.gizmo, "space", ["world", "local"][i]
                    ),
                )
                combo(
                    ["Default value", "Time sample"],
                    changed=lambda i: setattr(
                        self.gizmo, "time", ["default", "frame"][i]
                    ),
                )
                button("Grid", self.toggle_grid, self, width=55)
                button("Lock", self.lock_transform, self, width=55)
                button("Unlock", lambda: self.lock_transform(False), self, width=60)
            self.image.build(
                opaque_for_mouse_events=True,
                mouse_pressed_fn=self.mouse_down,
                mouse_moved_fn=self.mouse_move,
                mouse_released_fn=self.mouse_up,
                mouse_wheel_fn=lambda x, y, mods: self.navigate("dolly", -y * 0.08, 0),
            )
            ui.Label(
                "Alt + left: orbit · middle: pan · wheel: dolly · click / drag: select · F: frame",
                height=20,
            )

    def scene(self):
        aspect = self.renderer.resolution[0] / self.renderer.resolution[1]
        return self.document, self.get_camera(self.document.frame, aspect)

    def get_camera(self, frame, aspect):
        return (
            scene_camera(self.document.stage, self.camera_path, frame, aspect)
            if self.camera_path
            else self.camera.camera(aspect)
        )

    def start_renderer(self):
        if self.render_view.active:
            raise ValueError(
                "Wait for or cancel the final render before restarting the viewport."
            )
        self.renderer.start()

    def set_mode(self, index):
        self.renderer.mode = ["RealTimePathTracing", "PathTracing"][index]
        self.document.view.setdefault("viewport", {})["mode"] = self.renderer.mode
        self.changed()

    def set_wire(self, index):
        self.renderer.wireframe = index != 0
        self.renderer.wireframe_mode = "unlit" if index == 2 else "shaded"
        self.document.view.setdefault("viewport", {})["display"] = [
            "Shaded",
            "Shaded Wireframe",
            "Unlit Wireframe",
        ][index]
        self.changed()

    def choose_camera(self, path):
        self.camera_path = "" if path == "Free" else path
        self.document.view["scene_camera"] = self.camera_path
        self.renderer.invalidate(camera_only=True)

    def toggle_grid(self):
        self.gizmo.grid = not self.gizmo.grid
        self.gizmo.present()

    def lock_transform(self, enabled=True):
        for path in list(self.document.selection):
            self.execute("set_transform_lock", path, enabled)

    def orthographic(self):
        self.camera_path = ""
        self.camera.orthographic = not self.camera.orthographic
        self.renderer.invalidate(camera_only=True)

    def set_frame(self, value):
        self.document.frame = value
        self.changed()

    def play(self):
        self.playing = not self.playing
        self.last_play = time.monotonic()

    def frame_selected(self):
        self.camera_path = ""
        self.camera.frame(self.document.bounds(self.document.selection))
        self.renderer.invalidate(camera_only=True)

    def navigate(self, kind, dx, dy):
        if self.camera_path:
            self.set_status("Scene camera is locked. Select Free to navigate.")
            return
        if kind == "orbit":
            self.camera.orbit(dx, dy)
        elif kind == "pan":
            self.camera.pan(dx, dy, self.image.widget.computed_width)
        else:
            self.camera.dolly(dx)
        self.document.view["camera"] = self.camera.to_dict()
        self.renderer.invalidate(camera_only=True)

    def mouse_down(self, x, y, button_, modifiers):
        if button_ == 0 and not modifiers & 4 and self.gizmo.down(x, y):
            return
        self.drag = dict(start=(x, y), last=(x, y), button=button_, modifiers=modifiers)

    def mouse_move(self, x, y, modifiers, buttons):
        if self.gizmo.drag:
            self.safe(lambda: self.gizmo.move(x, y))
            return
        if not self.drag:
            return
        old = self.drag["last"]
        dx, dy = x - old[0], y - old[1]
        self.drag["last"] = (x, y)
        if self.drag["button"] == 2:
            self.navigate("pan", dx, dy)
        elif self.drag["modifiers"] & 4:
            self.navigate("orbit", dx, dy)

    def mouse_up(self, x, y, button_, modifiers):
        if self.gizmo.drag:
            self.safe(self.gizmo.up)
            return
        drag, self.drag = self.drag, None
        if not drag or drag["button"] != 0 or drag["modifiers"] & 4:
            return
        a, b = self.image.position(*drag["start"]), self.image.position(x, y)
        if a and b:
            self.renderer.pick(
                (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    min(1, max(a[0], b[0]) + 1 / self.renderer.resolution[0]),
                    min(1, max(a[1], b[1]) + 1 / self.renderer.resolution[1]),
                ),
                bool(modifiers & 3),
            )

    def on_frame(self, event):
        self.gizmo.present(event)
        self.set_status(
            f"{self.renderer.mode} · {event.get('milliseconds', 0):.1f} ms · frame {self.document.frame:g}"
        )

    def on_pick(self, paths, additive):
        paths = [hit["path"] for hit in paths]
        self.selection_bus.publish(
            list(dict.fromkeys((self.document.selection if additive else []) + paths)),
            source="viewport",
        )

    def selection_changed(self, event):
        paths = [item.path for item in event.snapshot.items]
        self.document.select(paths)
        self.property_window.set_selection(self.document.selection)
        self.renderer.invalidate(camera_only=True, discard=True)

    def execute(self, name, *args, **kwargs):
        result = self.document.command(name, *args, **kwargs)
        self.changed()
        self.selection_bus.publish(self.document.selection, source="document")
        return result

    def changed(self):
        self.renderer.invalidate()
        if hasattr(self, "materials"):
            self.materials.refresh()
        if hasattr(self, "layers"):
            self.layers.frame.rebuild()
        self.set_status(
            ("Modified · " if self.document.dirty else "")
            + (self.document.path or "Untitled")
        )

    def build_layers(self):
        with ui.VStack(spacing=4):
            with ui.HStack(height=26):
                button("Add prim", self.add_prim_dialog, self)
                button("Duplicate", self.duplicate_menu, self)
                button("Delete", self.delete, self)
            with ui.ScrollingFrame():
                with ui.VStack(height=0, spacing=4):
                    for layer in self.document.stage.GetLayerStack():
                        with ui.HStack(height=25):
                            active = layer == self.document.edits.layer
                            button(
                                ("● " if active else "") + layer.GetDisplayName(),
                                lambda l=layer: self.set_target(l),
                                self,
                                name="layer_edit_target" if active else "",
                            )
                            if layer not in (
                                self.document.stage.GetRootLayer(),
                                self.document.stage.GetSessionLayer(),
                            ):
                                button(
                                    "Mute",
                                    lambda l=layer: self.execute(
                                        "set_layer_muted", l.identifier, True
                                    ),
                                    self,
                                    width=48,
                                )
                    for identifier in self.document.stage.GetMutedLayers():
                        button(
                            "Unmute " + Path(identifier).name,
                            lambda i=identifier: self.execute(
                                "set_layer_muted", i, False
                            ),
                            self,
                            name="layer_muted",
                        )
            with ui.HStack(height=26):
                button("New layer", self.new_layer, self)
                button("USD commands", self.command_dialog, self)

    def set_target(self, layer):
        self.document.edits.set_edit_target(layer.identifier)
        self.layers.frame.rebuild()
        self.property_window.set_selection(self.document.selection)

    def new_layer(self):
        self.form(
            "New sublayer",
            {"name": "edits.usda"},
            lambda values: self.execute(
                "create_sublayer",
                dict(
                    identifier=self.document.edits.layer.identifier,
                    storage="memory",
                    name=values["name"],
                ),
            ),
        )

    def duplicate(self, mode="copy"):
        for path in list(self.document.selection):
            self.execute("duplicate_prim", path, mode)

    def duplicate_menu(self):
        self.active_prim_menu = ui.Menu("Duplicate")
        with self.active_prim_menu:
            ui.MenuItem("As New Prim", triggered_fn=lambda: self.safe(self.duplicate))
            ui.MenuItem(
                "As Instance",
                triggered_fn=lambda: self.safe(lambda: self.duplicate("instance")),
            )
        self.active_prim_menu.show()

    def prim_menu(self, path, x, y):
        prim = self.document.stage.GetPrimAtPath(path)
        if not prim:
            return
        self.selection_bus.publish([path], source="context_menu")
        menu = ui.Menu("Prim")
        with menu:
            with ui.Menu("Duplicate"):
                ui.MenuItem(
                    "As New Prim", triggered_fn=lambda: self.safe(self.duplicate)
                )
                ui.MenuItem(
                    "As Instance",
                    triggered_fn=lambda: self.safe(lambda: self.duplicate("instance")),
                )
            if bound_material_path(prim):
                ui.MenuItem(
                    "Select prims with bound material",
                    triggered_fn=lambda: self.safe(
                        lambda: self.selection_bus.publish(
                            prims_with_bound_material(prim), source="material"
                        )
                    ),
                )
            with ui.Menu("Copy Prim"):
                for part in ("Name", "Path", "Type", "Properties"):
                    ui.MenuItem(
                        part,
                        triggered_fn=lambda p=part: self.safe(
                            lambda: copy_value(prim_text(prim, p, self.document.frame))
                        ),
                    )
        self.active_prim_menu = menu
        menu.show_at(x, y)

    def delete(self):
        for path in sorted(self.document.selection, key=len, reverse=True):
            self.execute("remove_prim", path)

    def add_prim_dialog(self):
        self.form(
            "Add prim",
            dict(
                parent=self.document.selection[0]
                if self.document.selection
                else "/World",
                name="Cube",
                kind="Cube",
            ),
            lambda v: self.execute("add_prim", v["parent"], v["name"], v["kind"]),
        )

    def command_dialog(self):
        self.form(
            "Document command",
            dict(
                command="set_transform",
                args='[{"path":"/World/Cube","values":{"translate":[0,1,0]},"space":"local","representation":"trs","time":"default"}]',
            ),
            lambda v: self.execute(v["command"], *json.loads(v["args"])),
        )

    def form(self, title, values, accept):
        win = ui.Window(
            title,
            width=720,
            height=max(180, 80 + len(values) * 38),
            flags=ui.WINDOW_FLAGS_MODAL | ui.WINDOW_FLAGS_NO_DOCKING,
        )
        self.dialogs.append(win)
        models = {}
        with win.frame:
            with ui.VStack(spacing=6):
                for name, value in values.items():
                    with ui.HStack(height=28):
                        ui.Label(name, width=130)
                        models[name] = field(value)

                def apply():
                    accept({name: model.as_string for name, model in models.items()})
                    win.visible = False

                with ui.HStack(height=30):
                    button("Apply", apply, self)
                    ui.Button(
                        "Cancel", clicked_fn=lambda: setattr(win, "visible", False)
                    )
        return win

    def file_dialog(self, title, callback, save=False, filename=""):
        self.picker.show(
            title=title,
            import_button_label="Save" if save else "Open",
            file_extension_types=[(".*", "All files")],
            should_validate=not save,
            filename_url=filename or str(Path.home()),
            import_handler=lambda name, directory, selected: self.safe(
                lambda: callback(str(Path(directory) / name))
            ),
        )

    def open_dialog(self):
        self.file_dialog(
            "Open USD / OmniLab project",
            lambda path: self.replace_guard(lambda: Document.open(path)),
        )

    def save(self, save_as=False):
        def write(path):
            self.document.view["camera"] = self.camera.to_dict()
            self.document.view["scene_camera"] = self.camera_path
            self.materials.save_studio()
            self.document.save(path)
            self.set_status("Saved " + path)

        if save_as or not self.document.path:
            self.file_dialog(
                "Save USD / .omnilab project",
                write,
                True,
                self.document.path or str(Path.home() / "Untitled.omnilab"),
            )
        else:
            write(self.document.path)

    def replace_guard(self, factory):
        if self.document.dirty:
            self.form(
                "Unsaved changes — save first or type DISCARD",
                {"confirmation": ""},
                lambda v: (
                    self.replace(factory())
                    if v["confirmation"] == "DISCARD"
                    else self.set_status("Document retained.")
                ),
            )
        else:
            self.replace(factory())

    def replace(self, document):
        self.console.session.reset()
        self.materials.close_document()
        self.stage_adapter.dispose()
        self.document = document
        self.materials.restore_catalog()
        self.camera = ViewCamera.from_dict(document.view.get("camera", {}))
        self.camera.up_axis = str(UsdGeom.GetStageUpAxis(document.stage))
        if "camera" not in document.view:
            self.camera.frame(document.bounds())
        self.restore_view()
        self.stage_adapter = DocumentStageAdapter(
            document, self.changed, self.call_later
        )
        self.stage_window.set_adapter(self.stage_adapter)
        self.property_window.set_stage_adapter(self.stage_adapter)
        self.selection_bus.publish(document.selection, source="document")
        self.viewport.frame.rebuild()
        if self.materials.window.visible:
            self.materials.show()
        self.changed()
        if self.renderer.enabled and getattr(
            self.renderer.bridge, "config", {}
        ) != document.view.get("renderer_config", {}):
            self.renderer.start()

    def restore_view(self):
        path = self.document.view.get("scene_camera", "")
        prim = self.document.stage.GetPrimAtPath(path) if path else None
        self.camera_path = path if prim and prim.IsA(UsdGeom.Camera) else ""
        preferences = self.document.view.get("viewport", {})
        mode = preferences.get("mode", "RealTimePathTracing")
        self.renderer.mode = (
            mode
            if mode in ("RealTimePathTracing", "PathTracing")
            else "RealTimePathTracing"
        )
        self.renderer.samples = max(1, int(preferences.get("samples", 16)))
        display = preferences.get("display", "Shaded")
        self.renderer.wireframe = display in (
            "Shaded Wireframe",
            "Unlit Wireframe",
            "Wireframe",
        )
        self.renderer.wireframe_mode = (
            "unlit" if display == "Unlit Wireframe" else "shaded"
        )

    def key(self, key, modifiers, pressed):
        if not pressed:
            return
        # The core wheel reports ImGui codes for injected input and GLFW for OS input.
        if 546 <= key <= 571:
            key = ord("A") + key - 546
        key = {522: 261, 526: 256, 573: 291}.get(key, key)
        # WantCaptureKeyboard is true for keyboard navigation too; use actual
        # editing ownership so Ctrl+Z works after viewport mouse gestures.
        if (
            text_editing()
            or self.console.window.focused
            or self.property_window.is_focused
            or self.settings.window.focused
            or self.appearance.window.focused
            or self.render_view.window.focused
        ):
            return
        if self.stage_window.is_focused:
            widget = self.stage_window._widget
            if self.stage_window.is_filter_editing() or (
                widget and widget._rename_controller._active_item
            ):
                return
        if key == 256 and self.gizmo.drag:
            self.gizmo.cancel()
            return
        ctrl, shift = modifiers & 2, modifiers & 1
        if ctrl and key in (ord("S"), ord("s")):
            self.safe(lambda: self.save(bool(shift)))
        elif ctrl and key in (ord("Z"), ord("z"), ord("Y"), ord("y")):
            redo = bool(shift or key in (ord("Y"), ord("y")))
            self.safe(
                lambda: (
                    self.materials.undo(redo)
                    if self.materials.window.focused
                    else self.execute("restore", redo=redo)
                )
            )
        elif self.viewport.focused and key in (ord("F"), ord("f")):
            self.frame_selected()
        elif self.stage_window.is_focused and key == 291:
            self.stage_window.begin_rename_selected()
        elif self.stage_window.is_focused and key == 261:
            self.safe(self.delete)

    def request_exit(self):
        self.exiting = True

    def get_inspector_state(self):
        from dataclasses import asdict

        return dict(
            frontend="ovui",
            appearance=asdict(self.appearance.current),
            path=self.document.path,
            dirty=self.document.dirty,
            revision=self.document.revision,
            selection=self.document.selection,
            prims=[str(p.GetPath()) for p in self.document.stage.Traverse()],
            undo=len(self.document.edits.undo),
            redo=len(self.document.edits.redo),
            render=dict(
                frames=self.renderer.frames,
                publications=self.renderer.publications,
                request=self.renderer.request,
                presented=self.renderer.presented,
                error=self.renderer.error,
            ),
            console_running=self.console.session.running,
            console_output=self.console.output.as_string[-2000:],
            material=self.materials.path,
            material_selected=self.materials.selected,
            material_nodes=self.materials.graph.nodes() if self.materials.graph else [],
            preview=dict(
                frames=self.materials.preview.frames, error=self.materials.preview.error
            ),
            selected_attributes={
                p: {
                    a.GetName(): str(a.Get())
                    for a in self.document.stage.GetPrimAtPath(p).GetAttributes()
                }
                for p in self.document.selection
            },
            final=self.render_view.job.data["state"] if self.render_view.job else None,
        )

    async def run(self):
        try:
            for _ in range(4):
                await ui.next_frame()
            if not self.args.no_render:
                self.renderer.start()
            while not self.exiting:
                now = time.monotonic()
                pending, self.callbacks = self.callbacks, []
                for handle in pending:
                    if handle.is_cancelled:
                        continue
                    if handle._due_time <= now:
                        fn, handle._callback = handle._callback, None
                        self.safe(fn)
                    else:
                        self.callbacks.append(handle)
                if self.inspector:
                    from omni.ui import _ui

                    self.inspector.drain_pending(_ui, application=self)
                self.safe(self.renderer.tick)
                self.materials.tick()
                self.safe(self.render_view.tick)
                self.console.session.tick()
                if self.playing and now - self.last_play >= 1 / max(
                    1, self.document.stage.GetTimeCodesPerSecond()
                ):
                    frame = self.document.frame + 1
                    if frame > self.document.stage.GetEndTimeCode():
                        frame = self.document.stage.GetStartTimeCode()
                    self.frame_model.set_value(frame)
                    self.set_frame(frame)
                    self.last_play = now
                await ui.next_frame()
        except Exception:
            self.failure = traceback.format_exc()
            print(self.failure, flush=True)
        finally:
            self.close()

    def close(self):
        if getattr(self, "closed", False):
            return
        self.closed = True
        self.safe(self.recover)
        for cleanup in (
            close_clipboard,
            self.renderer.close,
            self.materials.close,
            self.render_view.close,
            self.console.session.close,
            self.stage_adapter.dispose,
            self.picker.destroy,
        ):
            self.safe(cleanup)
        scheduler.set_call_later(None)

    def recover(self):
        if self.document.dirty:
            from omnilab.core.document import atomic_json
            from omnilab.usd.usd_project import capture_stage

            # Preserve unsaved work when the native OS close button ends the loop.
            recovery = Path.cwd() / ("recovery-" + str(time.time_ns()) + ".omnilab")
            atomic_json(
                recovery,
                dict(
                    format="omnilab",
                    version=1,
                    stage=capture_stage(self.document.stage, self.document.retained),
                    frame=self.document.frame,
                    selection=self.document.selection,
                    view=self.document.view,
                ),
            )
            print("Unsaved document recovered to " + str(recovery), flush=True)

"""Native ovUI graph canvas, typed ports and isolated material preview."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import omni.ui as ui
from pxr import Sdf, UsdShade
from omnilab.core.camera import ViewCamera
from omnilab.materials.graph import MaterialGraph, create_material
from omnilab.materials.catalog import default_catalog
from omnilab.materials.studio import studio_scene
from omnilab.render.session import InteractiveSession
from .widgets import ImageSurface, field, combo, button, track_edit


class MaterialEditor:
    def __init__(self, owner):
        self.owner = owner
        self.path = ""
        self.graph = None
        self.selected = []
        self.clipboard = None
        self.connection = None
        self.node_drag = None
        self.tabs = []
        self.canvas_states = {}
        self.canvas_path = ""
        self.image = ImageSurface()
        self.camera = ViewCamera(target=[0, 1, 0], distance=5, yaw=24, pitch=12)
        self.geometry, self.light, self.hdri = "Sphere", 1.0, ""
        self.preview = InteractiveSession(
            self.scene, self.image.event, owner.set_status, profile="material"
        )
        self.preview.resolution = (384, 384)
        self.search = track_edit(ui.SimpleStringModel("open_pbr"))
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mdl-reflection"
        )
        self.future = None
        self.window = owner.window("Material Editor", self.build, 1280, 780)
        self.window.setPosition(60, 70)
        self.restore_catalog()

    def restore_catalog(self):
        from omnilab.materials.mdl import install_module

        for report in self.owner.document.view.get("mdl_catalog", []):
            install_module(
                default_catalog(),
                report,
                self.owner.document.view.get("mdl_search_paths", []),
            )

    def show(self):
        self.window.visible = True
        if not self.graph:
            paths = self.material_paths()
            if paths:
                saved = self.owner.document.view.get("materials", {})
                self.tabs = [path for path in saved.get("tabs", []) if path in paths]
                active = min(max(0, saved.get("active", 0)), len(self.tabs) - 1)
                self.set_material(self.tabs[active] if self.tabs else paths[0])
        self.window.frame.rebuild()

    def material_paths(self):
        return [
            str(p.GetPath())
            for p in self.owner.document.stage.Traverse()
            if p.IsA(UsdShade.Material)
        ]

    def set_material(self, path):
        self.save_studio()
        self.graph = MaterialGraph(self.owner.document, path)
        self.path, self.selected, self.connection = path, [], None
        if path not in self.tabs:
            self.tabs.append(path)
        state = self.owner.document.view.get("material_studios", {}).get(path, {})
        self.camera = ViewCamera.from_dict(
            state.get("camera", dict(target=[0, 1, 0], distance=5, yaw=24, pitch=12))
        )
        self.geometry, self.light, self.hdri = (
            state.get("geometry", "Sphere"),
            state.get("light", 1.0),
            state.get("hdri", ""),
        )
        self.preview.mode = state.get("mode", "RealTimePathTracing")
        self.save_studio()
        self.refresh()

    def save_studio(self):
        if self.path:
            self.owner.document.view["materials"] = dict(
                tabs=list(self.tabs), active=self.tabs.index(self.path)
            )
            self.owner.document.view.setdefault("material_studios", {})[self.path] = (
                dict(
                    camera=self.camera.to_dict(),
                    geometry=self.geometry,
                    light=self.light,
                    hdri=self.hdri,
                    mode=self.preview.mode,
                )
            )

    def scene(self):
        key = (
            id(self.owner.document),
            self.owner.document.revision,
            self.owner.document.frame,
            self.path,
            self.geometry,
            self.light,
            self.hdri,
        )
        if key != getattr(self, "studio_key", None):
            self.studio_document, _ = studio_scene(
                self.graph, self.camera, self.geometry, self.light, self.hdri
            )
            self.studio_key = key
        self.studio_document.view = dict(self.owner.document.view)
        return self.studio_document, self.camera.camera(1)

    def refresh(self):
        if self.path and not self.owner.document.stage.GetPrimAtPath(self.path):
            self.graph, self.path = None, ""
        if self.graph:
            live = {n["path"] for n in self.graph.nodes()}
            self.selected = [p for p in self.selected if p in live]
        self.window.frame.rebuild()
        self.preview.invalidate()

    def mutate(self, action):
        result = action()
        self.owner.changed()
        return result

    def build(self):
        if getattr(self, "canvas", None) and self.canvas_path:
            self.canvas_states[self.canvas_path] = (
                self.canvas.pan_x,
                self.canvas.pan_y,
                self.canvas.zoom,
            )
        self.canvas_path = self.path
        with ui.VStack(spacing=4):
            with ui.HStack(height=27, spacing=3):
                paths = self.material_paths()
                combo(
                    paths or ["No materials"],
                    paths.index(self.path) if self.path in paths else 0,
                    changed=lambda index: self.set_material(paths[index])
                    if paths
                    else None,
                )
                button("New OpenPBR", self.new, self.owner, width=110)
                button("Bind selected", self.bind, self.owner, width=105)
                button("Import .mtlx", self.import_mtlx, self.owner, width=100)
                button("Export .mtlx", self.export_mtlx, self.owner, width=100)
                button("Load MDL", self.load_mdl, self.owner, width=85)
            with ui.HStack(height=24, spacing=4):
                for path in self.tabs:
                    if path in paths:
                        button(
                            Path(path).name,
                            lambda p=path: self.set_material(p),
                            self.owner,
                            width=120,
                        )
            with ui.HStack(spacing=6):
                with ui.VStack(width=225, spacing=4):
                    ui.Label("Node library", height=20)
                    ui.StringField(model=self.search, height=25)
                    button(
                        "Search", lambda: self.library.rebuild(), self.owner, height=24
                    )
                    self.library = ui.Frame()
                    self.library.set_build_fn(self.build_library)
                    with ui.HStack(height=26):
                        button("Undo", lambda: self.undo(False), self.owner)
                        button("Redo", lambda: self.undo(True), self.owner)
                    with ui.HStack(height=26):
                        button("Copy", self.copy, self.owner)
                        button("Paste", self.paste, self.owner)
                        button("Delete", self.delete, self.owner)
                with ui.VStack(spacing=4):
                    ui.Label(
                        "Click an output, then an input to connect. Drag a title to move; middle drag pans.",
                        height=20,
                    )
                    self.canvas = ui.CanvasFrame(
                        zoom_min=0.2, zoom_max=2.0, draggable=True
                    )
                    if self.path in self.canvas_states:
                        self.canvas.pan_x, self.canvas.pan_y, self.canvas.zoom = (
                            self.canvas_states[self.path]
                        )
                    self.canvas.set_pan_key_shortcut(2, 0)
                    self.canvas.set_build_fn(self.build_graph)
                    self.inspector = ui.Frame(height=230)
                    self.inspector.set_build_fn(self.build_inspector)
                with ui.VStack(width=285, spacing=4):
                    self.image.build(
                        height=285,
                        opaque_for_mouse_events=True,
                        mouse_pressed_fn=self.preview_down,
                        mouse_moved_fn=self.preview_move,
                        mouse_released_fn=self.preview_up,
                        mouse_wheel_fn=lambda x, y, m: self.preview_dolly(-y * 0.08),
                    )
                    combo(
                        ["Sphere", "Cube", "Card"],
                        ["Sphere", "Cube", "Card"].index(self.geometry),
                        changed=self.set_geometry,
                    )
                    combo(
                        ["RealTimePathTracing", "PathTracing"],
                        int(self.preview.mode == "PathTracing"),
                        changed=self.set_preview_mode,
                    )
                    with ui.HStack(height=26):
                        button("Preview", self.start_preview, self.owner)
                        button("Stop", self.preview.stop, self.owner)
                    button(
                        "Studio light / HDRI",
                        self.studio_options,
                        self.owner,
                        height=26,
                    )
                    button("Bake selected map", self.bake, self.owner, height=26)
                    button("Camera projector", self.projector, self.owner, height=26)
                    diagnostics = self.graph.diagnostics() if self.graph else []
                    ui.Label(
                        "\n".join(map(str, diagnostics))
                        or "Material graph diagnostics: clear",
                        word_wrap=True,
                    )

    def build_library(self):
        with ui.ScrollingFrame():
            with ui.VStack(height=0, spacing=3):
                results = default_catalog().search(self.search.as_string)
                ui.Label(f"{len(results)} definitions; showing first 80", height=24)
                for definition in results[:80]:
                    button(
                        definition.label + " · " + definition.framework,
                        lambda d=definition: self.add_node(d.identifier),
                        self.owner,
                        height=26,
                        tooltip=definition.identifier,
                    )

    def build_graph(self):
        if not self.graph:
            ui.Label("Create or select a material.")
            return
        self.placers = {}
        nodes = self.graph.nodes()
        sockets = {}
        with ui.ZStack(width=1600, height=1200):
            ui.Rectangle(
                style_type_name_override="Material.CanvasBackground",
                opaque_for_mouse_events=False,
            )
            for node in nodes:
                x, y = node["position"]
                names = list(
                    dict.fromkeys(
                        [n for n, p in node["inputs"].items() if p.get("connection")]
                        + list(node["inputs"])[:6]
                    )
                )
                placer = ui.Placer(offset_x=x, offset_y=y)
                self.placers[node["path"]] = placer
                with placer:
                    with ui.VStack(
                        width=220,
                        height=0,
                        spacing=0,
                        style_type_name_override="Material.NodeBackground",
                    ):
                        ui.Button(
                            node["name"] + " · " + node["framework"],
                            height=28,
                            explicit_hover=True,
                            name="material_node_selected"
                            if node["path"] in self.selected
                            else "material_node",
                            mouse_pressed_fn=lambda x, y, b, m, n=node: self.node_down(
                                n, x, y, b, m
                            ),
                            mouse_moved_fn=self.node_move,
                            mouse_released_fn=self.node_up,
                        )
                        for name, type_ in node["outputs"].items():
                            sockets[node["path"] + ".outputs:" + name] = button(
                                name + " : " + type_ + "  >",
                                lambda p=node["path"], n=name: self.output(p, n),
                                self.owner,
                                height=24,
                            )
                        for name in names:
                            port = node["inputs"][name]
                            sockets[node["path"] + ".inputs:" + name] = button(
                                "<  " + name + " : " + port["type"],
                                lambda p=node["path"], n=name: self.input(p, n),
                                self.owner,
                                height=24,
                                tooltip=str(
                                    port.get("connection") or port.get("value")
                                ),
                            )
                        ui.Label(
                            f"{len(node['inputs'])} inputs · select title to inspect",
                            height=22,
                        )
            for node in nodes:
                for name, port in node["inputs"].items():
                    source = sockets.get(port.get("connection"))
                    target = sockets.get(node["path"] + ".inputs:" + name)
                    if source is not None and target is not None:
                        ui.FreeBezierCurve(
                            source,
                            target,
                            start_tangent_width=70,
                            end_tangent_width=-70,
                            style_type_name_override="Material.Connection",
                            opaque_for_mouse_events=False,
                        )

    def node_down(self, node, x, y, button_, modifiers):
        if button_ != 0:
            return
        if modifiers & 2:
            self.selected = list(dict.fromkeys(self.selected + [node["path"]]))
        else:
            self.selected = [node["path"]]
        self.node_drag = (
            node["path"],
            self.canvas.screen_to_canvas(x, y),
            list(node["position"]),
        )
        self.inspector.rebuild()

    def node_move(self, x, y, modifiers, buttons):
        if self.node_drag:
            path, origin, before = self.node_drag
            now = self.canvas.screen_to_canvas(x, y)
            placer = self.placers[path]
            placer.offset_x, placer.offset_y = (
                before[0] + now[0] - origin[0],
                before[1] + now[1] - origin[1],
            )

    def node_up(self, x, y, button_, modifiers):
        if self.node_drag:
            path, origin, before = self.node_drag
            self.node_drag = None
            now = self.canvas.screen_to_canvas(x, y)
            after = [before[0] + now[0] - origin[0], before[1] + now[1] - origin[1]]
            if abs(after[0] - before[0]) + abs(after[1] - before[1]) > 1:
                self.owner.safe(
                    lambda: self.mutate(lambda: self.graph.move({path: after}))
                )
            else:
                self.canvas.rebuild()

    def output(self, path, name):
        self.connection = (path, name)
        self.owner.set_status("Choose an input for " + path + ".outputs:" + name)
        self.inspector.rebuild()

    def input(self, path, name):
        if self.connection:
            source, output = self.connection
            self.mutate(lambda: self.graph.connect(source, output, path, name))
            self.connection = None
        else:
            self.selected = [path]
            self.inspector.rebuild()

    def build_inspector(self):
        with ui.ScrollingFrame():
            with ui.VStack(height=0, spacing=4):
                node = (
                    next(
                        (n for n in self.graph.nodes() if n["path"] in self.selected),
                        None,
                    )
                    if self.graph
                    else None
                )
                if not node:
                    ui.Label("Select a node to edit its typed inputs.", height=25)
                    return
                with ui.HStack(height=26):
                    ui.Label(node["name"])
                    button("Rename", lambda: self.rename(node), self.owner, width=80)
                    button(
                        "Surface terminal",
                        lambda: self.mutate(
                            lambda: self.graph.set_terminal(node["path"])
                        ),
                        self.owner,
                        width=125,
                    )
                for name, port in node["inputs"].items():
                    with ui.HStack(height=25):
                        ui.Label(name + " (" + port["type"] + ")", width=220)
                        value = field(json.dumps(port.get("value")))
                        button(
                            "Set",
                            lambda p=node["path"], n=name, m=value: self.mutate(
                                lambda: self.graph.set_value(
                                    p, n, json.loads(m.as_string)
                                )
                            ),
                            self.owner,
                            width=40,
                        )
                        if self.connection:
                            button(
                                "Connect",
                                lambda p=node["path"], n=name: self.input(p, n),
                                self.owner,
                                width=70,
                            )
                        if port.get("connection"):
                            button(
                                "Disconnect",
                                lambda p=node["path"], n=name: self.mutate(
                                    lambda: self.graph.disconnect(p, n)
                                ),
                                self.owner,
                                width=90,
                            )

    def add_node(self, identifier):
        definition = default_catalog().definition(identifier)
        if definition.framework == "mdl" and definition.metadata.get("material"):
            graph = create_material(self.owner.document, definition.label, identifier)
            self.set_material(str(graph.path))
            self.owner.changed()
            return
        if not self.graph:
            raise ValueError("Create or select a material first.")
        path = self.mutate(
            lambda: self.graph.add_node(
                identifier, position=(40 + len(self.graph.nodes()) * 245, 60)
            )
        )
        self.selected = [str(path)]
        self.refresh()

    def new(self):
        path = create_material(self.owner.document)
        self.set_material(str(path.path))
        self.owner.changed()

    def bind(self):
        if self.graph:
            self.owner.execute(
                "bind_scene_material", self.path, self.owner.document.selection
            )

    def rename(self, node):
        self.owner.form(
            "Rename node",
            {"name": node["name"]},
            lambda v: self.mutate(lambda: self.graph.rename(node["path"], v["name"])),
        )

    def copy(self):
        if self.graph:
            self.clipboard = self.graph.copy(self.selected)

    def paste(self):
        if self.graph and self.clipboard:
            self.selected = list(
                map(str, self.mutate(lambda: self.graph.paste(self.clipboard)))
            )

    def delete(self):
        if self.graph:
            self.mutate(lambda: self.graph.remove(self.selected))

    def undo(self, redo=False):
        if self.graph:
            self.mutate(lambda: self.graph.restore(redo))

    def import_mtlx(self):
        from omnilab.materials.exchange import import_materialx

        def apply(path):
            result = import_materialx(self.owner.document, path)
            self.owner.changed()
            self.set_material(str(result.path))

        self.owner.file_dialog("Import MaterialX", apply)

    def export_mtlx(self):
        from omnilab.materials.exchange import export_materialx

        if self.graph:
            self.owner.file_dialog(
                "Export MaterialX",
                lambda path: export_materialx(self.graph, path),
                True,
                str(Path.home() / "material.mtlx"),
            )

    def load_mdl(self):
        from omnilab.materials.mdl import reflect_module

        def load(path):
            if self.future:
                raise ValueError("A module is already compiling.")
            self.future = self.pool.submit(
                reflect_module,
                path,
                self.owner.document.view.get("mdl_search_paths", []),
            )
            self.future_document = self.owner.document
            self.owner.set_status("Compiling MDL; the editor remains available.")

        self.owner.file_dialog("Load / reload MDL module", load)

    def set_geometry(self, index):
        self.geometry = ["Sphere", "Cube", "Card"][index]
        self.save_studio()
        self.preview.invalidate()

    def set_preview_mode(self, index):
        self.preview.mode = ["RealTimePathTracing", "PathTracing"][index]
        self.save_studio()
        self.preview.invalidate()

    def studio_options(self):
        def apply(v):
            self.light, self.hdri = float(v["light"]), v["hdri"]
            self.save_studio()
            self.preview.invalidate()

        self.owner.form("Preview studio", dict(light=self.light, hdri=self.hdri), apply)

    def preview_down(self, x, y, button_, modifiers):
        self.preview_drag = (x, y, button_)

    def preview_move(self, x, y, modifiers, buttons):
        drag = getattr(self, "preview_drag", None)
        if drag:
            dx, dy = x - drag[0], y - drag[1]
            self.camera.pan(dx, dy, 285) if drag[2] == 2 else self.camera.orbit(dx, dy)
            self.preview_drag = (x, y, drag[2])
            self.save_studio()
            self.preview.invalidate(camera_only=True)

    def preview_up(self, *args):
        self.preview_drag = None

    def preview_dolly(self, amount):
        self.camera.dolly(amount)
        self.save_studio()
        self.preview.invalidate(camera_only=True)

    def start_preview(self):
        if self.owner.render_view.active:
            raise ValueError(
                "Wait for or cancel the final render before starting a preview."
            )
        if not self.graph:
            raise ValueError("Select a material first.")
        self.preview.start()

    def bake(self):
        if not self.graph or not self.selected:
            raise ValueError("Select a float or color map node.")
        from omnilab.materials.bake import prepare_bake

        def apply(v):
            job = prepare_bake(
                self.graph,
                self.selected[0],
                v["output"],
                self.owner.render_view.scratch.name,
                size=int(v["size"]),
                samples=int(v["samples"]),
            )
            self.owner.render_view.start_data(job)

        self.owner.form(
            "Bake selected map",
            dict(output=str(Path.home() / "map.exr"), size="512", samples="16"),
            apply,
        )

    def projector(self):
        from omnilab.materials.projector import add_projector

        if not self.graph:
            raise ValueError("Select a material.")
        self.owner.form(
            "Live camera projector",
            dict(camera="/World/Camera", texture=""),
            lambda v: self.mutate(
                lambda: add_projector(self.graph, v["camera"], v["texture"])
            ),
        )

    def tick(self):
        self.owner.safe(self.preview.tick)
        if self.future and self.future.done():
            future, self.future = self.future, None

            def finish():
                if self.future_document is not self.owner.document:
                    self.owner.set_status(
                        "Document changed; MDL inspection result discarded."
                    )
                    return
                from omnilab.materials.mdl import install_module

                report = future.result()
                document = self.owner.document
                definitions = install_module(
                    default_catalog(), report, document.view.get("mdl_search_paths", [])
                )
                reports = document.view.setdefault("mdl_catalog", [])
                reports[:] = [
                    item for item in reports if item["module"] != report["module"]
                ] + [report]
                modules = document.view.setdefault("mdl_modules", [])
                if report["module"] not in modules:
                    modules.append(report["module"])
                by_identifier = {
                    definition.identifier: definition for definition in definitions
                }

                def reload_sources():
                    for prim in document.stage.Traverse():
                        definition = by_identifier.get(
                            prim.GetCustomDataByKey("omnilab:definition")
                        )
                        if definition:
                            UsdShade.Shader(prim).SetSourceAsset(
                                Sdf.AssetPath(definition.metadata["runtime_module"]),
                                "mdl",
                            )

                document.edits.change("Reload MDL module", reload_sources)
                document.revision += 1
                self.search.set_value(Path(report["module"]).stem)
                self.owner.changed()
                self.window.frame.rebuild()
                self.owner.set_status(
                    f"Loaded {len(definitions)} MDL definitions. Add a material definition to a graph, then set its terminal."
                )

            self.owner.safe(finish)

    def close_document(self):
        self.preview.stop()
        self.graph, self.path, self.tabs, self.selected = None, "", [], []
        self.canvas_states.clear()
        self.canvas_path = ""

    def close(self):
        self.preview.close()
        self.pool.shutdown(wait=False, cancel_futures=True)

"""Native Python console and complete versioned renderer-settings browser."""

import json
from pathlib import Path
import omni.ui as ui
from omnilab.automation.console_session import ConsoleSession
from omnilab.core.document import atomic_json
from omnilab.render.settings import definitions, validate, export_settings, CONTROLLED
from .widgets import button, combo


class ConsolePanel:
    def __init__(self, owner):
        self.owner = owner
        self.code = ui.SimpleStringModel(
            "print([str(p.GetPath()) for p in stage.Traverse()])"
        )
        self.output = ui.SimpleStringModel("")
        self.session = ConsoleSession(
            lambda: owner.document, owner.changed, self.append
        )
        self.window = owner.window("Python Console", self.build, 960, 650)
        self.window.setPosition(100, 100)

    def show(self):
        self.window.visible = True

    def append(self, text):
        self.output.set_value((self.output.as_string + "\n" + text)[-200000:])

    def build(self):
        with ui.VStack(spacing=6):
            ui.Label(
                "stage, usd, document, Usd, UsdGeom, UsdShade, Sdf, Gf, Vt · Successful cells commit as one undo step.",
                height=24,
            )
            ui.StringField(model=self.code, multiline=True, allow_tab_input=True)
            with ui.HStack(height=28):
                button("Run", lambda: self.session.run(self.code.as_string), self.owner)
                button("Stop", self.session.stop, self.owner)
                button("Reset context", self.session.reset, self.owner)
                button("Open script", self.open_script, self.owner)
                button("Save script", self.save_script, self.owner)
            ui.StringField(model=self.output, multiline=True, read_only=True)
            ui.Label(
                "Errors and Stop discard cell USD edits. Script filesystem writes are outside USD undo.",
                height=24,
            )

    def open_script(self):
        self.owner.file_dialog(
            "Open Python script", lambda p: self.code.set_value(Path(p).read_text())
        )

    def save_script(self):
        self.owner.file_dialog(
            "Save Python script",
            lambda p: Path(p).write_text(self.code.as_string),
            True,
            str(Path.home() / "script.py"),
        )


class SettingsPanel:
    def __init__(self, owner):
        self.owner = owner
        self.scope = 0
        self.search = ui.SimpleStringModel("")
        self.window = owner.window("RTX Settings", self.build, 1100, 700)
        self.window.setPosition(80, 80)

    def show(self):
        self.window.visible = True
        self.window.frame.rebuild()

    def values(self):
        if self.scope == 3:
            return self.owner.document.view.setdefault("renderer_config", {})
        return self.owner.document.view.setdefault("rtx_settings", {}).setdefault(
            ["viewport", "material", "final"][self.scope], {}
        )

    def build(self):
        with ui.VStack(spacing=5):
            with ui.HStack(height=28):
                combo(
                    ["Viewport", "Material", "Final", "Renderer creation"],
                    self.scope,
                    self.set_scope,
                    width=200,
                )
                ui.StringField(model=self.search)
                button("Search", lambda: self.rows.rebuild(), self.owner, width=85)
                button("Export all settings", self.export, self.owner, width=145)
            ui.Label(
                "826 declared RTX names. Defaults are schema values; effective runtime values remain unknown.",
                height=23,
            )
            self.rows = ui.Frame()
            self.rows.set_build_fn(self.build_rows)

    def set_scope(self, index):
        self.scope = index
        self.rows.rebuild()

    def build_rows(self):
        values = self.values()
        words = self.search.as_string.lower().split()
        with ui.ScrollingFrame():
            with ui.VStack(height=0, spacing=3):
                for name, definition in definitions(self.scope == 3).items():
                    if not all(
                        w
                        in (
                            name
                            + " "
                            + definition["description"]
                            + " "
                            + definition["group"]
                        ).lower()
                        for w in words
                    ):
                        continue
                    with ui.HStack(height=28):
                        ui.Label(name, width=440, tooltip=definition["description"])
                        ui.Label(definition["type"], width=95)
                        ui.Label(
                            json.dumps(values.get(name, definition["default"])),
                            width=190,
                        )
                        button(
                            "Edit",
                            lambda n=name, d=definition: self.edit(n, d),
                            self.owner,
                            width=55,
                            enabled=name not in CONTROLLED,
                        )
                        button(
                            "Reset", lambda n=name: self.reset(n), self.owner, width=55
                        )
                for name in values.keys() - definitions(self.scope == 3).keys():
                    ui.Label(
                        name
                        + " = "
                        + json.dumps(values[name])
                        + " (unknown; preserved)",
                        height=25,
                    )

    def edit(self, name, definition):
        def apply(v):
            self.values()[name] = validate(
                name, json.loads(v["value"]), self.scope == 3
            )
            self.changed()

        self.owner.form(
            name,
            {"value": json.dumps(self.values().get(name, definition["default"]))},
            apply,
        )

    def reset(self, name):
        self.values().pop(name, None)
        self.changed()

    def changed(self):
        self.rows.rebuild()
        if self.scope == 3:
            if self.owner.renderer.enabled:
                self.owner.renderer.start()
            if self.owner.materials.preview.enabled:
                self.owner.materials.preview.start()
        else:
            self.owner.renderer.invalidate()
            self.owner.materials.preview.invalidate()

    def export(self):
        self.owner.file_dialog(
            "Export declared / authored RTX settings",
            lambda p: atomic_json(p, export_settings(self.owner.document)),
            True,
            str(Path.home() / "ovrtx-settings.json"),
        )

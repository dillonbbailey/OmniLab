"""Native appearance controls with explicit Apply and durable preferences."""

import omni.ui as ui
from .appearance import Appearance, THEMES, DENSITIES
from .style import apply_style
from .widgets import button, combo, combo_index


class AppearancePanel:
    def __init__(self, owner, appearance):
        self.owner = owner
        self.current = appearance
        self.window = owner.window("Appearance", self.build, 480, 345)
        self.window.setPosition(470, 220)

    def show(self):
        self.window.visible = True
        self.window.frame.rebuild()

    def build(self):
        with ui.VStack(spacing=8):
            ui.Label("Theme", height=24)
            self.theme = combo(
                list(THEMES.values()), list(THEMES).index(self.current.theme)
            )
            ui.Label("Control density", height=24)
            self.density = combo(
                list(DENSITIES.values()), list(DENSITIES).index(self.current.density)
            )
            ui.Label(
                "Applies to the workspace, Properties, Stage, Layers,\nasset dialogs, Material Editor and render/settings panels.",
                height=42,
                word_wrap=True,
            )
            ui.Label(
                "Showcase presets adapt NVIDIA’s example accent colors.\nColor and density are saved independently for this user.",
                height=42,
                word_wrap=True,
            )
            ui.Spacer()
            with ui.HStack(height=28, spacing=8):
                button("Restore defaults", self.defaults, self.owner)
                button("Apply", self.apply, self.owner, name="ok")
                button(
                    "Close", lambda: setattr(self.window, "visible", False), self.owner
                )

    def defaults(self):
        self.theme.model.get_item_value_model().set_value(0)
        self.density.model.get_item_value_model().set_value(0)

    def apply(self):
        candidate = Appearance(
            list(THEMES)[combo_index(self.theme)],
            list(DENSITIES)[combo_index(self.density)],
        )
        # Saving first makes a filesystem failure leave the visible theme alone.
        candidate.save()
        apply_style(candidate)
        self.current = candidate
        self.owner.set_status(
            f"Appearance: {THEMES[candidate.theme]} / {DENSITIES[candidate.density]}"
        )

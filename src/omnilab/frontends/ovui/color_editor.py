"""Three numeric channels followed by the native ovUI color-picker square."""

import math
import omni.ui as ui

from .widgets import track_edit
from .value_menu import install_value_menu

COLOR_TYPES = {"color3", "color3f", "color3d"}
COLOR_SWATCH_SIZE = 22
COLOR_CHANNEL_SPACING = 3


class ColorEditor:
    def __init__(
        self,
        value,
        committed,
        *,
        enabled=True,
        begin=None,
        end=None,
        safe=lambda fn: fn(),
    ):
        self.committed, self.begin_callback, self.end_callback = committed, begin, end
        self.values = list(value) if value is not None else [0.0, 0.0, 0.0]
        self.original = list(self.values)
        self.updating = False
        self.editing = False
        self.fields = []
        with ui.HStack(spacing=COLOR_CHANNEL_SPACING, height=COLOR_SWATCH_SIZE):
            for i, value in enumerate(self.values):
                model = track_edit(ui.SimpleFloatModel(float(value)))
                field = ui.FloatDrag(
                    model=model,
                    precision=6,
                    step=0.01,
                    enabled=enabled,
                    tooltip="RGB"[i],
                    style_type_name_override="Property.ValueField",
                )
                self.fields.append(field)
            self.swatch = ui.ColorWidget(
                *self.values,
                width=COLOR_SWATCH_SIZE,
                height=COLOR_SWATCH_SIZE,
                enabled=enabled,
                tooltip="Choose color; numeric fields retain HDR values.",
                style_type_name_override="Property.ColorSwatch",
            )
        self.color_models = [
            self.swatch.model.get_item_value_model(item)
            for item in self.swatch.model.get_item_children()
        ]
        for i, field in enumerate(self.fields):
            install_value_menu(field, lambda: list(self.values), safe)
            field.model.add_begin_edit_fn(lambda m: self.begin())
            field.model.add_value_changed_fn(
                lambda m, i=i: self.component(i, m.as_float)
            )
            field.model.add_end_edit_fn(lambda m: self.finish())
        self.swatch.model.add_begin_edit_fn(lambda m, item: self.begin())
        install_value_menu(self.swatch, lambda: list(self.values), safe)
        self.swatch.model.add_end_edit_fn(lambda m, item: self.finish())
        for i, model in enumerate(self.color_models):
            model.add_value_changed_fn(lambda m, i=i: self.component(i, m.as_float))

    def begin(self):
        if not self.editing:
            self.original = list(self.values)
            if self.begin_callback:
                self.begin_callback()
            self.editing = True

    def component(self, index, value):
        if self.updating:
            return
        self.begin()
        self.values[index] = value
        self.set_value(self.values)

    def set_value(self, values):
        self.values = list(values)
        self.updating = True
        try:
            for field, model, value in zip(self.fields, self.color_models, values):
                field.model.set_value(value)
                model.set_value(value)
        finally:
            self.updating = False

    def finish(self):
        if not self.editing:
            return
        self.editing = False
        changed = self.values != self.original
        if not all(math.isfinite(v) for v in self.values):
            self.set_value(self.original)
            changed = False
        if self.end_callback:
            self.end_callback(list(self.values), changed)
        elif changed:
            self.committed(list(self.values))
        self.original = list(self.values)

"""Extend NVIDIA's grouped inspector with editable color-picker squares."""

import omni.ui as ui
from ovui_widgets.property.window import PropertyWindow
from ovui_widgets.property.payload import PropertyPayload
from ovui_widgets.property.widget.attributes_widget import AttributesWidget
from ovui_widgets.property.widget.scheme_registry import PropertySchemeRegistry
from ovui_widgets.property.models.attribute_model import AttributeModelBase
from ovui_widgets.property.parts.control_state import ControlStateIndicator
from ovui_widgets.property.attribute_row import (
    _build_attribute_label_slot,
    _wire_row_context_menu,
)

from .color_editor import ColorEditor, COLOR_TYPES
from .value_menu import copy_value
from ovui_widgets.property.parts import attr_context_menu as stock_menu


def install_property_menu(widget, adapter, prop, safe):
    active = []

    def show(x, y, button, modifiers):
        if button != 1:
            return

        def copy():
            stock_menu.copy_value(adapter, prop.name)
            copy_value(adapter.get_value(prop.name))

        menu = ui.Menu("Property value")
        with menu:
            ui.MenuItem("Copy values", triggered_fn=lambda: safe(copy))
            ui.MenuItem(
                "Paste Value",
                enabled=stock_menu.can_paste(adapter, prop.name),
                triggered_fn=lambda: safe(
                    lambda: stock_menu.paste_value(adapter, prop.name)
                ),
            )
            ui.MenuItem(
                "Reset to Default",
                enabled=stock_menu.can_reset(adapter, prop.name),
                triggered_fn=lambda: safe(
                    lambda: stock_menu.reset_value(adapter, prop.name)
                ),
            )
            ui.MenuItem(
                "Copy Attribute Path",
                triggered_fn=lambda: safe(
                    lambda: copy_value(
                        stock_menu.compose_attribute_path(adapter, prop.name)
                    )
                ),
            )
        active[:] = [menu]
        menu.show_at(x, y)

    widget.set_mouse_released_fn(show)


class ColorRow:
    def __init__(self, prop, adapter, match, safe):
        self._prop, self._adapter = prop, adapter
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._active_context_menu = None
        self._safe = safe
        with ui.HStack(height=24, spacing=2) as row:
            _build_attribute_label_slot(prop, match)
            with ui.HStack(width=160):
                self.editor = ColorEditor(
                    self._model.get_value(),
                    None,
                    enabled=not self._model.is_readonly,
                    begin=self._model.begin_edit,
                    end=lambda values, changed: safe(
                        lambda: self.finish(values, changed)
                    ),
                    safe=safe,
                )
            self._indicator = ControlStateIndicator(self._model, adapter, prop.name)
        _wire_row_context_menu(row, self)
        for widget in [row, *self.editor.fields, self.editor.swatch]:
            install_property_menu(widget, adapter, prop, safe)
        self._value_sub = self._model.subscribe_value_changed(self.refresh)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)

    def finish(self, values, changed):
        if changed:
            self._model.set_value(tuple(values))
        self._model.end_edit()

    def refresh(self):
        value = self._model.get_value()
        if value is not None and not self.editor.editing:
            self.editor.set_value(value)


class ColorAttributes(AttributesWidget):
    def _build_attribute_row(self, prop):
        window = self._window
        if prop.type_name not in COLOR_TYPES:
            super()._build_attribute_row(prop)
            row = window._inspector_attribute_rows.get(prop.name)
            for widget in [
                getattr(row, "_row_hstack", None),
                getattr(row, "_widget", None),
                *getattr(row, "_widgets", []),
            ]:
                if hasattr(widget, "set_mouse_released_fn"):
                    install_property_menu(widget, window._adapter, prop, window.safe)
            return
        row = ColorRow(prop, window._adapter, window._filter_text or "", window.safe)
        if not hasattr(window, "_inspector_attribute_rows"):
            window._inspector_attribute_rows = {}
        window._inspector_attribute_rows[prop.name] = row


class OmniLabPropertyWindow(PropertyWindow):
    def __init__(self, safe):
        self.safe = safe
        super().__init__()

    def _build_registered_widgets(self):
        # Keep NVIDIA's grouping/filter/extension pipeline; replace only its
        # built-in attribute section within this window, not the global registry.
        payload = PropertyPayload(paths=self._selection)
        widgets = PropertySchemeRegistry.instance().get_widgets_for_payload(
            payload.get_scheme(), payload
        )
        for widget in [*widgets, *self._widgets]:
            if type(widget) is AttributesWidget:
                widget = ColorAttributes()
            if hasattr(widget, "set_window"):
                widget.set_window(self)
            if widget.on_new_payload(payload):
                widget.build_items()

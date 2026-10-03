"""Small native ovUI controls used by the OmniLab panels."""

import omni.ui as ui
import numpy as np
import weakref

_EDITING = {}


def track_edit(model):
    model.add_begin_edit_fn(lambda m: _EDITING.update({id(m): weakref.ref(m)}))
    model.add_end_edit_fn(lambda m: _EDITING.pop(id(m), None))
    return model


def text_editing():
    return any(ref() is not None for ref in _EDITING.values())


def field(value="", width=None, multiline=False, read_only=False):
    model = ui.SimpleStringModel(str(value))
    args = dict(
        model=model,
        height=0 if not multiline else ui.Fraction(1),
        multiline=multiline,
        read_only=read_only,
    )
    if width is not None:
        args["width"] = width
    track_edit(model)
    ui.StringField(**args)
    return model


def combo(values, selected=0, changed=None, width=None):
    args = dict(height=26) if width is None else dict(width=width, height=26)
    widget = ui.ComboBox(selected, *values, **args)
    if changed:
        widget.model.add_item_changed_fn(
            lambda model, item: changed(model.get_item_value_model().as_int)
        )
    return widget


def combo_index(widget):
    return widget.model.get_item_value_model().as_int


def button(label, callback, owner, **kwargs):
    return ui.Button(label, clicked_fn=lambda: owner.safe(callback), **kwargs)


class ImageSurface:
    def __init__(self):
        self.provider = ui.ByteImageProvider()
        self.pixels = np.zeros((2, 2, 4), np.uint8)
        self.widget = None
        self.set_pixels(self.pixels)

    def build(self, **kwargs):
        self.widget = ui.ImageWithProvider(
            self.provider,
            fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
            explicit_hover=True,
            scroll_only_window_hovered=True,
            **kwargs,
        )
        return self.widget

    def set_pixels(self, pixels):
        self.pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
        height, width = self.pixels.shape[:2]
        self.provider.set_data_array(self.pixels, [width, height])

    def event(self, message):
        self.set_pixels(
            np.frombuffer(message["pixels"], np.uint8).reshape(message["shape"]).copy()
        )

    def position(self, x, y):
        """Image normalized coordinates, excluding preserve-aspect letterboxing."""
        w = self.widget
        width, height = float(w.computed_width), float(w.computed_height)
        image_h, image_w = self.pixels.shape[:2]
        scale = min(width / image_w, height / image_h)
        left = w.screen_position_x + (width - image_w * scale) / 2
        top = w.screen_position_y + (height - image_h * scale) / 2
        u, v = (x - left) / max(1, image_w * scale), (y - top) / max(1, image_h * scale)
        return (u, v) if 0 <= u <= 1 and 0 <= v <= 1 else None

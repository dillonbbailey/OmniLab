"""One owner for application, component and OmniLab-specific styles."""

from importlib.resources import files
import omni.ui as ui
from omni.ui import color as cl
from omni.ui import constant as fl
from ovui_widgets.app.style import constants as nvidia_constants  # noqa: F401
from ovui_widgets.app.style.styles import GLOBAL_STYLES
from ovui_widgets.app.style.imgui_runtime import apply_imgui_splitter_style
from ovui_widgets.stage.style import STAGE_STYLES
from ovui_widgets.property.style import PROPERTY_STYLES
from ovui_widgets.content.style import CONTENT_STYLES
from ovui_widgets.layers.style import LAYERS_STYLES

from .palette import register
from .constants import apply_density


def apply_style(appearance):
    register()
    ui.set_shade("default" if appearance.theme == "dark" else appearance.theme)
    apply_density(appearance.density)
    styles = {
        **GLOBAL_STYLES,
        **STAGE_STYLES,
        **PROPERTY_STYLES,
        **CONTENT_STYLES,
        **LAYERS_STYLES,
        "Material.CanvasBackground": {"background_color": cl.background_secondary},
        "Material.NodeBackground": {"background_color": cl.material_node_background},
        "Material.Connection": {
            "color": cl.material_connection,
            "border_width": fl.material_connection_width,
        },
        "Button::material_node": {"background_color": cl.background_elevated},
        "Button::material_node_selected": {"background_color": cl.accent_primary},
        "Button.Label::material_node_selected": {"color": cl.text_on_accent},
        "Button::material_node_selected:hovered": {
            "background_color": cl.accent_hovered
        },
        "Button.Label::material_node_selected:hovered": {"color": cl.text_on_accent},
        "Button.Label::ok:hovered": {"color": cl.text_on_accent},
        "Button::layer_edit_target": {"background_color": cl.layers_row_edit_target},
        "Button::layer_edit_target:hovered": {
            "background_color": cl.layers_row_edit_target
        },
        "Button::layer_muted": {"color": cl.text_disabled},
        "Button.Label::layer_muted": {"color": cl.text_disabled},
    }
    # An explicit bundled font also supports font-size changes on standalone
    # runtimes whose default ImGui font ignores the widget's requested size.
    font = str(files("omni.ui").joinpath("resources/fonts/NotoSans-Regular.ttf"))
    styles = {
        selector: {**values, "font": font} if "font_size" in values else values
        for selector, values in styles.items()
    }
    ui.style.default = styles
    apply_imgui_splitter_style()

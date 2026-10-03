"""OvGear palette plus accents inspired by NVIDIA's standalone showcase."""

from omni.ui import color as cl
from ovui_widgets.common.style import palette as nvidia_palette  # noqa: F401


def register():
    # Unspecified shades retain the default value in NVIDIA's ColorStore.
    for name, dark, light, orange, blue, teal in (
        ("accent_primary", "#008AF9", "#008AF9", "#BB6620", "#3366CC", "#33AAAA"),
        ("accent_hovered", "#1FA0FF", "#1FA0FF", "#DD8833", "#4477DD", "#44BBBB"),
        ("accent_pressed", "#0060C7", "#0060C7", "#8F4B16", "#254B99", "#247D7D"),
        ("accent_secondary", "#008AF9", "#008AF9", "#BB6620", "#3366CC", "#33AAAA"),
        ("border_focused", "#008AF9", "#0078D4", "#DD8833", "#4477DD", "#44BBBB"),
        (
            "treeview_drop_indicator",
            "#008AF9",
            "#008AF9",
            "#BB6620",
            "#3366CC",
            "#33AAAA",
        ),
        (
            "property_state_indicator_active",
            "#008AF980",
            "#008AF9",
            "#BB662080",
            "#3366CC80",
            "#33AAAA80",
        ),
        ("background_primary", "#222222", "#E0E0E0", "#1A1A1A", "#1A1A1A", "#1A1A1A"),
        ("background_field", "#161616", "#EEEEEE", "#111111", "#111111", "#111111"),
    ):
        cl.shade(
            cl(dark),
            light=cl(light),
            showcase_orange=cl(orange),
            showcase_blue=cl(blue),
            showcase_teal=cl(teal),
            name=name,
        )

    cl.shade(cl("#313131"), light=cl("#FFFFFF"), name="material_node_background")
    cl.shade(cl("#DDAA50"), light=cl("#996000"), name="material_connection")

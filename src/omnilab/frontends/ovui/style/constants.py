"""OmniLab density values; color changes never change geometry constants."""

from omni.ui import constant as fl


def apply_density(density):
    comfortable = density == "comfortable"
    values = dict(
        font_size_tiny=10,
        font_size_small=14 if comfortable else 13,
        font_size_medium=16 if comfortable else 14,
        font_size_value=14 if comfortable else 13,
        font_size_large=20 if comfortable else 18,
        font_size_xlarge=24 if comfortable else 22,
        treeview_indent=16,
        treeview_row_height=24 if comfortable else 22,
        property_label_width=145 if comfortable else 135,
        property_row_height=24,
        scrollbar_width=9 if comfortable else 7,
        radius_none=0,
        radius_small=3,
        radius_medium=5,
        radius_large=8,
        spacing_none=0,
        spacing_small=6 if comfortable else 4,
        spacing_medium=10 if comfortable else 8,
        spacing_large=18 if comfortable else 16,
        material_connection_width=2,
    )
    for name, value in values.items():
        setattr(fl, name, float(value))
    return values

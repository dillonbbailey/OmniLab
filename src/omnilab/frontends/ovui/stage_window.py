"""Add OmniLab's prim actions without replacing NVIDIA's tree interactions."""

import omni.ui as ui
from ovui_widgets.stage.window import StageWindow


class OmniLabStageWindow(StageWindow):
    def __init__(self, adapter, selection_bus, context_menu):
        self.context_menu = context_menu
        super().__init__(adapter, selection_bus)

    def _build_ui(self):
        super()._build_ui()
        delegate = self._widget._delegate
        build = delegate.build_widget

        def build_with_menu(model, item, column, level, expanded):
            if item is None:
                return build(model, item, column, level, expanded)
            path = str(model._adapter.get_item_path(item.adapter_item))
            with ui.HStack(
                mouse_released_fn=lambda x, y, b, m: (
                    self.context_menu(path, x, y) if b == 1 else None
                )
            ):
                build(model, item, column, level, expanded)

        # The delegate is local to this tree. Keep its existing rename,
        # expansion, visibility and drag/drop handlers inside each wrapper.
        delegate.build_widget = build_with_menu

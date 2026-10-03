"""Native color controls share the property adapter's undo transaction."""

import pytest

pytest.importorskip("ovui_widgets.property")
from pxr import Sdf
from omnilab.core.fixtures import demo_document
from omnilab.frontends.ovui.adapters import DocumentPropertyAdapter
from omnilab.frontends.ovui.property_window import ColorRow


def test_native_color_swatch_models_preserve_hdr_noop_and_commit_once():
    document = demo_document()
    prim = document.stage.GetPrimAtPath("/World/Cube")
    attr = prim.CreateAttribute("test:color", Sdf.ValueTypeNames.Color3f)
    attr.Set((2.0, 0.25, 0.5))
    adapter = DocumentPropertyAdapter(document, ["/World/Cube"])
    row = ColorRow(
        adapter.get_attribute_metadata("test:color"), adapter, "", lambda fn: fn()
    )
    editor = row.editor
    assert len(editor.fields) == 3 and len(editor.color_models) == 3
    editor.begin()
    editor.finish()
    assert list(attr.Get()) == [2.0, 0.25, 0.5] and not document.edits.undo
    editor.begin()
    editor.color_models[1].set_value(0.75)
    editor.color_models[2].set_value(0.125)
    assert list(attr.Get()) == [2.0, 0.25, 0.5]
    editor.finish()
    assert list(attr.Get()) == [2.0, 0.75, 0.125] and len(document.edits.undo) == 1
    document.command("restore")
    assert list(attr.Get()) == [2.0, 0.25, 0.5]


def test_native_color_target_switch_cannot_commit():
    document = demo_document()
    adapter = DocumentPropertyAdapter(document, ["/World/Looks/Surface/Shader"])
    row = ColorRow(
        adapter.get_attribute_metadata("inputs:base_color"),
        adapter,
        "",
        lambda fn: fn(),
    )
    before = adapter.get_value("inputs:base_color")
    row.editor.begin()
    row.editor.component(0, 0.75)
    document.stage.SetEditTarget(document.stage.GetSessionLayer())
    with pytest.raises(ValueError, match="target changed"):
        row.editor.finish()
    assert adapter.get_value("inputs:base_color") == before
    assert not document.edits.undo

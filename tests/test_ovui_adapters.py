"""Frontend contract: NVIDIA widget adapters retain OmniLab authoring semantics."""

import pytest

pytest.importorskip("ovui_data_adapters")
from pxr import UsdGeom
from omnilab.core.document import Document
from omnilab.core.fixtures import demo_document
from omnilab.frontends.ovui.adapters import (
    DocumentStageAdapter,
    DocumentPropertyAdapter,
)
from omnilab.materials.graph import MaterialGraph, create_material


def test_stage_rename_visibility_shared_undo(tmp_path):
    document = demo_document()
    adapter = DocumentStageAdapter(document)
    try:
        document.select(["/World/Cube"])
        adapter.rename(document.stage.GetPrimAtPath("/World/Cube"), "Box")
        assert document.selection == ["/World/Box"]
        assert len(document.edits.undo) == 1
        adapter.set_visibility(document.stage.GetPrimAtPath("/World/Box"), False)
        assert len(document.edits.undo) == 2
        document.command("restore")
        assert (
            UsdGeom.Imageable(
                document.stage.GetPrimAtPath("/World/Box")
            ).ComputeVisibility()
            == "inherited"
        )
        document.command("restore")
        assert document.selection == ["/World/Cube"]
        assert document.stage.GetPrimAtPath("/World/Cube")
        document.command("restore", redo=True)
        assert document.stage.GetPrimAtPath("/World/Box")
        document.save(tmp_path / "ovui.omnilab")
        other = Document.open(tmp_path / "ovui.omnilab")
        assert other.selection == ["/World/Box"]
        assert other.stage.GetPrimAtPath("/World/Box")
    finally:
        adapter.dispose()


def test_property_commit_cancel_and_noop():
    document = demo_document()
    adapter = DocumentPropertyAdapter(document, ["/World/Cube"])
    adapter.begin_edit("size")
    adapter.end_edit("size")
    assert len(document.edits.undo) == 0
    adapter.begin_edit("size")
    adapter.set_value("size", 3.0)
    assert document.stage.GetPrimAtPath("/World/Cube").GetAttribute("size").Get() == 1.5
    adapter.cancel_edit("size")
    assert len(document.edits.undo) == 0
    adapter.begin_edit("size")
    adapter.set_value("size", 3.0)
    adapter.end_edit("size")
    assert len(document.edits.undo) == 1
    document.command("restore")
    assert document.stage.GetPrimAtPath("/World/Cube").GetAttribute("size").Get() == 1.5
    document.command("set_transform_lock", "/World/Cube", True)
    before = document.edits.layer.ExportToString()
    with pytest.raises(ValueError):
        adapter.clear_value("xformOp:translate")
    assert document.edits.layer.ExportToString() == before


def test_property_batch_failure_rollback():
    document = demo_document()
    before = document.edits.layer.ExportToString()
    with pytest.raises(Exception):
        document.command(
            "set_properties",
            [
                dict(path="/World/Cube", group="Attributes", name="size", value=7),
                dict(
                    path="/World/Sphere",
                    group="Attributes",
                    name="orientation",
                    value="not-an-allowed-token",
                ),
            ],
        )
    assert document.edits.layer.ExportToString() == before
    assert not document.edits.undo


def test_property_target_switch_cannot_commit():
    document = demo_document()
    adapter = DocumentPropertyAdapter(document, ["/World/Cube"])
    adapter.begin_edit("size")
    adapter.set_value("size", 4.0)
    document.stage.SetEditTarget(document.stage.GetSessionLayer())
    with pytest.raises(ValueError, match="target changed"):
        adapter.end_edit("size")
    assert not document.edits.undo


def test_property_batch_rolls_back_root_metadata_and_nonroot_edit_target():
    document = demo_document()
    document.stage.SetEditTarget(document.stage.GetSessionLayer())
    before = [layer.ExportToString() for layer in document.stage.GetLayerStack()]
    with pytest.raises(Exception):
        document.command(
            "set_properties",
            [
                dict(path="/", group="Metadata", name="upAxis", value="Z"),
                dict(path="/World/Cube", group="Attributes", name="size", value=5),
                dict(
                    path="/World/Sphere",
                    group="Attributes",
                    name="orientation",
                    value="invalid",
                ),
            ],
        )
    assert [
        layer.ExportToString() for layer in document.stage.GetLayerStack()
    ] == before
    assert document.stage.GetEditTarget().GetLayer() == document.stage.GetSessionLayer()
    assert not document.edits.undo


def test_widget_and_material_histories_round_trip(tmp_path):
    document = demo_document()
    graph = create_material(document, "Second")
    material = graph.path
    node = graph.nodes()[0]["path"]
    graph.set_value(node, "base_color", [0.8, 0.1, 0.05])
    graph.move({node: [250, 80]})
    property_ = DocumentPropertyAdapter(document, ["/World/Cube"])
    property_.begin_edit("size")
    property_.set_value("size", 3)
    property_.end_edit("size")
    graph.restore()
    assert document.stage.GetPrimAtPath("/World/Cube").GetAttribute("size").Get() == 3
    document.view["material_studios"] = {
        str(material): {"geometry": "Sphere", "light": 2}
    }
    document.save(tmp_path / "shared.omnilab")
    reopened = Document.open(tmp_path / "shared.omnilab")
    other = MaterialGraph(reopened, material)
    assert other.nodes()[0]["inputs"]["base_color"]["value"] == pytest.approx(
        [0.8, 0.1, 0.05]
    )
    assert reopened.view == document.view


def test_multi_selection_visibility_is_one_undo_and_abort_authors_nothing():
    document = demo_document()
    adapter = DocumentStageAdapter(document)
    try:
        adapter.begin_undo_group("Visibility")
        for path in ["/World/Cube", "/World/Sphere"]:
            adapter.set_visibility(document.stage.GetPrimAtPath(path), False)
        assert not document.edits.undo
        adapter.end_undo_group()
        assert len(document.edits.undo) == 1
        document.command("restore")
        for path in ["/World/Cube", "/World/Sphere"]:
            assert (
                UsdGeom.Imageable(
                    document.stage.GetPrimAtPath(path)
                ).ComputeVisibility()
                == "inherited"
            )
        adapter.begin_undo_group("Cancelled")
        adapter.set_visibility(document.stage.GetPrimAtPath("/World/Cube"), False)
        adapter.abort_undo_group()
        assert not document.edits.undo
        assert len(document.edits.redo) == 1
    finally:
        adapter.dispose()


def test_multi_selection_namespace_undo_and_failure_rollback():
    from ovui_data_adapters.common import ReparentPosition

    document = demo_document()
    document.command("add_prim", "/World", "Group", "Xform")
    document.select(["/World/Cube", "/World/Sphere"])
    adapter = DocumentStageAdapter(document)
    try:
        adapter.reparent(
            [document.stage.GetPrimAtPath(path) for path in document.selection],
            document.stage.GetPrimAtPath("/World/Group"),
            ReparentPosition.CHILD,
        )
        assert len(document.edits.undo) == 2
        assert document.selection == ["/World/Group/Cube", "/World/Group/Sphere"]
        document.command("restore")
        assert document.selection == ["/World/Cube", "/World/Sphere"]
        document.command("restore", redo=True)
        assert document.selection == ["/World/Group/Cube", "/World/Group/Sphere"]
        before = [layer.ExportToString() for layer in document.stage.GetLayerStack()]
        revision = document.revision
        with pytest.raises(Exception):
            document.command(
                "edit_prims",
                [
                    dict(
                        name="set_property",
                        data=dict(
                            path="/World/Group/Cube",
                            group="Attributes",
                            name="size",
                            value=5,
                        ),
                    ),
                    dict(
                        name="reparent_prim",
                        data=dict(
                            path="/World/Group",
                            parent="/World/Group/Cube",
                            mode="namespace",
                        ),
                    ),
                ],
            )
        assert [
            layer.ExportToString() for layer in document.stage.GetLayerStack()
        ] == before
        assert document.revision == revision
        assert len(document.edits.undo) == 2
    finally:
        adapter.dispose()

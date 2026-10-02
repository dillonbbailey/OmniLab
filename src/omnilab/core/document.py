"""Authoritative document and command API; independent of Qt and ovRTX."""
import json
import os
from pathlib import Path
import tempfile

from pxr import Sdf, Usd, UsdGeom

from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_new_stage import create_stage
from omnilab.usd.usd_project import capture_stage, restore_stage
from omnilab.usd.usd_variants import edit_variant


def atomic_json(path, value):
    path = Path(path).expanduser().absolute()
    fd, name = tempfile.mkstemp(prefix=".omnilab-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Document:
    def __init__(self, stage=None, retained=(), target=None, path=""):
        self.stage = stage if stage is not None else create_stage()[0]
        self.retained = retained
        self.edits = StageEdits(self.stage)
        for layer in self.stage.GetLayerStack():
            self.edits.track_layer(layer)
        if target:
            self.edits.set_edit_target(target.identifier)
        self.path = path
        self.revision = 0
        self.frame = self.stage.GetStartTimeCode()
        self.selection = []
        self.view = {}
        self._runtime_state = self._state()

    def _state(self):
        return (tuple(sorted(self.stage.GetMutedLayers())),
                tuple(self.stage.GetLoadRules().GetRules()))

    @property
    def dirty(self):
        return self.edits.state()["dirty"] or self._runtime_state != self._state()

    @classmethod
    def open(cls, path):
        path = str(Path(path).expanduser().resolve())
        if path.endswith(".omnilab"):
            data = json.loads(Path(path).read_text())
            if data.get("format") != "omnilab" or data.get("version") != 1:
                raise ValueError("Unsupported OmniLab project format.")
            stage, retained, target = restore_stage(data["stage"])
            result = cls(stage, retained, target, path)
            result.frame = float(data.get("frame", result.frame))
            result.view = data.get("view", {})
            result.select(data.get("selection", []))
            return result
        # An isolated root avoids sharing unsaved root edits with another document.
        # capture/restore also isolates contributing dependencies and anchors assets.
        root = Sdf.Layer.OpenAsAnonymous(path)
        if not root:
            raise ValueError("USD could not open " + path)
        from omnilab.usd.usd_project import remap_assets, anchor_asset
        original = Sdf.Layer.FindOrOpen(path)
        remap_assets(root, lambda asset: anchor_asset(original, asset))
        stage = Usd.Stage.Open(root)
        stage, retained, target = restore_stage(capture_stage(stage))
        return cls(stage, retained, target, path)

    def select(self, paths):
        self.selection = list(dict.fromkeys(str(p) for p in paths if self.stage.GetPrimAtPath(p)))

    def command(self, name, *args, **kwargs):
        previous_selection = list(self.selection)
        if name == "variant":
            result = edit_variant(self.edits, *args, **kwargs)
        elif name == "payload":
            from omnilab.usd.usd_composition import set_payload_load
            path, loaded = args
            before = self.stage.GetLoadRules()
            try:
                set_payload_load(self.stage, path, loaded)
            except Exception:
                self.stage.SetLoadRules(before)
                raise
            # A no-op layer snapshot keeps load-rule history in the same transaction model.
            self.edits.undo.append(("Load payload" if loaded else "Unload payload",
                                    self.edits.layer, self.edits.layer.ExportToString(),
                                    {"load_rules": before}))
            self.edits.redo.clear()
            self.edits.undo = self.edits.undo[-100:]
            result = None
        else:
            allowed = {"add_prim", "remove_prim", "duplicate_prim", "reparent_prim", "set_default_prim",
                       "set_prim_specifier", "set_prim_active", "set_prims_active", "set_transform",
                       "set_transform_lock", "set_frame_range", "set_property", "set_stage_metadata",
                       "set_layer_muted", "set_sublayers", "create_sublayer", "add_arc", "apply_schema",
                       "convert_to_mesh", "bind_scene_material", "restore"}
            if name not in allowed:
                raise ValueError("Unknown document command: " + name)
            result = getattr(self.edits, name)(*args, **kwargs)
        self.revision += 1
        move = None
        if name == "reparent_prim":
            move = (Sdf.Path(args[0]["path"]), Sdf.Path(result))
        elif name == "restore" and isinstance(result, tuple) and len(result) == 2:
            move = tuple(Sdf.Path(path) for path in result)
        if move:
            self.select([str(Sdf.Path(path).ReplacePrefix(*move)) for path in previous_selection])
        else:
            self.select(previous_selection)
        return result

    def save(self, path=None):
        path = str(Path(path or self.path).expanduser().absolute())
        if path.endswith(".omnilab"):
            atomic_json(path, dict(format="omnilab", version=1,
                                   stage=capture_stage(self.stage, self.retained),
                                   frame=self.frame, selection=self.selection, view=self.view))
            self.edits.saved = {layer: layer.ExportToString() for layer in self.edits.saved}
        else:
            self.edits.export(path, self.retained)
        self.path = path
        self._runtime_state = self._state()
        return path

    def bounds(self, paths=()):
        cache = UsdGeom.BBoxCache(Usd.TimeCode(self.frame), ["default", "render", "proxy"], useExtentsHint=True)
        prims = [self.stage.GetPrimAtPath(path) for path in paths] or [self.stage.GetPseudoRoot()]
        from pxr import Gf
        result = Gf.Range3d()
        for prim in prims:
            if prim:
                result.UnionWith(cache.ComputeWorldBound(prim).ComputeAlignedRange())
        return result

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
        self.recovered_unsaved = False
        self._runtime_state = self._state()

    def _state(self):
        return (tuple(sorted(self.stage.GetMutedLayers())),
                tuple(self.stage.GetLoadRules().GetRules()))

    @property
    def dirty(self):
        return self.recovered_unsaved or self.edits.state()["dirty"] or self._runtime_state != self._state()

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
        if name == 'edit_prims':
            return self.edit_prims(*args, **kwargs)
        if name == 'set_properties':
            return self.edit_prims([dict(name='set_property', data=item) for item in args[0]],
                                   label='Set selected properties')
        previous_selection = list(self.selection)
        restore_selection = None
        restoring_redo = kwargs.get('redo', args[0] if args and name == 'restore' else False)
        if name == 'restore':
            history = self.edits.redo if restoring_redo else self.edits.undo
            if history and len(history[-1]) > 3 and isinstance(history[-1][3], dict):
                restore_selection = history[-1][3].get('selection')
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
                       "set_transform_lock", "set_camera_view", "set_frame_range", "set_property", "set_stage_metadata",
                       "set_layer_muted", "set_sublayers", "create_sublayer", "add_arc", "apply_schema",
                       "convert_to_mesh", "bind_scene_material", "restore"}
            if name not in allowed:
                raise ValueError("Unknown document command: " + name)
            result = getattr(self.edits, name)(*args, **kwargs)
        self.revision += 1
        if restore_selection is not None:
            reverse = self.edits.undo if restoring_redo else self.edits.redo
            reverse[-1][3]['selection'] = previous_selection
            self.select(restore_selection)
            return result
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

    def edit_prims(self, operations, label='Edit selected prims'):
        """Batch property/namespace commands without partial edits or extra undo steps."""
        operations = list(operations)
        if any(op['name'] not in {'set_property', 'reparent_prim'} for op in operations):
            raise ValueError('A prim edit batch accepts property and namespace commands only.')
        layers = tuple(self.edits.track_layer(layer) for layer in self.stage.GetLayerStack())
        before = tuple(layer.ExportToString() for layer in layers)
        rules, selection = self.stage.GetLoadRules(), list(self.selection)
        undo, redo = list(self.edits.undo), list(self.edits.redo)
        revision = self.revision
        try:
            results = [self.command(op['name'], op['data']) for op in operations]
        except Exception:
            with Sdf.ChangeBlock():
                for layer, text in zip(layers, before):
                    if layer.ExportToString() != text:
                        layer.ImportFromString(text)
            self.stage.SetLoadRules(rules)
            self.select(selection)
            raise
        finally:
            self.edits.undo[:], self.edits.redo[:] = undo, redo
            self.revision = revision
        changed = [(layer, text) for layer, text in zip(layers, before) if layer.ExportToString() != text]
        if changed:
            self.edits.undo.append((label, tuple(row[0] for row in changed), tuple(row[1] for row in changed),
                                   dict(load_rules=rules, selection=selection)))
            self.edits.undo = self.edits.undo[-100:]
            self.edits.redo.clear()
            self.revision += 1
        return results

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
        self.recovered_unsaved = False
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

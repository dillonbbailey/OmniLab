"""Save one authored layer, preserving arcs and its live editing identity."""
import os
from pathlib import Path
import shutil
import tempfile

from pxr import Ar, Sdf

from .usd_layers import layer_entries
from .usd_project import anchor_asset, disk_baseline, remap_assets


def save_layer(editing, identifier, destination, retained):
    stage = editing.stage
    entries = layer_entries(stage, editing, retained.sources)
    entry = next((entry for entry in entries if entry["identifier"] == identifier), None)
    if not entry or not entry["can_save"]:
        raise ValueError("Choose a local layer that permits saving.")
    layer = editing.layer_cache[identifier]
    path = Path(destination).expanduser().resolve()
    if path.suffix.lower() not in (".usd", ".usda", ".usdc"):
        raise ValueError("Save the layer as .usd, .usda, or .usdc.")
    if not path.parent.is_dir() or path.is_dir():
        raise ValueError("Choose a USD filename in an existing directory.")
    if path.exists() and not os.access(path, os.W_OK):
        raise ValueError("The layer file is read-only: " + str(path))
    origins = {item.identifier: retained.sources.get(item.identifier) or item.realPath
               for item in [*retained, *editing.layer_cache.values()]}
    source = origins.get(identifier)
    if (not source or Path(source).resolve() != path) and any(
            other != identifier and origin and Path(origin).resolve() == path for other, origin in origins.items()):
        raise ValueError("That file belongs to another loaded layer. Choose a different filename.")
    clone = Sdf.Layer.CreateAnonymous("save-layer.usda")
    clone.TransferContent(layer)
    anchor = layer if layer.realPath else stage.GetRootLayer()
    if source and not layer.realPath:
        anchor = Sdf.Layer.FindOrOpen(source) or anchor

    def resolve(asset):
        target = origins.get(asset) or anchor_asset(anchor, asset)
        if target.startswith("anon:"):
            name = Sdf.Layer.GetDisplayNameFromIdentifier(target)
            raise ValueError("Save the in-memory dependency first: " + name)
        if target and Path(target).is_absolute() and not Ar.IsPackageRelativePath(target):
            return os.path.relpath(target, path.parent)
        return target

    # Remap copied project-layer identifiers to their tracked files. Never
    # flatten a stage or write dangling anonymous dependencies into a USD file.
    with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
        remap_assets(clone, resolve)
    fd, temporary = tempfile.mkstemp(prefix=".usd-layer-save-", suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        if not clone.Export(temporary):
            raise ValueError("USD could not save layer: " + str(path))
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    retained.sources[identifier] = str(path)
    retained.baselines[identifier] = disk_baseline(str(path), retained.identifiers)
    editing.saved[editing.track_layer(layer)] = layer.ExportToString()
    return str(path)

"""Create empty stages without importing native USD into the UI process."""
import os
from pathlib import Path
import tempfile

from pxr import Sdf, Usd
from .usd_stage_metadata import author_layer_metadata


def create_stage(path="", *, overwrite=False, metadata=None):
    root = Sdf.Layer.CreateAnonymous("Untitled.usda")
    author_layer_metadata(root, metadata or {}, defaults=True)
    stage = Usd.Stage.Open(root, Sdf.Layer.CreateAnonymous("viewer-edits.usda"))
    if not path:
        return stage, root.identifier
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() not in (".usd", ".usda", ".usdc"):
        raise ValueError("Create the stage as .usd, .usda, or .usdc.")
    if target.exists() and not overwrite:
        raise ValueError("This USD file already exists. Choose another name or confirm replacement.")
    # Write completely before replacing an existing file. Only the new root
    # layer is authored here; there is no composed or flattened export.
    fd, temporary = tempfile.mkstemp(prefix=".usd-new-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    try:
        if not root.Export(temporary):
            raise ValueError("Could not create the USD root layer.")
        if overwrite:
            os.replace(temporary, target)
        else:
            # Do not replace a file that appeared after the dialog closed.
            os.link(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    root = Sdf.Layer.FindOrOpen(str(target))
    root.Reload()
    stage = Usd.Stage.Open(root, Sdf.Layer.CreateAnonymous("viewer-edits.usda"))
    return stage, str(target.resolve())

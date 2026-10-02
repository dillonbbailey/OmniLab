"""Shared validation for the UI and the isolated USD asset publisher."""
from pathlib import Path
import re


def asset_name(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value or ""):
        raise ValueError("Use an asset name starting with a letter or underscore, followed by letters, numbers or underscores.")
    return value


def publish_destination(directory, name):
    name = asset_name(name)
    if not str(directory).strip():
        raise ValueError("Choose a publish directory.")
    parent = Path(directory).expanduser().absolute()
    if not parent.is_dir():
        raise ValueError("Choose an existing publish directory.")
    destination = parent / name
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"{destination} already exists. Choose a new asset name or directory.")
    return destination

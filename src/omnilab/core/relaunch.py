"""Durable, composition-preserving handoff to a fresh application process."""
import json
import os
from pathlib import Path
import uuid

from .document import Document, atomic_json
from omnilab.usd.usd_project import capture_stage, stage_layers


def write_checkpoint(document, workspace=None, directory=None):
    directory = Path(directory) if directory else Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'omnilab/relaunch'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (uuid.uuid4().hex + '.omnilab')
    # Inline loaded layers so edits to disk during code reload cannot alter the handoff.
    stage = capture_stage(document.stage, document.retained, inline=stage_layers(document.stage, document.retained))
    atomic_json(path, dict(format='omnilab', version=1, stage=stage,
        frame=document.frame, selection=document.selection, view=document.view,
        relaunch=dict(version=1, original_path=document.path, unsaved=bool(document.dirty), workspace=workspace or {})))
    return path


def read_checkpoint(path):
    data = json.loads(Path(path).read_text())
    state = data.get('relaunch', {})
    if state.get('version') != 1:
        raise ValueError('This file is not an OmniLab relaunch checkpoint.')
    document = Document.open(path)
    document.path = state['original_path']
    document.recovered_unsaved = bool(state['unsaved'])
    return document, state.get('workspace', {})

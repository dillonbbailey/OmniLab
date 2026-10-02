"""Versioned declarations, typed authoring and honest settings snapshots."""
from functools import lru_cache
import json
from pathlib import Path

from pxr import Sdf
from omnilab.usd.usd_editing import decode_value, encode_value

CONTROLLED = {'omni:rtx:rendermode', 'omni:rtx:pt:samplesPerPixel', 'omni:rtx:wireframe:enabled',
              'omni:rtx:wireframe:mode', 'omni:rtx:wireframe:thickness'}
ENUMS = {'selection_fill_mode': range(4), 'motion_bvh': range(3), 'texture_streaming_mode': range(3), 'aftermath_mode': range(3)}


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parents[1] / 'data/ovrtx-settings.json').read_text())


def definitions(creation=False):
    return {row['name']: row for row in catalog()['renderer_config' if creation else 'rtx_schema']}


def validate(name, value, creation=False):
    row = definitions(creation).get(name)
    if row is None:
        raise ValueError('Unknown setting; imported entries are preserved but cannot be authored without a type.')
    if creation:
        if name == 'log_file_path':
            raise ValueError('Each worker owns its diagnostic log path; inspect it through Renderer logs or Job / logs.')
        if value is None:
            return None
        expected = {'Optional[bool]': bool, 'Optional[int]': int, 'Optional[str]': str}.get(row['type'])
        if name in ENUMS:
            if type(value) is not int or value not in ENUMS[name]:
                raise ValueError(f'Use one of these enum values: {list(ENUMS[name])}.')
        elif type(value) is not expected:
            raise ValueError('Expected ' + row['type'])
        if name == 'active_cuda_gpus' and (not value or any(not part.strip().isdigit() for part in value.split(','))):
            raise ValueError('Use comma-separated CUDA device indices, for example "0" or "0,1".')
        return value
    if name in CONTROLLED:
        raise ValueError('This setting is controlled by the viewport or RenderView controls.')
    if row['allowed_tokens'] and value not in row['allowed_tokens']:
        raise ValueError('Allowed values: ' + ', '.join(map(str, row['allowed_tokens'])))
    type_name = Sdf.ValueTypeNames.Find(row['type'])
    if not type_name:
        raise ValueError('The installed OpenUSD does not provide type ' + row['type'])
    return encode_value(decode_value(type_name, value))


def apply_product(prim, values):
    known = definitions()
    for name, value in values.items():
        validated = validate(name, value)
        type_name = Sdf.ValueTypeNames.Find(known[name]['type'])
        prim.CreateAttribute(name, type_name).Set(decode_value(type_name, validated))


def export_settings(document):
    from importlib import metadata
    versions = {}
    for package in ('ovrtx', 'ovstage', 'usd-core'):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = 'unavailable'
    authored = []
    for prim in document.stage.Traverse():
        for attr in prim.GetAttributes():
            if attr.GetName().startswith('omni:rtx:') or (prim.GetTypeName() in ('RenderProduct', 'RenderSettings', 'Camera') and attr.HasAuthoredValueOpinion()):
                authored.append(dict(path=str(attr.GetPath()), type=str(attr.GetTypeName()),
                    composed_value=encode_value(attr.Get(document.frame)), effective_value='unknown',
                    layers=[spec.layer.identifier for spec in attr.GetPropertyStack(document.frame)]))
    return dict(catalog=catalog(), versions=versions, revision=document.revision, frame=document.frame,
                editor_profiles=document.view.get('rtx_settings', {}),
                renderer_creation=document.view.get('renderer_config', {}),
                viewport=document.view.get('viewport', {}), authored_stage_settings=authored,
                effective_values='unknown: the native runtime does not expose a complete effective-settings query')

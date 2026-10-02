"""MDL SDK discovery and transactional definition catalog updates."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from importlib.util import find_spec

from .catalog import Definition, Port, USD_TYPES
from pxr import Sdf


USD_TYPES['double'] = Sdf.ValueTypeNames.Double


def sdk_configuration():
    root = Path(os.environ['OMNILAB_MDL_SDK']) if os.environ.get('OMNILAB_MDL_SDK') else None
    if root is None:
        roots = sorted((Path(__file__).resolve().parents[3] / '.cache/mdl-sdk').glob('MDL-SDK-*-linux-x86-64'))
        root = roots[-1] if roots else None
    python = os.environ.get('OMNILAB_MDL_PYTHON') or shutil.which('python3.10')
    if not python and shutil.which('uv'):
        result = subprocess.run(['uv', 'python', 'find', '3.10', '--no-project'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            python = result.stdout.strip()
    if root is None or not (root / 'lib/python/pymdlsdk.py').exists() or not python:
        raise ValueError('MDL reflection needs NVIDIA MDL SDK and its matching Python bindings. Run tools/setup_mdl_sdk.py or set OMNILAB_MDL_SDK and OMNILAB_MDL_PYTHON.')
    return root.resolve(), python


def module_paths(module, search_paths=()):
    paths = [str(Path(module).resolve().parent), *map(str, search_paths)]
    spec = find_spec('ovrtx')
    if spec:
        root = Path(spec.origin).parent / 'bin/library/mdl'
        paths.extend([str(root), *[str(path) for path in root.iterdir() if path.is_dir()]])
    return list(dict.fromkeys(paths))


def reflect_module(module, search_paths=()):
    module = Path(module).expanduser().resolve()
    if not module.is_file() or module.suffix.lower() != '.mdl':
        raise ValueError('Choose an existing .mdl module.')
    root, python = sdk_configuration()
    with tempfile.TemporaryDirectory(prefix='omnilab-mdl-') as directory:
        request, output = Path(directory) / 'request.json', Path(directory) / 'result.json'
        bundle = Path(directory) / 'bundle'
        bundle.mkdir()
        request.write_text(json.dumps(dict(sdk=str(root), module=str(module), search_paths=module_paths(module, search_paths),
                                          runtime_module=str(bundle / module.name))))
        environment = dict(os.environ)
        environment['LD_LIBRARY_PATH'] = os.pathsep.join([str(Path(python).resolve().parents[1] / 'lib'),
            str(root / 'lib'), environment.get('LD_LIBRARY_PATH', '')])
        process = subprocess.run([python, str(Path(__file__).with_name('mdl_worker.py')), str(request), str(output)],
                                 capture_output=True, text=True, timeout=90, env=environment)
        if not output.exists():
            raise ValueError('MDL SDK process failed:\n' + process.stderr[-4000:])
        result = json.loads(output.read_text())
        if result['status'] != 'passed':
            raise ValueError(result.get('error', process.stderr[-4000:]))
        result['sha256'] = hashlib.sha256(module.read_bytes()).hexdigest()
        # The SDK resolves imports using the declared roots, inlines non-builtin
        # dependencies, and bundles resources. Cache the validated result by its
        # content, so a broken source reload cannot invalidate existing shaders.
        digest = hashlib.sha256()
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(bundle)).encode())
                digest.update(path.read_bytes())
        cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'omnilab/mdl' / digest.hexdigest()
        cache.mkdir(parents=True, exist_ok=True)
        for path in bundle.rglob('*'):
            if path.is_file():
                target = cache / path.relative_to(bundle)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(path, target)
        manifest = dict(format='omnilab-mdl-bundle', version=1, module=module.name,
            files={str(path.relative_to(bundle)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in bundle.rglob('*') if path.is_file()})
        from omnilab.core.document import atomic_json
        atomic_json(cache / 'omnilab_bundle.json', manifest)
        result['runtime_module'] = str(cache / module.name)
        return result


def port_type(type_name):
    type_name = type_name.replace('uniform ', '').replace('varying ', '').strip()
    return {'bool': 'boolean', 'int': 'integer', 'color': 'color3', 'float2': 'vector2',
            'float3': 'vector3', 'float4': 'vector4', 'texture_2d': 'filename',
            'texture_3d': 'filename', 'float3x3': 'matrix33', 'float4x4': 'matrix44'}.get(type_name, type_name)


def annotation_metadata(annotations):
    metadata = {'annotations': annotations}
    for name, args in annotations.items():
        if '::display_name(' in name:
            metadata['uiname'] = next(iter(args.values()), '')
        elif '::description(' in name:
            metadata['doc'] = next(iter(args.values()), '')
        elif '::in_group(' in name:
            metadata['uifolder'] = next(iter(args.values()), '')
        elif '::hard_range(' in name or '::soft_range(' in name:
            metadata['uimin'] = args.get('min')
            metadata['uimax'] = args.get('max')
    return metadata


def load_module(catalog, module, search_paths=()):
    # Nothing changes if the compiler reports errors. Keep the old definitions
    # and the current native preview available while the user fixes the source.
    report = reflect_module(module, search_paths)
    return install_module(catalog, report, search_paths), report


def install_module(catalog, report, search_paths=()):
    from collections import Counter
    names = Counter(function['name'] for function in report['definitions'])
    definitions = {}
    for function in report['definitions']:
        identifier = 'mdl:' + report['module'] + '#' + function['signature']
        inputs = {p['name']: Port(p['name'], port_type(p['type']), p['default'],
                    dict(annotation_metadata(p['annotations']), mdl_type=p['type'])) for p in function['inputs']}
        output_type = 'surfaceshader' if function['material'] else port_type(function['return_type'])
        metadata = dict(annotation_metadata(function['annotations']), module=report['module'],
                        runtime_module=report.get('runtime_module', report['module']),
                        subidentifier=function['name'], signature=function['signature'],
                        sha256=report['sha256'], search_paths=list(map(str, search_paths)), material=function['material'])
        if names[function['name']] > 1:
            metadata['unsupported'] = 'This MDL name is overloaded. Export a uniquely named wrapper before adding it to a USD graph.'
        definitions[identifier] = Definition(identifier, function['name'], metadata.get('uiname') or function['name'],
            inputs, {'out': Port('out', output_type)}, 'mdl', metadata)
    if not definitions:
        raise ValueError('The module has no exported material or function definitions.')
    for key, definition in list(catalog.definitions.items()):
        if definition.framework == 'mdl' and definition.metadata['module'] == report['module']:
            del catalog.definitions[key]
    catalog.definitions.update(definitions)
    return list(definitions.values())

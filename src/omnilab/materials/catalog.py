"""Read shader definitions from installed libraries, without copying SDK assets."""
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

import MaterialX as mx
from pxr import Sdf


USD_TYPES = {
    'float': Sdf.ValueTypeNames.Float, 'integer': Sdf.ValueTypeNames.Int,
    'boolean': Sdf.ValueTypeNames.Bool, 'string': Sdf.ValueTypeNames.String,
    'filename': Sdf.ValueTypeNames.Asset, 'color3': Sdf.ValueTypeNames.Color3f,
    'color4': Sdf.ValueTypeNames.Color4f, 'vector2': Sdf.ValueTypeNames.Float2,
    'vector3': Sdf.ValueTypeNames.Vector3f, 'vector4': Sdf.ValueTypeNames.Float4,
    'matrix33': Sdf.ValueTypeNames.Matrix3d, 'matrix44': Sdf.ValueTypeNames.Matrix4d,
    'surfaceshader': Sdf.ValueTypeNames.Token, 'displacementshader': Sdf.ValueTypeNames.Token,
    'volumeshader': Sdf.ValueTypeNames.Token, 'BSDF': Sdf.ValueTypeNames.Token,
    'EDF': Sdf.ValueTypeNames.Token, 'VDF': Sdf.ValueTypeNames.Token,
    'floatarray': Sdf.ValueTypeNames.FloatArray, 'integerarray': Sdf.ValueTypeNames.IntArray,
    'color3array': Sdf.ValueTypeNames.Color3fArray, 'vector3array': Sdf.ValueTypeNames.Vector3fArray,
    'stringarray': Sdf.ValueTypeNames.StringArray,
}


def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (mx.Matrix33, mx.Matrix44)):
        size = 3 if isinstance(value, mx.Matrix33) else 4
        return [[value[row, column] for column in range(size)] for row in range(size)]
    return [plain(part) for part in value]


@dataclass
class Port:
    name: str
    type: str
    default: object = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Definition:
    identifier: str
    category: str
    label: str
    inputs: dict
    outputs: dict
    framework: str = 'mtlx'
    metadata: dict = field(default_factory=dict)


class Catalog:
    def __init__(self, library=None):
        self.library = mx.createDocument()
        spec = find_spec('ovrtx')
        root = Path(spec.origin).parent / 'bin/library/materialx' if spec else None
        if library:
            root = Path(library)
        if root and root.is_dir():
            self.sources = sorted(mx.loadLibraries(['.'], mx.FileSearchPath(str(root)), self.library))
        else:
            self.sources = sorted(mx.loadLibraries(mx.getDefaultDataLibraryFolders(), mx.getDefaultDataSearchPath(), self.library))
        self.version = mx.getVersionString()
        self.definitions = {}
        for node in self.library.getNodeDefs():
            def port(element):
                return Port(element.getName(), element.getType(), plain(element.getValue()),
                            {key: element.getAttribute(key) for key in element.getAttributeNames()})
            self.definitions[node.getName()] = Definition(node.getName(), node.getNodeString(),
                node.getAttribute('uiname') or node.getNodeString(),
                {p.getName(): port(p) for p in node.getActiveInputs()},
                {p.getName(): port(p) for p in node.getActiveOutputs()},
                metadata={key: node.getAttribute(key) for key in node.getAttributeNames()})
        if not self.definitions:
            raise ValueError('No MaterialX NodeDefs found. Install MaterialX or configure a library directory.')

    def definition(self, identifier):
        try:
            return self.definitions[identifier]
        except KeyError:
            raise ValueError(f'Unknown shader definition: {identifier}. Its USD data is preserved.') from None

    def search(self, text='', framework=None):
        words = text.lower().split()
        return [d for d in self.definitions.values() if (framework is None or d.framework == framework)
                and all(word in (d.identifier + ' ' + d.label + ' ' + d.category).lower() for word in words)]


@lru_cache(maxsize=1)
def default_catalog():
    return Catalog()

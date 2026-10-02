"""Lossless float EXR output from explicitly supported ovRTX camera quantities."""
import json
from pathlib import Path

import numpy as np
import OpenImageIO as oiio

# These quantities have documented standalone 0.5 semantics. Integer semantic
# IDs require UINT channels and their mapping metadata, and are not float AOVs.
AOVS = {
    'HdrColor': ('RGBA', ('RealTimePathTracing', 'PathTracing')),
    'NormalSD': ('XYZA', ('RealTimePathTracing',)),
    'DistanceToCameraSD': ('Z', ('RealTimePathTracing', 'PathTracing')),
    'DistanceToImagePlaneSD': ('Z', ('RealTimePathTracing',)),
    'Camera3dPositionSD': ('XYZA', ('RealTimePathTracing',)),
}


def write_exr(path, outputs, resolution, region=None, metadata=None):
    """Write a private staging file; the job owner decides when to publish it."""
    channels, arrays = [], []
    width, height = resolution
    x0, y0, x1, y1 = region or (0, 0, width, height)
    for name, pixels in outputs.items():
        if name not in AOVS:
            raise ValueError('Unsupported EXR output: ' + name)
        pixels = np.asarray(pixels)
        if pixels.ndim == 2:
            pixels = pixels[:, :, None]
        axes = AOVS[name][0]
        if pixels.shape != (y1-y0, x1-x0, len(axes)):
            raise ValueError(f'{name} returned {pixels.shape}, expected {(y1-y0, x1-x0, len(axes))}.')
        channels.extend([axis if name == 'HdrColor' else name + '.' + axis for axis in axes])
        arrays.append(pixels.astype(np.float32))
    if not arrays:
        raise ValueError('The renderer returned no EXR outputs.')
    data = np.ascontiguousarray(np.concatenate(arrays, axis=2))
    spec = oiio.ImageSpec(x1-x0, y1-y0, len(channels), oiio.FLOAT)
    spec.channelnames = channels
    spec.x, spec.y = x0, y0
    spec.full_width, spec.full_height = width, height
    spec.attribute('compression', 'zip')
    spec.attribute('oiio:ColorSpace', 'Linear')
    spec.attribute('Software', 'OmniLab / ovRTX')
    spec.attribute('omnilab:job', json.dumps(metadata or {}, sort_keys=True))
    output = oiio.ImageOutput.create(str(path))
    try:
        if not output or not output.open(str(path), spec):
            raise ValueError('Cannot create EXR: ' + str(path))
        if not output.write_image(data) or not output.close():
            raise ValueError(output.geterror() or 'EXR write failed.')
    finally:
        if output:
            output.close()


def atomic_copy(source, destination):
    """Copy across filesystems, then atomically replace on the destination volume."""
    import os
    import shutil
    import tempfile
    destination = Path(destination)
    fd, pending = tempfile.mkstemp(prefix='.omnilab-', suffix=destination.suffix, dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream, open(source, 'rb') as incoming:
            shutil.copyfileobj(incoming, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, destination)
    finally:
        Path(pending).unlink(missing_ok=True)

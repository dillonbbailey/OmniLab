"""Immutable, isolated final jobs. Only the owner may replace user output files."""
from dataclasses import dataclass, asdict
from decimal import Decimal
import hashlib
import importlib.metadata
import math
import multiprocessing
import os
from pathlib import Path
import time
import traceback
from types import SimpleNamespace
import uuid

from omnilab.core.document import atomic_json
from .snapshot import publish
from .images import AOVS, atomic_copy
from .render_region import validate_region


def frame_range(start, end, step=1):
    start, end, step = [Decimal(str(value)) for value in (start, end, step)]
    if not all(value.is_finite() for value in (start, end, step)) or step <= 0 or end < start:
        raise ValueError('Frame range requires finite start ≤ end and a positive step.')
    count = int((end-start) // step) + 1
    if count > 10000:
        raise ValueError('A job can contain at most 10,000 frames.')
    return [float(start + i * step) for i in range(count)]


@dataclass
class JobOptions:
    output: str
    resolution: tuple = (1280, 720)
    mode: str = 'PathTracing'
    samples: int = 64
    warmup: int = 16
    aovs: tuple = ('HdrColor',)
    frames: tuple = (1.,)
    region: tuple | None = None
    purposes: tuple = ('default', 'render')

    def destinations(self):
        if (len(self.resolution) != 2 or any(type(v) is not int or not 1 <= v <= 32768 for v in self.resolution)):
            raise ValueError('Resolution must contain two whole numbers from 1 to 32768.')
        if self.mode not in ('RealTimePathTracing', 'PathTracing'):
            raise ValueError('Final rendering supports RTPT and PathTracing.')
        if type(self.samples) is not int or type(self.warmup) is not int or not 1 <= self.samples <= 1000000 or not 1 <= self.warmup <= 1024:
            raise ValueError('Use positive samples (≤1,000,000) and RTPT warmup frames (≤1024).')
        if not self.frames or len(self.frames) > 10000 or any(not math.isfinite(f) for f in self.frames):
            raise ValueError('The job requires 1–10,000 finite frame numbers.')
        if not self.aovs or len(set(self.aovs)) != len(self.aovs):
            raise ValueError('Choose unique render outputs.')
        for name in self.aovs:
            if name not in AOVS or self.mode not in AOVS[name][1]:
                raise ValueError(f'{name} is not a validated output in {self.mode}.')
        validate_region(self.region, *self.resolution)
        result = []
        for frame in self.frames:
            number = int(frame) if float(frame).is_integer() else frame
            try:
                path = Path(self.output.format(frame=number)).expanduser().absolute()
            except (KeyError, ValueError, IndexError) as exc:
                raise ValueError('Use {frame} in sequence filenames; integer formats require whole frames.') from exc
            if path.suffix.lower() != '.exr' or not path.parent.is_dir():
                raise ValueError('Output must be an EXR in an existing directory.')
            if path.exists() and not path.is_file():
                raise ValueError('The output path is not a regular file.')
            result.append(str(path))
        if len(set(result)) != len(result):
            raise ValueError('Each frame needs a unique filename; include {frame} in the output path.')
        return result


def prepare_job(document, camera_at, options, directory):
    """Called on the document owner thread before native work starts."""
    destinations = options.destinations()
    directory = Path(directory).absolute() / uuid.uuid4().hex
    directory.mkdir(parents=True)
    snapshots = []
    # Freeze the composed document once. Each sample camera is captured while
    # the authoring thread owns the stage; subsequent edits cannot affect it.
    from pxr import Usd
    frozen = Usd.Stage.Open(document.stage.Flatten())
    for index, frame in enumerate(options.frames):
        source = SimpleNamespace(stage=frozen, frame=frame, view=document.view)
        snapshot = publish(source, directory / str(index), camera_at(frame), options.resolution,
            options.mode, options.samples, options.purposes, options.aovs, region=options.region, profile='final')
        snapshot['sha256'] = hashlib.sha256(Path(snapshot['path']).read_bytes()).hexdigest()
        snapshots.append(snapshot)
    versions = {}
    for package in ('ovrtx', 'ovstage', 'usd-core', 'MaterialX', 'OpenImageIO'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = 'unavailable'
    job = dict(id=directory.name, directory=str(directory), revision=document.revision,
        source=document.path, options=asdict(options), destinations=destinations,
        snapshots=snapshots, versions=versions, created=time.time(), state='prepared', completed=[])
    atomic_json(directory / 'job.json', job)
    return job


def render_worker(connection, job):
    directory = Path(job['directory'])
    fd = os.open(directory / 'worker.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    backend = None
    try:
        from .backend import Backend
        from .images import write_exr
        from .render_region import merge_region
        connection.send(dict(type='status', text='Initializing ovRTX'))
        backend = Backend(directory / 'ovrtx.log', job['snapshots'][0].get('renderer_config', {}))
        calibration = None
        if job.get('calibration'):
            import numpy as np
            connection.send(dict(type='status', text='Calibrating linear map output'))
            backend.load(job['calibration'])
            outputs, _, _ = backend.render()
            calibration = outputs['HdrColor'][8:-8, 8:-8, :3].astype(np.float32).mean(axis=(0, 1))
            if not np.isfinite(calibration).all() or np.any(calibration <= 0):
                raise ValueError('The renderer did not produce a valid unit-emission reference; no bake was saved.')
        for index, snapshot in enumerate(job['snapshots']):
            connection.send(dict(type='status', index=index, text=f'Publishing frame {snapshot["frame"]:g}'))
            backend.load(snapshot)
            steps = job['options']['warmup'] if snapshot['mode'] == 'RealTimePathTracing' else 1
            for step in range(steps):
                connection.send(dict(type='status', index=index,
                    text=f'Rendering frame {snapshot["frame"]:g}' + (f' · temporal frame {step+1}/{steps}' if steps > 1 else '')))
                outputs, _, milliseconds = backend.render()
            cameras = snapshot.get('bake_cameras')
            if cameras and len(cameras) > 1:
                import numpy as np
                accumulated = None
                for sample, camera in enumerate(cameras):
                    connection.send(dict(type='status', index=index, text=f'Baking temporal sample {sample+1}/{len(cameras)}'))
                    backend.update_camera(camera)
                    arrays, _, milliseconds = backend.render()
                    values = arrays['HdrColor'].astype(np.float32)
                    accumulated = values / len(cameras) if accumulated is None else accumulated + values / len(cameras)
                outputs = {'HdrColor': accumulated}
            if calibration is not None:
                import numpy as np
                outputs['HdrColor'] = outputs['HdrColor'].astype(np.float32)
                outputs['HdrColor'][:, :, :3] /= calibration
            missing = set(job['options']['aovs']) - outputs.keys()
            if missing:
                raise ValueError('ovRTX did not produce: ' + ', '.join(sorted(missing)))
            path = directory / str(index) / 'completed.exr'
            write_exr(path, {name: outputs[name] for name in job['options']['aovs']}, snapshot['resolution'],
                      snapshot['region'], dict(job_id=job['id'], revision=job['revision'], versions=job['versions'],
                          render={key: value for key, value in snapshot.items() if key not in ('path', 'bake_cameras')}))
            if snapshot['region']:
                baseline = job['destinations'][index]
                merge_region(path, baseline if Path(baseline).is_file() else None, snapshot['region'], *snapshot['resolution'])
            connection.send(dict(type='frame_ready', index=index, path=str(path), milliseconds=milliseconds))
            # Bounded handoff. The worker never writes a user's final filename.
            if connection.recv().get('type') != 'accepted':
                return
        connection.send(dict(type='complete'))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException:
        detail = traceback.format_exc()
        connection.send(dict(type='error', text=detail))
        print(detail, flush=True)
    finally:
        if backend is not None:
            backend.close()
        connection.close()


class RenderJob:
    """Poll/cancel on one owner thread; no queued event may commit after cancel."""
    def __init__(self, job, worker=render_worker):
        self.data = job
        self.worker = worker
        self.process = None
        self.connection = None
        self.active = False

    def save(self):
        atomic_json(Path(self.data['directory']) / 'job.json', self.data)

    def start(self):
        if self.process is not None:
            raise ValueError('This job has already started.')
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=self.worker, args=(child, self.data), daemon=True)
        self.process.start()
        child.close()
        self.active = True
        self.data['state'] = 'running'
        self.save()

    def poll(self):
        events = []
        if not self.active:
            return events
        try:
            while self.connection.poll():
                event = self.connection.recv()
                if event['type'] == 'frame_ready':
                    index = event['index']
                    if index != len(self.data['completed']):
                        raise ValueError('Final job returned an unexpected frame index.')
                    expected = Path(self.data['directory']) / str(index) / 'completed.exr'
                    if Path(event['path']) != expected:
                        raise ValueError('Final job returned an unexpected staging file.')
                    destination = self.data['destinations'][index]
                    atomic_copy(expected, destination)
                    self.data['completed'].append(dict(index=index, path=destination, frame=self.data['snapshots'][index]['frame']))
                    self.save()
                    self.connection.send(dict(type='accepted'))
                    event = dict(event, type='frame', path=destination)
                elif event['type'] in ('complete', 'error'):
                    if event['type'] == 'complete' and len(self.data['completed']) != len(self.data['snapshots']):
                        raise ValueError('Final job ended before all frames were published.')
                    self.finish('complete' if event['type'] == 'complete' else 'failed', event.get('text', ''))
                events.append(event)
                if not self.active:
                    break
            if self.active and not self.process.is_alive() and not self.connection.poll():
                raise RuntimeError('Render worker exited unexpectedly. See the saved job logs.')
        except (OSError, EOFError, ValueError, RuntimeError) as exc:
            self.finish('failed', str(exc))
            events.append(dict(type='error', text=str(exc)))
        return events

    def finish(self, state, error=''):
        self.active = False
        self.data.update(state=state, error=error, ended=time.time())
        self.save()
        self.stop_process()

    def stop_process(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
            self.process.close()
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def cancel(self):
        if self.active:
            self.finish('cancelled')

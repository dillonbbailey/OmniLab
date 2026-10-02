import time
from pathlib import Path

import numpy as np
import OpenImageIO as oiio
import pytest
from pxr import Usd, UsdGeom

from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera
from omnilab.render.jobs import JobOptions, RenderJob, prepare_job, frame_range
from omnilab.render.images import write_exr


def fake_worker(connection, job):
    for index, snapshot in enumerate(job['snapshots']):
        if index == 1 and job.get('fail_second'):
            connection.send(dict(type='error', text='Intentional frame failure'))
            return
        path = Path(job['directory']) / str(index) / 'completed.exr'
        path.write_bytes(b'completed image')
        connection.send(dict(type='frame_ready', index=index, path=str(path)))
        connection.recv()
    connection.send(dict(type='complete'))


def make_job(tmp_path, frames=(1.,)):
    document = demo_document()
    camera = ViewCamera().camera(1)
    data = prepare_job(document, lambda _: camera,
        JobOptions(str(tmp_path / 'frame.{frame}.exr'), resolution=(8, 8), frames=frames), tmp_path / 'jobs')
    return RenderJob(data, fake_worker)


def test_cancel_before_accept_never_replaces_output(tmp_path):
    job = make_job(tmp_path)
    destination = Path(job.data['destinations'][0])
    destination.write_bytes(b'old image')
    job.start()
    assert job.connection.poll(10), 'Worker must have a completed frame queued before cancellation.'
    job.cancel()
    assert job.poll() == []
    assert destination.read_bytes() == b'old image'
    assert job.data['state'] == 'cancelled'


def test_failure_preserves_completed_frames_and_other_baselines(tmp_path):
    job = make_job(tmp_path, (1., 2.))
    job.data['fail_second'] = True
    paths = [Path(path) for path in job.data['destinations']]
    for path in paths:
        path.write_bytes(b'old image')
    job.start()
    deadline = time.monotonic() + 10
    while job.active and time.monotonic() < deadline:
        job.poll()
        time.sleep(.01)
    assert not job.active
    assert job.data['state'] == 'failed'
    assert paths[0].read_bytes() == b'completed image'
    assert paths[1].read_bytes() == b'old image'
    assert len(job.data['completed']) == 1


def test_job_snapshot_is_immutable_fractional_and_aovs_are_mode_checked(tmp_path):
    assert frame_range(.1, .4, .1) == [.1, .2, .3, .4]
    document = demo_document()
    options = JobOptions(str(tmp_path/'frame.{frame}.exr'), frames=(1.25, 1.5))
    job = prepare_job(document, lambda _: ViewCamera().camera(1), options, tmp_path/'jobs')
    document.stage.RemovePrim('/World/Sphere')
    for snapshot in job['snapshots']:
        frozen = Usd.Stage.Open(snapshot['path'])
        assert frozen.GetPrimAtPath('/World/Sphere')
    assert [s['frame'] for s in job['snapshots']] == [1.25, 1.5]
    options.output = str(tmp_path/'same.exr')
    with pytest.raises(ValueError, match='unique'):
        options.destinations()
    options.output = str(tmp_path/'frame.{frame}.exr')
    options.aovs = ('NormalSD',)
    with pytest.raises(ValueError, match='not a validated'):
        options.destinations()


def test_exr_keeps_hdr_negative_infinite_and_aov_values(tmp_path):
    values = np.array([[[12.5, -.75, np.inf, 1.], [.2, .3, .4, .5]]], dtype=np.float32)
    output = tmp_path/'hdr.exr'
    write_exr(output, {'HdrColor': values, 'DistanceToCameraSD': np.array([[25., 0.]], np.float32)}, (2, 1))
    image = oiio.ImageInput.open(str(output))
    try:
        channels = list(image.spec().channelnames)
        result = image.read_image()
    finally:
        image.close()
    assert result[0, 0, channels.index('R')] == 12.5
    assert result[0, 0, channels.index('G')] == -.75
    assert np.isinf(result[0, 0, channels.index('B')])
    assert result[0, 0, channels.index('DistanceToCameraSD.Z')] == 25.

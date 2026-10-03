"""Exercise scheduling without a GPU or either UI toolkit."""

from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera
from omnilab.render.session import InteractiveSession


class Bridge:
    def __init__(self):
        self.incoming = []
        self.sent = []

    def poll(self):
        events, self.incoming = self.incoming, []
        return events

    def send(self, data):
        self.sent.append(data)

    def stop(self):
        pass


def test_one_inflight_and_camera_reuses_snapshot():
    document = demo_document()
    camera = ViewCamera()
    frames = []
    session = InteractiveSession(lambda: (document, camera.camera(1.6)), frames.append)
    session.bridge = Bridge()
    session.enabled = session.ready = True
    try:
        session.invalidate()
        session.tick()
        first = session.submitted
        snapshot = session.bridge.sent[-1]["snapshot"]
        for _ in range(10):
            camera.orbit(2, 0)
            session.invalidate(camera_only=True)
            session.tick()
        assert len(session.bridge.sent) == 1
        session.bridge.incoming = [dict(type="frame", request=first)]
        session.tick()
        assert frames == [dict(type="frame", request=first)]
        assert session.bridge.sent[-1]["snapshot"] == snapshot
        assert session.publications == 1
        assert session.submitted == session.request
    finally:
        session.close()


def test_structural_floor_and_stale_pick():
    document = demo_document()
    frames = []
    picks = []
    session = InteractiveSession(
        lambda: (document, ViewCamera().camera(1)),
        frames.append,
        on_pick=lambda *v: picks.append(v),
    )
    session.bridge = Bridge()
    session.enabled = session.ready = True
    try:
        session.invalidate()
        session.tick()
        first = session.submitted
        session.invalidate()
        session.bridge.incoming = [
            dict(type="frame", request=first, hits=[dict(path="/World/Cube")])
        ]
        session.tick()
        assert not frames and not picks
        assert session.publications == 2
        latest = session.submitted
        session.bridge.incoming = [
            dict(type="frame", request=latest, hits=[dict(path="/World/Cube")])
        ]
        session.tick()
        assert len(frames) == len(picks) == 1
    finally:
        session.close()


def test_publication_failure_stops_instead_of_retrying_every_ui_frame():
    calls = []
    status = []

    def broken_scene():
        calls.append(True)
        raise ValueError("Missing camera")

    session = InteractiveSession(broken_scene, lambda event: None, status.append)
    session.bridge = Bridge()
    session.enabled = session.ready = True
    try:
        session.tick()
        session.tick()
        assert calls == [True]
        assert not session.enabled
        assert session.error == "Missing camera"
        assert "Restart" in status[-1]
    finally:
        session.close()

"""Single persistent native renderer with bounded, acknowledged CPU frames."""
import os
from pathlib import Path
import traceback


def run(connection, directory):
    directory = Path(directory)
    # Native libraries write directly to stdout/stderr; keep diagnostics off the transport.
    fd = os.open(directory / "worker.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    backend = None
    try:
        connection.send(dict(type="status", text="Initializing ovRTX; first-run shader compilation can take several minutes."))
        from .backend import Backend
        backend = Backend(directory / "ovrtx.log")
        connection.send(dict(type="ready"))
        snapshot = None
        current = None
        remaining = 0
        awaiting_ack = False
        pending_pick = None
        while True:
            if not remaining or awaiting_ack:
                if not connection.poll(.05):
                    continue
            messages = []
            while connection.poll():
                messages.append(connection.recv())
            for message in messages:
                kind = message["type"]
                if kind == "stop":
                    return
                if kind == "ack":
                    awaiting_ack = False
                elif kind == "view":
                    current = message
                    pending_pick = None
                    remaining = 8 if message["snapshot"]["mode"] == "RealTimePathTracing" else 1
                elif kind == "pick" and current and message["request"] == current["request"]:
                    pending_pick = message
                    remaining = max(remaining, 1)
            if not current or not remaining or awaiting_ack:
                continue
            request = current["request"]
            if snapshot != current["snapshot"]["path"]:
                connection.send(dict(type="status", text="Publishing USD to ovRTX…", request=request))
                ms = backend.load(current["snapshot"])
                snapshot = current["snapshot"]["path"]
                applied_deltas = {}
                connection.send(dict(type="loaded", request=request, path=snapshot, milliseconds=ms))
                last_camera = current["snapshot"]["camera_data"]
            if last_camera != current["camera"]:
                backend.update_camera(current["camera"])
                last_camera = current["camera"]
            edits = [edit for key, edit in current.get("deltas", {}).items() if applied_deltas.get(key) != edit]
            if edits:
                backend.update_attributes(edits)
                applied_deltas = dict(current["deltas"])
            if backend.selection != current["selection"]:
                backend.set_selection(current["selection"])
            connection.send(dict(type="render_started", request=request))
            outputs, hits, ms = backend.render(pending_pick["rect"] if pending_pick else None)
            pixels = outputs["LdrColor"]
            connection.send(dict(type="frame", request=request, shape=pixels.shape,
                                 pixels=pixels.tobytes(), milliseconds=ms, ordinal=backend.ordinal,
                                 hits=hits if pending_pick else None,
                                 additive=pending_pick.get("additive", False) if pending_pick else False))
            pending_pick = None
            remaining -= 1
            awaiting_ack = True
    except (EOFError, BrokenPipeError):
        pass
    except BaseException:
        detail = traceback.format_exc()
        try:
            connection.send(dict(type="error", text=detail))
        except (EOFError, BrokenPipeError, OSError):
            pass
        print(detail, flush=True)
    finally:
        if backend is not None:
            backend.close()
        connection.close()

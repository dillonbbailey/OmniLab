"""Toolkit-neutral, cancellable console owner for standalone frontends."""

import multiprocessing
from pathlib import Path
import tempfile
import time
import uuid
from .console import run_worker, snapshot, apply_result


class ConsoleSession:
    def __init__(self, document, changed, output):
        self.document, self.changed, self.output = document, changed, output
        self.process = None
        self.running = False
        self.scratch = tempfile.TemporaryDirectory(prefix="omnilab-console-")
        self.cancel_path = Path(self.scratch.name) / "cancel"

    def run(self, code):
        if self.running:
            raise ValueError("A Python cell is already running.")
        if self.process is None or not self.process.is_alive():
            self.reset()
            context = multiprocessing.get_context("spawn")
            self.connection, child = context.Pipe()
            self.process = context.Process(
                target=run_worker, args=(child,), daemon=True
            )
            self.process.start()
            child.close()
        self.owner = self.document()
        self.before = snapshot(self.owner)
        self.cancel_path.unlink(missing_ok=True)
        self.cancelled_at = None
        self.connection.send(
            dict(
                type="execute",
                id=uuid.uuid4().hex,
                stage=self.before,
                frame=self.owner.frame,
                selection=self.owner.selection,
                code=code,
                cancel=str(self.cancel_path),
            )
        )
        self.running = True

    def tick(self):
        if not self.running:
            return
        try:
            while self.connection.poll():
                message = self.connection.recv()
                if message.get("text"):
                    self.output(message["text"])
                if message["type"] == "finished":
                    if message["status"] == "ok" and self.cancelled_at is None:
                        if self.document() is not self.owner:
                            raise ValueError(
                                "The document changed; Python result discarded."
                            )
                        apply_result(self.owner, self.before, message)
                        self.changed()
                    self.output("Cell " + message["status"])
                    self.running = False
                    break
            if (
                self.running
                and self.cancelled_at
                and time.monotonic() - self.cancelled_at > 0.5
            ):
                self.reset()
                self.output("Stopped native call; USD edits were not committed.")
            elif self.running and not self.process.is_alive():
                raise RuntimeError("Python worker exited; Run starts a fresh context.")
        except Exception as error:
            self.output(str(error))
            self.reset()

    def stop(self):
        if self.running:
            self.cancelled_at = time.monotonic()
            self.cancel_path.touch()

    def reset(self):
        self.running = False
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
            self.process.close()
            self.connection.close()
            self.process = None

    def close(self):
        self.reset()
        self.scratch.cleanup()

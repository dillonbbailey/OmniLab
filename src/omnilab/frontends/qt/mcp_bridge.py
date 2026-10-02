"""Private opt-in socket endpoint; document operations remain on the Qt thread."""
import json
import os
import uuid
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from omnilab.automation.mcp_transport import MAX_MESSAGE, runtime_dir
from .mcp_controller import EditorController

class EditorBridge(QObject):
    closed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.editor_id = uuid.uuid4().hex[:16]
        self.controller = None
        self._closed = False
        self.descriptor = self.socket_path = None
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.setMaxPendingConnections(16)
        self.connections = {}
        self.server.newConnection.connect(self.accept)
        try:
            self.directory = runtime_dir()
            self.descriptor = self.directory / (self.editor_id + ".json")
            self.socket_path = self.directory / (self.editor_id + ".sock")
            if len(os.fsencode(self.socket_path)) > 100:
                raise ValueError("MCP runtime path is too long; set OMNILAB_MCP_DIR to a shorter private directory")
            if not self.server.listen(str(self.socket_path)):
                raise ValueError(self.server.errorString())
            with self.descriptor.open("x") as file:
                os.chmod(self.descriptor, 0o600)
                json.dump({"editor_id": self.editor_id, "pid": os.getpid(), "socket": str(self.socket_path)}, file)
            self.controller = EditorController(window, self.editor_id)
        except Exception:
            self.close()
            self.deleteLater()
            raise

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.connections[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self.read(s))
            socket.disconnected.connect(lambda s=socket: self.disconnected(s))
            timer = QTimer(socket)
            timer.setSingleShot(True)
            # Accepted sockets are C++-created: a direct abort connection makes
            # PySide attempt unsupported dynamic-slot registration on them.
            timer.timeout.connect(lambda s=socket: s.abort())
            timer.start(10000)
            self.read(socket)

    def read(self, socket):
        if socket not in self.connections:
            return
        buffer = self.connections[socket]
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_MESSAGE:
            self.respond(socket, {"error": "Request exceeds the 8 MiB limit"})
            return
        if b"\n" not in buffer:
            return
        try:
            payload = json.loads(bytes(buffer).split(b"\n", 1)[0])
            if not isinstance(payload, dict) or not isinstance(payload.get("method"), str) or not isinstance(payload.get("params", {}), dict):
                raise ValueError("Expected a method and parameter object")
            result = self.controller.dispatch(payload["method"], payload.get("params", {}))
            response = {"result": result}
        except Exception as exc:
            response = {"error": str(exc) or type(exc).__name__}
        self.respond(socket, response)

    def respond(self, socket, payload):
        self.connections.pop(socket, None)
        try:
            message = json.dumps(payload, allow_nan=False).encode() + b"\n"
        except (TypeError, ValueError):
            message = b'{"error":"Could not serialize the editor response"}\n'
        if len(message) > MAX_MESSAGE:
            message = b'{"error":"Response exceeds the 8 MiB limit"}\n'
        socket.write(message)
        socket.disconnectFromServer()

    def disconnected(self, socket):
        self.connections.pop(socket, None)
        socket.deleteLater()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.server.close()
        for socket in self.server.findChildren(QLocalSocket):
            socket.abort()
        self.connections.clear()
        if self.controller is not None:
            self.controller.close()
        try:
            for path in (self.descriptor, self.socket_path):
                if path is not None:
                    path.unlink(missing_ok=True)
        finally:
            self.closed.emit()

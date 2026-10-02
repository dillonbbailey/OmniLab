"""Private local-socket discovery and async client; no Qt or MCP SDK imports."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import stat

MAX_MESSAGE = 8 * 1024 * 1024


class BridgeError(RuntimeError):
    pass


def runtime_dir():
    override = os.environ.get("OMNILAB_MCP_DIR")
    # GUI launchers and stdio clients often inherit different XDG environments.
    # Use a stable per-user address so both always discover the same editors.
    base = Path(override) if override else Path("/tmp") / f"omnilab-{os.getuid()}"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = base.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BridgeError(f"MCP runtime directory must be owned by you and private (mode 0700): {base}")
    return base.resolve()


def read_endpoint(editor_id):
    if not re.fullmatch(r"[a-f0-9]{16}", editor_id):
        raise BridgeError("Invalid editor_id; use list_editors")
    path = runtime_dir() / (editor_id + ".json")
    try:
        endpoint = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise BridgeError(f"Editor {editor_id} is unavailable; use list_editors") from exc
    socket = runtime_dir() / (editor_id + ".sock")
    if endpoint.get("editor_id") != editor_id or endpoint.get("socket") != str(socket):
        raise BridgeError("Invalid editor connection descriptor")
    return endpoint


async def request(editor_id, method, params=None, timeout=10):
    endpoint = read_endpoint(editor_id)
    async def exchange():
        reader, writer = await asyncio.open_unix_connection(endpoint["socket"], limit=MAX_MESSAGE)
        try:
            message = json.dumps({"method": method, "params": params or {}}, allow_nan=False).encode() + b"\n"
            if len(message) > MAX_MESSAGE:
                raise BridgeError("Request exceeds the 8 MiB limit")
            writer.write(message)
            await writer.drain()
            response = await reader.readline()
            if not response:
                raise BridgeError("The editor closed the connection")
            payload = json.loads(response)
            if "error" in payload:
                raise BridgeError(payload["error"])
            return payload["result"]
        finally:
            writer.close()
            await writer.wait_closed()
    try:
        return await asyncio.wait_for(exchange(), timeout)
    except (OSError, asyncio.TimeoutError) as exc:
        raise BridgeError(f"Cannot reach editor {editor_id}; it may be closed or busy") from exc


async def editors():
    async def probe(path):
        try:
            return await request(path.stem, "get_state", timeout=1)
        except (BridgeError, ValueError):
            return None
    found = await asyncio.gather(*(probe(p) for p in runtime_dir().glob("*.json")))
    return [item for item in found if item is not None]


async def resolve_editor(editor_id=None):
    chosen = editor_id or os.environ.get("OMNILAB_SESSION")
    if chosen:
        read_endpoint(chosen)
        return chosen
    found = await editors()
    if not found:
        raise BridgeError("No reachable OmniLab editor. Click Start MCP in an open window.")
    if len(found) != 1:
        raise BridgeError("Multiple editors are open. Use list_editors and pass editor_id explicitly.")
    return found[0]["editor_id"]


async def call(method, params=None, editor_id=None):
    return await request(await resolve_editor(editor_id), method, params)

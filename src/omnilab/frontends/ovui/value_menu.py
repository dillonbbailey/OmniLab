"""Native value menus with a durable system clipboard owner."""

import atexit
import json
import select
import subprocess
import sys
import omni.ui as ui
from omnilab.usd.property_actions import copy_text

_clipboard = None


def close_clipboard():
    global _clipboard
    if _clipboard is not None:
        if not _clipboard.stdin.closed:
            _clipboard.stdin.close()
        if _clipboard.poll() is None:
            try:
                _clipboard.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _clipboard.kill()
                _clipboard.wait()
        _clipboard.stdout.close()
        _clipboard = None


atexit.register(close_clipboard)


def copy_value(value):
    global _clipboard
    # The pinned ovUI wheel exposes only a test-only clipboard setter that
    # replaces the OS clipboard with an in-memory buffer. Use the existing Qt
    # dependency in a small child process; ovUI itself remains free of Qt.
    if _clipboard is None or _clipboard.poll() is not None:
        close_clipboard()
        _clipboard = subprocess.Popen(
            [sys.executable, "-m", "omnilab.frontends.qt.clipboard_service"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
    _clipboard.stdin.write(json.dumps(copy_text(value)) + "\n")
    _clipboard.stdin.flush()
    if (
        not select.select([_clipboard.stdout], [], [], 3)[0]
        or _clipboard.stdout.readline().strip() != "ok"
    ):
        close_clipboard()
        raise RuntimeError("The system clipboard could not be updated.")


def value_menu(value, x, y, safe=lambda fn: fn()):
    menu = ui.Menu("Property value")
    with menu:
        ui.MenuItem(
            "Copy values", triggered_fn=lambda: safe(lambda: copy_value(value()))
        )
    menu.show_at(x, y)
    return menu


def install_value_menu(widget, value, safe=lambda fn: fn()):
    # Retain the popup in the callback closure for the lifetime of this field.
    active = []

    def released(x, y, button, modifiers):
        if button == 1:
            active[:] = [value_menu(value, x, y, safe)]

    widget.set_mouse_released_fn(released)

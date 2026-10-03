"""Standalone ovUI entry point. The default ``omnilab`` command remains Qt."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="OmniLab standalone ovUI USD editor")
    parser.add_argument("scene", nargs="?")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--reset-layout", action="store_true")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Enable the optional localhost NVIDIA inspector",
    )
    args = parser.parse_args()
    try:
        import omni.ui as ui
    except ImportError:
        parser.error(
            "Install the optional frontend with: uv sync --extra ovui --extra rtx"
        )
    if args.scene:
        args.scene = str(Path(args.scene).expanduser().resolve())
    # ovUI stores imgui.ini in cwd. Keep that state out of scene repositories.
    config = (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "omnilab/ovui"
    )
    config.mkdir(parents=True, exist_ok=True)
    os.chdir(config)
    from .workspace import Workspace

    ui.init("OmniLab — ovUI", 1440, 900)
    if min(ui.standalone.get_window_size()) <= 0:
        parser.error(
            "ovUI could not create a window. Check DISPLAY and OpenGL availability."
        )
    from .layout import initialize_layout
    from .appearance import Appearance
    from .style import apply_style

    initialize_layout(args.reset_layout)
    appearance = Appearance.load()
    apply_style(appearance)
    app = Workspace(args, appearance)
    try:
        ui.run(app.run())
    finally:
        app.close()
    if app.failure:
        raise RuntimeError(app.failure)


if __name__ == "__main__":
    main()

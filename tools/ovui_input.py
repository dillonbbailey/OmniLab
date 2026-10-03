#!/usr/bin/env python3
"""Record one real Inspector input between screenshots; never executes Python in the app.

Example: uv run python tools/ovui_input.py --name select-cube click 620 535
Set OVUI_REPO to the pinned NVIDIA ovui checkout (see docs/P6_STATUS.md).
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", default="artifacts/p6/input")
    parser.add_argument("--settle", type=float, default=0.5)
    parser.add_argument("action", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(os.environ.get("OVUI_REPO", ".cache/ovui-source"))
    cli = root / "skills/omniverse-ui-inspector/scripts/ovui-inspect.py"
    directory = Path(args.output) / args.name
    directory.mkdir(parents=True, exist_ok=True)

    def run(*command):
        output = subprocess.check_output(
            [sys.executable, str(cli), *command], text=True
        )
        return json.loads(output)

    run("screenshot", "--out", str(directory / "before.png"))
    result = run(*args.action) if args.action else {}
    time.sleep(max(0, min(5, args.settle)))
    run("screenshot", "--out", str(directory / "after.png"))
    state = run("state", "--out", str(directory / "state.json"))
    (directory / "action.json").write_text(
        json.dumps(dict(action=args.action, result=result), indent=2) + "\n"
    )
    summary = state.get("state", {})
    print(
        json.dumps(
            dict(
                screenshot=str((directory / "after.png").absolute()),
                state={
                    key: summary.get(key)
                    for key in (
                        "revision",
                        "selection",
                        "undo",
                        "redo",
                        "render",
                        "preview",
                        "final",
                        "console_output",
                    )
                },
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

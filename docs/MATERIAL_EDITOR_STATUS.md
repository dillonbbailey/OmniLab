# Qt Material Editor layout and relaunch

2026-10-03. A live OmniPBR inspector was forcing the Material Editor to **3695 × 960** because the complete MDL function signature contributed to the label's minimum width. The signature now elides inside the inspector, with its full text available on hover. Library, graph, inspector and preview have independent splitter sizes. Preview images scale when the panel changes size. Initial graph framing waits for layout and avoids enlarging a single node beyond its normal size.

**OpenPBR**, **MDL** and **MaterialX** have separate creation/import menus and node-library tabs. The inspector identifies the selected node's family and retains its framework's parameter groups. OpenPBR remains authored through MaterialX; the extra section organizes its surface and helper definitions separately. Numeric display is compact while the tooltip and raw editor retain full precision.

![MDL properties and native ovRTX studio at 1480 × 900](evidence/material-layout.png)

## Relaunch

Use **File → Relaunch OmniLab**, or **Material Editor → Tools → Relaunch OmniLab**, after changing application code. It writes a private `.omnilab` checkpoint, launches the same Python environment and shuts down the old window's workers. The new process restores the current USD document, unsaved status, original save destination, selection/time, view settings, material tabs/studios and console text. It does not execute restored console text. Undo history and Python execution state start fresh; renderer processes are recreated. Active Python cells/final renders must finish or be stopped first, and an MDL load must finish.

Checkpoints remain under `$XDG_CACHE_HOME/omnilab/relaunch` (normally `~/.cache/omnilab/relaunch`) and can also be opened as ordinary projects for recovery. The original scene file is unchanged. A process-spawn failure keeps the old window open. If a subsequent startup fails because of a code error, the checkpoint is retained for recovery after repairing the code. Windows already running older code need one normal save-and-restart to acquire the new action.

## Validation

- **149 tests passed**: long reflected MDL identifiers and large preview images cannot force the tested window wider; framework filtering, checkpoint composition/edit-target/mute state, clean/dirty/untitled recovery, original-file preservation, active material tab, console text and spawn-failure behavior are covered.
- An isolated native X display exercised the actual reflected OmniPBR definition (463-character identifier), native ovRTX preview, node selection and all three framework tabs. The editor remained **1480 × 900**, then **1300 × 800**, with usable graph, properties and preview. [Layout measurements](evidence/material-layout.json).
- The existing native material replay passed library node creation, port dragging, preview updates, camera navigation, material tab isolation and a UDIM thumbnail. [Replay result](evidence/material-layout-regression.json).
- A mouse click on the real File-menu action launched a separate `python -m omnilab.app --resume-session … --no-render` process. The original window closed; the replacement showed its dirty document title and reopened Material Editor. The checkpoint retained edits, save path, selection/time and console text without executing it. Unit tests also inspect the restored widgets directly. [Restart result](evidence/relaunch.json).

Reproduce CPU checks with `.venv/bin/python -m pytest -q`. On an isolated X display (for example, Xvfb at 1600 × 1000), run:

```bash
.venv/bin/python tools/replay_material_layout.py
.venv/bin/python tools/replay_material_editor.py
.venv/bin/python tools/replay_relaunch.py
```

The first two need the installed RTX runtime and an NVIDIA GPU; the layout replay additionally uses the optional MDL SDK adapter. Relaunch acceptance uses `xwininfo` and `xprop` and terminates only its own replacement process. Full captures and test projects are under ignored `artifacts/`. These changes target Qt; the existing [ovUI scope and remaining differences](P6_STATUS.md) still apply.

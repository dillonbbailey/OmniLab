# OmniLab

A Qt USD editor using NVIDIA ovstage and ovRTX, with MaterialX/OpenPBR and native MDL material graphs, interactive previews and a final RenderView. The P2–P5 core workflows are implemented; [release-parity limits](docs/P2_P5_STATUS.md) remain explicit.

The agreed direction is **Qt first, ovUI second**, with one shared document/command core. OpenUSD owns editable documents and composition; isolated workers own **ovstage + ovRTX**. **ovUI is P6** and **MoonRay graph conversion is P7, low priority**.

## Run

Linux x86_64, Python 3.12 and a supported NVIDIA RTX GPU/driver are required for rendering. Authoring can run without the renderer.

```bash
uv sync --python 3.12 --extra rtx --extra dev
.venv/bin/omnilab --demo
.venv/bin/omnilab /path/to/scene.usda
.venv/bin/omnilab --no-render --demo
```

The editor retains USD layers, edit targets, transforms, typed properties, composition arcs, variants, bindings, undo/redo and composition-preserving saves. `.omnilab` projects also retain session layers, mute/load state, material tabs/studios and renderer settings. Asset publishing is a separate composed-content operation.

- **Viewport:** Alt+left drag orbits, middle drag pans, wheel dollies. F frames selection; Shift+F frames all. W/E/R select transform tools. Drag previews immediately, release commits one edit, Escape cancels. **Edit camera** makes navigation author the selected USD camera. View → Restart renderer recovers without discarding edits.
- **Display:** Shaded, native Shaded Wireframe, native Unlit Wireframe, Wire over Shaded, and Points. The latter two use native depth with bounded CPU mesh overlays; see their geometry limits in the status document.
- **Material Editor (Ctrl+M):** OpenPBR/MaterialX nodes, typed port dragging, grouped inputs, bindings, `.mtlx` import/export and graph-local undo. Start Preview for the native studio. Drag the preview to orbit; middle drag pans; wheel dollies. Tools provides map/blur baking and live/frozen camera projectors.
- **RenderView (F6):** render the viewer, material studio or a USD file to linear multichannel EXR. Set fractional frame ranges, supported AOVs and pixel regions. Shift-drag the image to select a region. Inspect layers/components/mattes and original float pixels; save the original EXR with all channels intact. Final jobs pause the interactive renderers and resume them afterward.
- **Python Console (F8):** explicit script execution in a cancellable worker. Successful cells apply as one undo transaction; errors, Stop or a conflicting document edit leave the main document intact.

![Material editor and native preview](docs/evidence/material-editor.png)

![Final RenderView](docs/evidence/render-view.png)

## MDL and automation

File → New MDL demo uses the installed ovRTX OmniPBR module. For reflected/custom MDL graph editing, install the optional SDK adapter:

```bash
.venv/bin/python tools/setup_mdl_sdk.py
```

This downloads the checksum-pinned NVIDIA MDL SDK into `.cache/mdl-sdk` and installs its matching Python 3.10 interpreter through uv. Alternatively, set `OMNILAB_MDL_SDK` and `OMNILAB_MDL_PYTHON`. Load modules and set search roots in the Material Editor. Successful modules are cached with imports/resources bundled; a failed reload retains the last valid material. SDK assets remain outside the repository.

MCP is optional and starts stopped:

```bash
uv sync --extra rtx --extra dev --extra mcp
.venv/bin/omnilab-mcp
```

Enable **View → Start MCP** in the editor and configure the stdio command above in your MCP client. It exposes the same document, graph, preview, final-render and export services, with revision checks for edits. Stop MCP removes the private local endpoint.

## Validation and settings

```bash
.venv/bin/python -m pytest -q
.venv/bin/omnilab-probe --output artifacts/p0
.venv/bin/python tools/replay_qt.py
```

[Full P2–P5 validation and reproduction commands](docs/P2_P5_STATUS.md) include native GPU material, EXR/region, projector/bake, Qt and MCP tests. The original [P0–P2 report](docs/P0_P2_STATUS.md) is retained as historical evidence.

**View → Inspect all ovRTX settings** opens typed viewport/material/final overrides and renderer-creation controls. Export all settings writes declarations, authored values, source versions and explicitly unknown effective values. Full extracted inventories remain available:

- [Complete settings catalog](docs/settings/OVRTX_SETTINGS.md): 828 declarations / 826 unique RTX names.
- [JSON](docs/settings/ovrtx-settings.json), [CSV](docs/settings/ovrtx-settings.csv), and [C creation options](docs/settings/ovrtx-c-configuration.csv).
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md) and [Lunatic parity matrix](docs/LUNATIC_PARITY.md).
- [Evidence](docs/EVIDENCE.md) and [Lunatic source reuse/hashes](docs/LUNATIC_REUSE.json).

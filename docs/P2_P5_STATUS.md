# P2–P5 implementation and acceptance

2026-10-02. The Qt application now has working viewport, MaterialX/OpenPBR, native MDL, RenderView, baking, publishing and automation workflows. These are tested implementations, not just the earlier design. **Full Lunatic release parity is still an open acceptance gate**: the limits below remain visible rather than being counted as completed features. Qt stays first; ovUI is P6 and MoonRay graph conversion stays P7.

## Delivered workflows

| Phase | Implementation | Evidence |
|---|---|---|
| P2: viewport | Persistent ovstage/ovRTX worker; continuous-input scheduling; camera and material deltas; live transform drag without a USD commit; one release/undo transaction; cancel/recovery; scene-camera navigation with edit toggle, locks, roll, lens shift and fractional-frame authorship | Real desktop replay, camera/gesture regressions; latest [viewport report](evidence/p2-p5-viewport.json) |
| P2: overlays/settings | Native shaded/unlit wireframe; filled-surface polygon wire and points using metric distance occlusion; typed, searchable renderer creation and per-product overrides; JSON inventory export; retired snapshots removed only after worker acknowledgement | CPU occlusion and profile isolation checks, native overlay screenshots and replay; full [settings inventory](settings/OVRTX_SETTINGS.md) |
| P3: graphs | Catalog from installed MaterialX NodeDefs; OpenPBR inputs grouped by annotations; typed ports, cycle rejection, terminals, node naming, clipboard, layout, independent tab undo; global document undo refreshes open tabs; unknown USD nodes retained | Graph tests and [real Qt input replay](evidence/material-editor.json) |
| P3: materials and previews | USD bindings; atomic `.mtlx` import/export; colorspaces and UDIM path preservation; asynchronous source thumbnails; sphere/cube/UV-card studio with orbit/pan/dolly, HDRI, lighting, RTPT/PT; per-material studio state and request-checked images | Red/green native preview images, binding/layout save/reopen tests, material editor screenshot |
| P4: native MDL | SDK reflection of exported materials/functions, typed inputs/defaults/annotations, configured search roots, OmniPBR loading, source diagnostics, typed function-call graphs, reload and content-addressed last-valid module bundles | Actual SDK compile/reflection tests; [native function-graph edit](evidence/mdl-graph.json) visibly changes the image; broken source reload preserves the valid module |
| P5: RenderView | Viewer, material-studio or USD-file source; immutable USD/camera/time snapshots; isolated final worker; GPU scheduling pauses interactive workers; RTPT temporal-frame status and PT active-frame status; fractional sequences; bounded cancel and saved diagnostics | [RenderView desktop replay](evidence/render-view.json); cancellation and failure tests protect previous files |
| P5: images | FLOAT multichannel EXR, exact floating-point probes, multipart/layer/component selection, matte selection/overlay, exposure, raw/sRGB/signed/normalized display, pan/zoom and lossless all-channel save | Ported OIIO tests including negative/HDR/nonfinite values; native [AOV and region report](evidence/final-jobs.json) |
| P5: regions | Pixel regions or Shift-drag; native `dataWindowNDC`; per-frame/per-channel merge; only successful staged output replaces destination | Native crop aligns with the full image; outside-region pixels compare exactly equal |
| P5: maps/projectors | Native calibrated UV-card float/color evaluation; temporal directional/rotational UV blur; atomic EXR; insert baked image node; camera projection using MaterialX coordinates, perspective division, near/far and behind-camera clipping, live/frozen links | [Native bake/projector probe](evidence/bake-projector.json): known HDR colors, periodic wrap, directional/rotational averaging, perspective/orthographic quadrants, clipping and frozen links |
| P5: asset publishing | Existing Lunatic composition-aware selected-prim publication, MaterialX textures/UDIM and validated MDL import/resource bundles | Publishing does not alter source layers; published MDL textures resolve after original module/search files are removed |
| P5: console/MCP | Python worker with stop, retained context, explicit script execution, composition-preserving result transactions and conflict rejection; opt-in local MCP with shared document/graph commands, revisions, preview/final/export | [Actual stdio MCP and desktop console replay](evidence/automation.json): 15 tools, one batch/undo, stale revision rejection, stopped-by-default endpoint, native-call cancellation |

The main interpreter remains Python 3.12. MDL reflection uses a separate, optional NVIDIA MDL SDK 2026.0.2 process with its matching Python 3.10 bindings. SDK binaries are neither copied into the application package nor committed. `tools/setup_mdl_sdk.py` installs the pinned archive into the ignored local cache and verifies SHA-256. MDL source paths can also be configured through `OMNILAB_MDL_SDK` and `OMNILAB_MDL_PYTHON`.

## Rendering and data contracts

- USD and `.omnilab` saves preserve the existing document/composition model. Rendering flattens only private snapshots. Subsequent editor changes cannot alter a running job's USD/camera/time; external texture files are still referenced and should remain unchanged during the job.
- Only the parent job controller can publish a completed EXR. Cancel/failure cannot publish a queued unfinished frame. Already completed sequence frames remain available. The saved job JSON includes versions, source revision, snapshot hashes, camera, AOVs and settings; logs remain alongside it.
- Final outputs offered after native validation: **HdrColor and DistanceToCameraSD in PT/RTPT**; **NormalSD, DistanceToImagePlaneSD and Camera3dPositionSD in RTPT**. The final probe checks 14 EXR channels. Infinite background distance is retained as data, not converted to a made-up finite depth.
- Settings export distinguishes schema/API declarations, authored editor overrides and composed USD values. It labels effective runtime values **unknown** because the SDK has no complete effective-settings query. The catalog contains 828 declarations / 826 unique RTX names, 19 Python creation fields and the separate 20-key C inventory. Schema availability is not a promise that every setting visibly works in every mode.
- Bake normalization measures a unit-emission reference through the same native pipeline. It is a **nonnegative float/color UV-card bake**, with renderer precision and finite temporal sampling. Signed vectors/normals are rejected. It is not mesh/UDIM baking or an exact evaluator of arbitrary shader state.
- Projector camera and matrix relationships survive USD namespace changes and graph duplication. A standalone MaterialX export requires freezing live camera links first.

## Remaining release-parity gates

These are not silently moved to P7; P7 applies only to MoonRay graph conversion.

| Area | Remaining limit / gate |
|---|---|
| Large stages and interaction | Full snapshots still compose on the Qt owner thread. GPU output crosses a copied CPU buffer. Very large scenes need profiling and incremental structural publication. Gizmos operate on the first selected prim. |
| Geometry overlays | Bounded to 100,000 samples per paint, 100,000 vertices and 10,000 edges per mesh, and 10,000 traversed prims. They use authored mesh geometry and native depth; renderer displacement, subdivision or skinning can differ. Native wireframe remains available for rendered tessellation. Full joint/skeleton UI, deformed overlay parity and advanced camera/light guides remain open. |
| Graph UX | Typed NodeDef ramp/math/UV nodes work through their ports; Lunatic's specialized ramp widget, full alignment/shortcut suite, arbitrary scene-object previews and linked studio-camera UI are not all ported. No blanket claim of native coverage for every catalog node/lobe. |
| MDL | Scalar/vector/color/string/texture inputs and the tested color function graphs are supported. Overloaded exported names need a uniquely named wrapper; adding ambiguous nodes is rejected. Complex struct/enum/closure/array graphs and uniform/varying constraint validation are not complete. Last-valid module compilation does not prove every renderer-specific MDL feature. |
| Final renderer features | No true intermediate PT checkpoint image API has been established; active-frame status is honest about this. Arbitrary LPEs, Cryptomatte, custom shader AOVs, hair/VDB/displacement/blur effect matrices and second-machine qualification remain unaccepted. Failed/cancelled jobs can be rerendered; there is no checkpoint-resume UI. |
| Legacy/general UI | `.lunaproj`/`.moonrayproject` import, appearance/recent-file preferences, external layer-change notices and every original Lunatic dialog/shortcut are not a finished compatibility layer. Existing USD content is retained; legacy MoonRay execution is not substituted. |
| Display | The image viewer retains original float data but displays a bounded 8-bit preview. Full OCIO/HDR display and deep-EXR visualization are outside the inspected baseline. |
| Runtime | The installed SDK still emits a nonfatal MaterialX cache permission warning for `/usr/bin/cache/rtx.materialx`; native tests succeeded without changing system-directory permissions. |

## Validation result

**128 tests passed, zero failures/skips** with the optional MDL SDK present. All seven native/desktop reports above passed. The application wheel builds and includes the settings registry. The [validation manifest](evidence/p2-p5-validation.json) records package versions and report hashes. On this workstation the viewport presented 29 frames during a 1.055-second continuous mouse drag (median 33.0 ms between frames); final PT cancellation took 0.35 seconds. These are measured replay outcomes, not general benchmarks.

## Reproduce

```bash
uv sync --python 3.12 --extra rtx --extra dev --extra mcp
.venv/bin/python tools/setup_mdl_sdk.py  # optional native MDL reflection
.venv/bin/python -m pytest -q
.venv/bin/python tools/replay_qt.py
.venv/bin/python tools/replay_material_editor.py
.venv/bin/python tools/replay_render_view.py
.venv/bin/python tools/replay_automation.py
.venv/bin/python tools/probe_mdl_graph.py
.venv/bin/python tools/probe_final_jobs.py
.venv/bin/python tools/probe_bake_projector.py
```

Run GPU replays sequentially. They open temporary Qt windows and write generated scenes, EXRs and full native logs to ignored `artifacts/`. Tests that require the optional MDL SDK skip when it is absent. The checked-in reports and screenshots record this workstation's outcomes, not general performance guarantees. No original Lunatic source files were changed.

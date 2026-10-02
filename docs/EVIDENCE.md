# Evidence and reproduction

Research date: 2026-10-02. The user chose Qt first and standalone ovUI as a second frontend. The initial research produced the plan and settings catalog. Implementation followed in the same session; [P0–P2 status](P0_P2_STATUS.md), [runtime manifest](evidence/p0-runtime.json) and [desktop replay](evidence/qt-replay.json) record the new GPU evidence. The source Lunatic checkout and external SDK installations were not modified.

## Local sources

| Source | Identity | Use |
|---|---|---|
| [Lunatic README](/home/dillonb/DEV/astra_tests/moonray_tests/lunatic/README.md) | Current working tree; HEAD `5b9421a3b1866ea55e46c273d7ee3a46440f5dd5` | Existing workspaces, UI rules, dependencies, save/render/material behavior |
| [Project capture/restore](/home/dillonb/DEV/astra_tests/moonray_tests/lunatic/moonray_editor/usd_project.py) | Same working tree | Durable USD layer ownership and save invariants |
| [Shader catalog](/home/dillonb/DEV/astra_tests/moonray_tests/lunatic/moonray_editor/model.py) | Same working tree | Current MoonRay metadata coupling |
| [Shader adapters](/home/dillonb/DEV/astra_tests/moonray_tests/lunatic/moonray_editor/shader_adapters.py) | Same working tree | Existing graph lowering is MoonRay-specific |
| [Viewport frontend](/home/dillonb/DEV/astra_tests/moonray_tests/lunatic/moonray_editor/usd_viewer.py) | Same working tree | Qt/process boundaries and renderer-specific UI dependencies |
| [Asset publishing](/home/dillonb/DEV/astra_tests/moonray_tests/lunatic/ASSET_PUBLISHING.md) | Same working tree | Explicit difference between saving composition and publishing a composed snapshot |
| [ovRTX sources](/home/dillonb/DEV/skills-src/ovrtx/README.md) | `0.5.0`, commit `e3ebb35a6024d070fe21125f3806d6152ed3c753` | Current API, examples, configuration headers, release notes and docs |
| [Renderer creation configuration](/home/dillonb/DEV/skills-src/ovrtx/python/ovrtx/_src/types.py) | Matches installed package file SHA-256 | 19 Python fields and documented native defaults |
| [C configuration keys](/home/dillonb/DEV/skills-src/ovrtx/include/ovrtx/ovrtx_types.h:864) | Same source commit | 20 active keys and two retired slots |
| [Packaged RTX schema](/home/dillonb/DEV/db/Omnivore-work/ovrtx/ovrtx-0.5.0/ovrtx/bin/usd_plugins/rtx_settings/generatedSchema.usda) | Package `ovrtx-0.5.0.377615` | All 828 RTX schema declarations, defaults, types, labels and enum tokens |
| [OpenPBR definition](/home/dillonb/DEV/db/Omnivore-work/ovrtx/ovrtx-0.5.0/ovrtx/bin/library/materialx/bxdf/open_pbr_surface.mtlx) | Same installed package | Presence of MaterialX/OpenPBR implementation assets; not a GPU acceptance test |
| [Attached-mode minimal example](/home/dillonb/DEV/skills-src/ovrtx/examples/python/minimal/main.py) | Same source commit | Population, sealing, RenderProduct stepping and DLPack readback lifecycle |
| [ovstage public contract](/home/dillonb/DEV/db/Omnivore-work/public-src/ovstage/AGENTS.md) | Local public-source checkout | Runtime scene ownership, publication ordinals and latest-state limitations |

[sources.json](sources.json) records the Lunatic working-tree status and file hashes for a broader baseline inventory. Hashing a file does not mean it was reviewed line by line. [ovrtx-settings.json](settings/ovrtx-settings.json) records exact hashes of every schema/configuration source used by the extractor.

## Public cross-checks

- [ovRTX version](https://github.com/NVIDIA-Omniverse/ovrtx/blob/main/VERSION.md) and [release notes](https://github.com/NVIDIA-Omniverse/ovrtx/blob/main/CHANGELOG.md): version, attached-stage migration, output changes and removed configuration options.
- [NVIDIA Qt/MaterialX sample](https://github.com/NVIDIA-Omniverse/ovrtx/blob/main/docs/examples/c_material_editor.rst): confirmed the sample's scope and deprecated API use.
- [NVIDIA OpenPBR documentation](https://docs.omniverse.nvidia.com/materials-and-rendering/latest/templates/OpenPBR.html): relationship between OpenPBR, MaterialX and MDL, plus renderer-mode caveats.
- [ovUI overview](https://github.com/NVIDIA-Omniverse/ovui), [widget README](https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-widgets/README.md) and [data adapters](https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-data-adapters/README.md): standalone UI availability and differences between authoring and native runtime providers.

Public documentation describes available implementations and known limits; it does not validate this workstation's complete package combination. The implementation plan uses source-pinned ovRTX evidence and requires a P0 runtime manifest for deployment.

## Reproduce the settings extraction

The existing `lab` interpreter has `pxr.Sdf` and was used only to read schema text. Its OpenUSD parser reports **26.8**; that is the extraction interpreter's version, not a proposed renderer/authoring dependency pin. No ovRTX import, renderer initialization or GPU workload is needed.

```bash
cd /home/dillonb/DEV/db/OmniLab
/home/dillonb/DEV/db/Omnivore-work/lab/.venv/bin/python \
  tools/export_ovrtx_settings.py \
  --sdk-package /home/dillonb/DEV/db/Omnivore-work/ovrtx/ovrtx-0.5.0 \
  --source-checkout /home/dillonb/DEV/skills-src/ovrtx \
  --output-dir docs/settings
```

The exporter uses USD's Sdf parser, compares the complete emitted RTX declaration count to the original layer, checks unique `(schema class, attribute)` identities, checks declaration line locations, and rejects a mismatch between package and source `RendererConfig` files. It reads the public C key declarations independently, including the C-only binary package path.

The catalog keeps repeated property names in different schema classes. Consequently 828 declarations represent 826 unique names. Raw declaration defaults preserve the USD spelling; typed values and complete descriptions are in JSON. Standard Camera/UsdRender declarations and SDK documentation rows remain separate so provenance is not lost.

## Validation performed and limits

- Successfully parsed and inventoried all 28 RTX schema classes: 828 declarations / 826 unique names.
- Extracted all 19 Python creation fields and 20 active public C configuration keys; retained the two retired slots as retired.
- Included 56 standard Camera/UsdRender declarations, 76 documented settings and documented camera outputs by mode.
- Compared schema and documented defaults/types; found two differences, plus nine documented names absent from the schema. These are surfaced explicitly.
- Checked output structure, source references and local documentation links. No application or GPU integration tests were run; those are P0 deliverables.

The output is a versioned settings **catalog**, not a live effective-configuration dump. Schema declaration, SDK documentation and successful rendering are distinct evidence levels. Future runtime checks must establish supported scopes/modes, effective values, reset requirements and visible effects before promoting controls into ordinary UI.

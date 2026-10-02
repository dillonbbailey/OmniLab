# OmniLab

Planning workspace for reproducing Lunatic's USD editor, material editor and RenderView with NVIDIA Omniverse libraries.

The agreed direction is **Qt first, ovUI second**, with one shared editor core. The proposed rendering stack is **ovstage + ovRTX**, while OpenUSD owns editable documents and composition. **OpenPBR through MaterialX** is the default material workflow; **MDL** is an additional native material workflow.

- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Lunatic behavior and migration matrix](docs/LUNATIC_PARITY.md)
- [Complete extracted ovRTX settings catalog](docs/settings/OVRTX_SETTINGS.md)
- [Machine-readable settings](docs/settings/ovrtx-settings.json) and [CSV](docs/settings/ovrtx-settings.csv)
- [C creation options](docs/settings/ovrtx-c-configuration.csv)
- [Evidence and reproduction](docs/EVIDENCE.md)

This workspace contains a researched plan and a reproducible settings exporter. The application has not been implemented, and renderer/material compatibility has not yet been tested on the GPU.

# ovRTX settings inventory

Extracted 2026-10-02 from `ovrtx-0.5.0.377615`; source commit `e3ebb35a6024d070fe21125f3806d6152ed3c753`.

This is a complete extraction of the selected **RTX settings schema and public creation configuration**, plus the SDK's documented settings and standard camera/render declarations. It is **not** a dump of effective settings in a running renderer, and it does not imply every shipped property is implemented by standalone ovRTX. Schema groups include legacy, debug and XR entries. Sensor-specific LiDAR/radar model parameters, shader inputs, SPG program parameters and private Carb settings are separate domains, outside this renderer/editor catalog.

Schema defaults, SDK-documented defaults, application presets and effective runtime values are different. Keep them separate. An unset Python field (`None`) delegates to the native runtime; it does not mean false or zero. No runtime validation was performed.

Use [JSON](ovrtx-settings.json) for full descriptions, source provenance and conflicts; [CSV](ovrtx-settings.csv) for filtering; [C config CSV](ovrtx-c-configuration.csv) for the public C keys.

## Coverage

| Item | Count |
|---|---:|
| rtx_schema_declarations | 828 |
| rtx_schema_unique_names | 826 |
| rtx_schema_classes | 28 |
| python_config_fields | 19 |
| active_C_config_keys | 20 |
| retired_C_config_keys | 2 |
| standard_USD_declarations | 56 |
| documented_setting_rows | 76 |
| documented_names_missing_from_schema | 9 |
| default_or_type_differences | 2 |

## Interpretation and authoring

Documented `omni:rtx:*` rendering controls are authored on the selected RenderProduct. Camera lens/shutter properties belong on Camera prims; relationships and output declarations belong on RenderProduct/RenderVar. The raw schema class sections below preserve declarations and are not an authoring-target or supported-mode guarantee. Check global/camera/post-process scope and actual behavior before exposing each control.

The 0.5 SDK uses `RealTimePathTracing`, `PathTracing`, and `MinimalRendering` for the public render-mode API. The shipped schema enumerates `Real-Time Path-Tracing`, `PathTracing`, and `Minimal`. Preserve this discrepancy; implement and test a version-specific adapter rather than directly feeding schema tokens to the runtime.

Also check `renderingColorSpace` versus `omni:rtx:renderingColorSpace`. Do not silently rewrite assets. Retired creation controls `use_vulkan` and `dome_baking_resolution` must not be exposed as active 0.5 options. Dome MDL baking resolution is now a RenderProduct attribute but is consumed per scene; products sharing that scene must agree.

Create an allowlist from successful GPU checks for ordinary UI controls. Keep unverified/legacy schema properties in an explicitly labeled advanced inspector. The schema's old Carb paths are historical metadata, not a promise that standalone ovRTX exposes a Carb settings API.

## Schema/documentation differences

| Attribute | Schema type/default | SDK documentation type/default |
|---|---|---|
| `omni:rtx:rendermode` | `token` / `"Real-Time Path-Tracing"` | `token` / `"RealTimePathTracing"` |
| `omni:rtx:pt:adaptiveSampling:enabled` | `bool` / `0` | `bool` / `true` |

## Python renderer creation

| Field | Type | Python default | Meaning and native-default notes |
|---|---|---|---|
| `sync_mode` | `Optional[bool]` | `None` | Enables synchronous rendering mode for debugging purposes. |
| `log_file_path` | `Optional[str]` | `None` | Set the path to the log file for logging output. |
| `log_level` | `Optional[str]` | `None` | Set the log level for logging output (e.g. "verbose", "info", "warn", "error"). |
| `enable_profiling` | `Optional[bool]` | `None` | Enable internal profiling. Adds overhead when enabled. |
| `read_gpu_transforms` | `Optional[bool]` | `None` | Use GPU world transform propagation during rendering. |
| `keep_system_alive` | `Optional[bool]` | `None` | Keep the renderer system alive after all instances are destroyed so the next create reuses it. When omitted (`None`), the native layer defaults to enabled. |
| `active_cuda_gpus` | `Optional[str]` | `None` | Comma-separated CUDA device indices to use for rendering (e.g., "0,1,2"). |
| `datastore_cache` | `Optional[str]` | `None` | Protocol-prefixed datastore cache configuration used by UJITSO. Supported values include `grpcdns://host:port`, `grpcdns_notls://host:port`, and `local://path`. When omitted, existing defaults and environment-variable behavior are preserved. |
| `selection_outline_enabled` | `Optional[bool]` | `None` | Enable the selection-outline post-process pass. Defaults to `True` when unset. Init-time only; toggling requires recreating the renderer. |
| `selection_outline_width` | `Optional[int]` | `None` | Selection outline width in pixels. Valid range is `0..15` (the underlying RTX outline pipeline cap); out-of-range values are clamped by the renderer. Init-time only; changing requires recreating the renderer. Default: 2. |
| `selection_fill_mode` | `Optional[SelectionFillMode]` | `None` | Selection-outline fill (interior) mode. Accepts a :class:`SelectionFillMode` member or the equivalent `int` value (`0..3`). Out-of-range values raise :class:`ValueError`. Init-time only; changing requires recreating the renderer. Default: :attr:`SelectionFillMode.GLOBAL`. |
| `enable_geometry_streaming` | `Optional[bool]` | `None` | Enable geometry streaming. Disabled by default when `None`. |
| `enable_geometry_streaming_lod` | `Optional[bool]` | `None` | Geometry streaming LOD opt-in config entry. |
| `enable_spg` | `Optional[bool]` | `None` | Set to False to disable Sensor Processing Graphs (SPG), enabled by default. This is a global setting, applying to all active renderer instances. |
| `suppress_deprecation_warnings` | `Optional[bool]` | `None` | Suppress Python and native runtime warnings emitted by deprecated OVRTX APIs. Compile-time deprecation diagnostics for C and C++ consumers are unaffected. When `None` or `False`, runtime deprecation warnings remain enabled. |
| `motion_bvh` | `Optional[MotionBvh]` | `None` | Motion BVH mode for sensor pipelines (lidar, radar, acoustic). Accepts a :class:`MotionBvh` member, the equivalent `int` value (`0..2`), or the strings `"disable"`, `"enable"`, or `"auto"`. When `None` (default), motion BVH is disabled and no config entry is sent. Sensor workflows should pass :attr:`MotionBvh.AUTO` or :attr:`MotionBvh.ENABLE`. Init-time only; changing requires recreating the renderer. |
| `sensors_allowed_deprecation_base` | `Optional[str]` | `None` | Allow all soft-deprecated sensor versions while pinned to a specific release: `"<major>.<minor>.<patch>"` (e.g. `"0.4.0"`). Soft-deprecated versions are rejected by default; deprecation is allowed only when this matches the current framework version, so it must be revisited on every framework upgrade. |
| `aftermath_mode` | `Optional[AftermathMode]` | `None` | NVIDIA Nsight Aftermath diagnostics mode. Accepts an :class:`AftermathMode` member, the equivalent `int` value (`0..2`), or `"disable"`, `"enable"`, or `"auto"`. Disable skips Aftermath initialization, enable selects explicit diagnostics initialization, and `None` or auto selects the initialization mode automatically. This setting is process-global and must match the first renderer while the renderer system is alive. |
| `texture_streaming_mode` | `Optional[TextureStreamingMode]` | `None` | Texture streaming mode. Accepts a :class:`TextureStreamingMode` member, the equivalent `int` value (`0..2`), or the strings `"disable"`, `"synchronous"`, or `"asynchronous"`. When `None`, asynchronous mode is used. Synchronous mode controls texture-feedback processing; it does not make all texture loading operations synchronous. This setting is process-global and applies to all active renderer instances. |

## C configuration keys

| Key | Type | State | Meaning |
|---|---|---|---|
| `OVRTX_CONFIG_SYNC_MODE` | `bool` | Public | If true, stream operations execute synchronously (enqueue blocks). Init and create_renderer. |
| `OVRTX_CONFIG_ENABLE_PROFILING` | `bool` | Public | If true, enables internal profiling. Init and create_renderer. |
| `OVRTX_CONFIG_READ_GPU_TRANSFORMS` | `bool` | Public | If true, uses GPU world transform propagation during rendering. Create_renderer. |
| `OVRTX_CONFIG_KEEP_SYSTEM_ALIVE` | `bool` | Public | If true, keeps the renderer system alive after all instances are destroyed (for reuse). Create_renderer. |
| `OVRTX_CONFIG_DEPRECATED_4` | `bool` | Retired — reject | Retired OVRTX_CONFIG_USE_VULKAN slot. Passing this key returns an error. |
| `OVRTX_CONFIG_SELECTION_OUTLINE_ENABLED` | `bool` | Public | If true, enables the selection outline postprocessing pass. Create_renderer. When not specified, defaults to true. |
| `OVRTX_CONFIG_ENABLE_GEOMETRY_STREAMING` | `bool` | Public | If true, enables geometry streaming. Create_renderer. When not specified, defaults to false. |
| `OVRTX_CONFIG_ENABLE_GEOMETRY_STREAMING_LOD` | `bool` | Public | API key for the geometry streaming LOD opt-in flag. Create_renderer. |
| `OVRTX_CONFIG_ENABLE_SPG` | `bool` | Public | If false, disables Sensor Processing Graphs (SPG), default: enabled. This is a global setting, applying to all active renderer instances. |
| `OVRTX_CONFIG_SUPPRESS_DEPRECATION_WARNINGS` | `bool` | Public | If true, suppresses runtime deprecation warnings emitted by legacy OVRTX APIs. Compile-time deprecation diagnostics are unaffected. Create_renderer. |
| `OVRTX_CONFIG_BINARY_PACKAGE_ROOT_PATH` | `string` | Public | Path to OVRTX binary package root. Loader uses for dylib and resources. Init and create_renderer (must match). |
| `OVRTX_CONFIG_LOG_FILE_PATH` | `string` | Public | Log file path for carb logging. Applied when first renderer is created. Init and create_renderer. |
| `OVRTX_CONFIG_LOG_LEVEL` | `string` | Public | Log level for carb logging (e.g. "verbose", "info", "warn", "error"). Init and create_renderer. |
| `OVRTX_CONFIG_ACTIVE_CUDA_GPUS` | `string` | Public | Comma-separated CUDA device indices to use (e.g. "0,1,2"). Create_renderer. |
| `OVRTX_CONFIG_DATASTORE_CACHE` | `string` | Public | Protocol-prefixed datastore cache configuration used by UJITSO. Supported values: "grpcdns://host:port", "grpcdns_notls://host:port", and "local://path". System-level; init and create_renderer values must match when both are specified. |
| `OVRTX_CONFIG_SENSORS_ALLOWED_DEPRECATION_BASE` | `string` | Public | Allow all soft-deprecated sensor versions, but only while pinned to a specific framework release: "<major>.<minor>.<patch>". (e.g. "0.4.0"). Any other value (or unset) allows none. |
| `OVRTX_CONFIG_SELECTION_OUTLINE_WIDTH` | `int64` | Public | Selection outline width in pixels. Valid range 0..15 (15 is the underlying RTX outline pipeline cap). Init-time only; changing requires renderer recreation. Default: 2 (set by the underlying renderer). |
| `OVRTX_CONFIG_SELECTION_FILL_MODE` | `int64` | Public | Selection-outline interior (fill) mode. Value type: @ref ovrtx_selection_fill_mode_t. Out-of-range values are clamped by the renderer. Init-time only; changing requires renderer recreation. Default: @ref OVRTX_SELECTION_FILL_MODE_GLOBAL. |
| `OVRTX_CONFIG_MOTION_BVH` | `int64` | Public | Motion BVH mode. Value type: @ref ovrtx_motion_bvh_t. Init-time only; changing requires renderer recreation. When not specified, defaults to @ref OVRTX_MOTION_BVH_DISABLE. |
| `OVRTX_CONFIG_INT64_DEPRECATED_4` | `int64` | Retired — reject | Retired OVRTX_CONFIG_DOME_BAKING_RESOLUTION slot, replaced by the per-RenderProduct 'omni:rtx:lights:dome:baking:resolution' attribute. Passing this key returns an error. It shipped as 4 in ovrtx 0.4.1, so do not reuse the value for a new key: a config array built against those headers would then be misread as that key instead of rejected. |
| `OVRTX_CONFIG_TEXTURE_STREAMING_MODE` | `int64` | Public | Texture streaming mode. Value type: @ref ovrtx_texture_streaming_mode_t. Invalid values cause renderer creation to fail. When omitted, defaults to @ref OVRTX_TEXTURE_STREAMING_ASYNCHRONOUS. Process-global; changing affects all active renderer instances. |
| `OVRTX_CONFIG_AFTERMATH_MODE` | `int64` | Public | NVIDIA Nsight Aftermath mode. Value type: @ref ovrtx_aftermath_mode_t. @ref OVRTX_AFTERMATH_DISABLE skips Aftermath initialization, @ref OVRTX_AFTERMATH_ENABLE selects explicit diagnostics initialization, and omitted or @ref OVRTX_AFTERMATH_AUTO selects the initialization mode automatically. This setting is process-global and must match the first renderer while the renderer system is alive. |

## Documented RenderProduct settings

### Render Mode Selection

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rendermode` | `token` | `"RealTimePathTracing"` | — |  |

### Sampling and Caching

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rtpt:cached:enabled` | `bool` | `true` | — |  |
| `omni:rtx:rtpt:lightcache:cached:enabled` | `bool` | `true` | — |  |
| `omni:rtx:rtpt:ris:meshLights` | `bool` | `false` | — |  |
| `omni:rtx:pt:radianceCache:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:lightCache:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:ris:meshLights` | `bool` | `false` | — |  |
| `omni:rtx:pathtracing:rayguide:cached:enabled` | `bool` | `false` | — |  |

### Ray Bounces and Shading

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rtpt:maxBounces` | `uint` | `3` | — |  |
| `omni:rtx:rtpt:extraSpecularAndTransmissiveBounces` | `uint` | `0` | — |  |
| `omni:rtx:rtpt:maxVolumeBounces` | `uint` | `3` | — |  |
| `omni:rtx:pt:fractionalCutoutOpacity` | `bool` | `true` | — |  |
| `omni:rtx:rtpt:maxRoughness` | `float` | `0.3` | — |  |
| `omni:rtx:rt:reflections:roughnessCacheThreshold` | `float` | `0.3` | — |  |
| `omni:rtx:rtpt:translucency:virtualMotion:enabled` | `bool` | `true` | — |  |

### Firefly Filter

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rtpt:fireflyFilter:enabled` | `bool` | `true` | — |  |
| `omni:rtx:rtpt:fireflyFilter:maxUnexposedIntensityPerSample` | `float` | `3200.0` | — |  |
| `omni:rtx:rtpt:fireflyFilter:maxUnexposedIntensityPerSampleDiffuse` | `float` | `3200.0` | — |  |
| `omni:rtx:rtpt:fireflyFilter:maxPerEmissiveUnexposedIntensity` | `float` | `3200.0` | — |  |
| `omni:rtx:pt:fireflyFilter:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:fireflyFilter:maxUnexposedIntensityPerSample` | `float` | `3200.0` | — |  |
| `omni:rtx:pt:fireflyFilter:maxUnexposedIntensityPerSampleDiffuse` | `float` | `3200.0` | — |  |
| `omni:rtx:pt:fireflyFilter:maxPerEmissiveUnexposedIntensity` | `float` | `3200.0` | — |  |

### Gaussian Splatting

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rtpt:gaussian:accumulatedDepth:enabled` | `bool` | `true` | — |  |
| `omni:rtx:rtpt:gaussian:accumulatedAlbedo:enabled` | `bool` | `true` | — |  |
| `omni:rtx:rtpt:gaussian:maxGaussiansToAccumulate` | `int` | `48` | — |  |

### Path Tracing

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:samplesPerPixel` | `uint` | `512` | — |  |
| `omni:rtx:pt:samplesPerIteration` | `int` | `1` | — |  |
| `omni:rtx:pt:adaptiveSampling:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:limits:maxBounces` | `uint` | `4` | — |  |
| `omni:rtx:pt:limits:extraSpecularAndTransmissiveBounces` | `uint` | `2` | — |  |
| `omni:rtx:pt:maxVolumeBounces` | `uint` | `15` | — |  |
| `omni:rtx:pt:limits:maxFogBounces` | `uint` | `2` | — |  |
| `omni:rtx:pt:fractionalCutoutOpacity` | `bool` | `true` | — |  |

### Denoising

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:denoising:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:denoising:optix:temporal` | `bool` | `false` | — |  |
| `omni:rtx:pt:denoising:blendFactor` | `float` | `0.0` | — |  |
| `omni:rtx:pt:denoising:optix:denoiseAOVs` | `bool` | `true` | — |  |

### Spectral Rendering

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pathtracing:spectral:enabled` | `bool` | `false` | — |  |
| `omni:rtx:pathtracing:spectral:wavelengthMin` | `float` | `10.0` | — |  |
| `omni:rtx:pathtracing:spectral:wavelengthMax` | `float` | `10000.0` | — |  |
| `omni:rtx:renderingColorSpace` | `string` | `"lin_rec709_scene"` | — |  |
| `omni:rtx:pathtracing:spectral:responseCurve` | `uint` | `0` | — |  |

### Non-Uniform Volumes

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:ptvol:enabled` | `bool` | `false` | — |  |
| `omni:rtx:pt:volumes:transmittanceMethod` | `token` | `"biasedRayMarching"` | — |  |
| `omni:rtx:pt:volumes:tracking:maxScatteringSteps` | `int` | `1024` | — |  |
| `omni:rtx:pt:volumes:tracking:maxShadowSteps` | `int` | `32` | — |  |
| `omni:rtx:pt:limits:maxVolumeBounces` | `uint` | `2` | — |  |

### Multi-GPU

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:multigpu:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:mgpu:autoLoadBalancing:enabled` | `bool` | `true` | — |  |
| `omni:rtx:pt:mgpu:compressRadiance` | `bool` | `false` | — |  |
| `omni:rtx:pt:mgpu:compressAlbedo` | `bool` | `true` | — |  |
| `omni:rtx:pt:mgpu:compressNormals` | `bool` | `true` | — |  |
| `omni:rtx:multiThreading:enabled` | `bool` | `true` | — |  |

### Global Volumetric Effects

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:ptvol:raySky` | `bool` | `false` | — |  |
| `omni:rtx:pt:ptvol:raySkyScale` | `float` | `1.0` | — |  |
| `omni:rtx:pt:ptvol:raySkyDomelight` | `bool` | `false` | — |  |

### Anti-Aliasing

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:pixelFilter:filter` | `token` | `"triangle"` | — |  |
| `omni:rtx:pt:pixelFilter:radius` | `float` | `1.0` | — |  |

### View Lighting Mode (Camera Light)

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:scene:useViewLightingMode` | `bool` | `false` | — |  |
| `omni:rtx:viewLighting:lightType` | `token` | `"distant"` | — |  |
| `omni:rtx:viewLighting:color` | `color3f` | `(1, 1, 1)` | — |  |
| `omni:rtx:viewLighting:intensity` | `float` | `3000.0` | — |  |
| `omni:rtx:viewLighting:normalize` | `bool` | `true` | — |  |
| `omni:rtx:viewLighting:angle` | `float` | `0.0` | — |  |
| `omni:rtx:viewLighting:radius` | `float` | `0.05` | — |  |
| `omni:rtx:viewLighting:coneAngle` | `float` | `90.0` | — |  |
| `omni:rtx:viewLighting:coneSoftness` | `float` | `0.0` | — |  |

### DomeLight MDL Material Baking

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:lights:dome:baking:resolution` | `int` | `4096` | — |  |
| `omni:rtx:domeLight:baking:spp` | `int` | `4` | — |  |
| `omni:rtx:lights:dome:baking:denoising:enabled` | `bool` | `false` | — |  |

### Minimal Settings

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:minimal:mode` | `int` | `(not declared)` | — |  |
| `omni:rtx:minimal:constantColor` | `color3f` | `(not declared)` | — |  |
| `omni:rtx:minimal:castShadows` | `bool` | `(not declared)` | — |  |
| `omni:rtx:rt:ambientLight:color` | `color3f` | `(not declared)` | — |  |
| `omni:rtx:rt:ambientLight:intensity` | `float` | `(not declared)` | — |  |


## All shipped RTX schema declarations

### OmniRtxSettingsGlobalRtAdvancedAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rt:multigpu:enabled` | `bool` | `1` | — | Enabled |

### OmniRtxSettingsGlobalPtAdvancedAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:multigpu:enabled` | `bool` | `1` | — | Enabled |

### OmniRtxSettingsGlobalCommonAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:scenePartitioning:showAllPartitionsByDefault` | `bool` | `0` | — | Show all partitions by default |
| `renderingColorSpace` | `token` | `"lin_rec709_scene"` | — | Rendering color space |

### OmniRtxSettingsCommonAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:lights:reflectionVisibleRoughnessThreshold` | `float` | `0` | — | Reflection visible roughness threshold |
| `omni:rtx:lights:refractionVisibleRoughnessThreshold` | `float` | `0` | — | Refraction visible roughness threshold |
| `omni:rtx:lights:visibilityOverride` | `token` | `"perLight"` | ["perLight", "forceVisible", "forceInvisible"] | Visibility override |
| `omni:rtx:materials:time:useWallClock` | `bool` | `0` | — | Use wallclock time |
| `omni:rtx:rendermode` | `token` | `"Real-Time Path-Tracing"` | ["PathTracing", "Real-Time Path-Tracing", "Minimal"] | Render mode |
| `omni:rtx:background:source:type` | `token` | `"DomeLight"` | ["domeLight", "backplate", "color"] | Background source |
| `omni:rtx:background:source:texture:path` | `asset` | `@@` | — | Background backplate texture path |
| `omni:rtx:background:source:texture:colorSpace` | `token` | `"lin_rec709"` | ["sRGB", "lin_rec709"] | Background backplate texture color space |
| `omni:rtx:background:source:texture:luminanceScale` | `float` | `1` | — | Background backplate texture luminance scale |
| `omni:rtx:background:source:texture:textureMode` | `token` | `"RepeatMirrored"` | ["repeat", "repeatMirrored", "clamp"] | Background backplate texture sample mode |
| `omni:rtx:background:source:color` | `color3f` | `(0, 0, 0)` | — | Background default color |
| `dataWindowNDC` | `float4` | `(0, 0, 1, 1)` | — | Data window NDC |

### OmniRtxSettingsCommonAdvancedAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:geometry:rayOffset` | `float` | `0` | — | Ray offset |
| `omni:rtx:lights:dome:baking:denoising:enabled` | `bool` | `0` | — | Baking denoising |
| `omni:rtx:lights:dome:baking:resolution` | `int` | `4096` | — | Baking resolution |
| `omni:rtx:lights:dome:samplingStrategy` | `token` | `"imageBasedLighting"` | ["imageBasedLighting", "upperAndLowerIsBlack", "upperAndLowerIsVisible", "environmentMappedImageBasedLighting", "approximatedImageBasedLighting"] | Sampling strategy |
| `omni:rtx:lights:shadowRayOffset` | `float` | `0.001` | — | Shadow bias |
| `omni:rtx:materials:refractionAsOpacity` | `bool` | `0` | — | Refraction as opacity |
| `omni:rtx:materials:time:override` | `float` | `-1` | — | Override |
| `omni:rtx:wireframe:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:wireframe:perPrimThicknessWorldSpace` | `bool` | `1` | — | Per-prim thickness is world-space |
| `omni:rtx:wireframe:thickness` | `float` | `0.3` | — | Thickness |
| `omni:rtx:wireframePrimThicknessWorldSpace` | `bool` | `0` | — | Global thickness is world-space |
| `omni:rtx:raytracing:picking:occluded:enabled` | `bool` | `0` | — | Pick Occluded Objects |
| `omni:rtx:syntheticdata:sensors:returnAllBBoxesOutsideFrustum` | `bool` | `0` | — | Include 3D Bounding Boxes outside the sensor frustum |
| `omni:rtx:wireframe:mode` | `token` | `"instance"` | ["instance", "shaded", "emissive"] |  |
| `omni:rtx:wireframe:shading:enabled` | `bool` | `1` | — | Wireframe Shading |

### OmniRtxSettingsMinimalAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:minimal:mode` | `int` | `2` | — | Minimal Shading Mode |
| `omni:rtx:minimal:constantColor` | `color3f` | `(0.5, 0.5, 0.5)` | — | Minimal Shading Constant Color |
| `omni:rtx:minimal:castShadows` | `bool` | `true` | — | Cast Shadows |
| `omni:rtx:minimal:useMinimalPipeline` | `bool` | `true` | — | Use Minimal Pipeline |
| `omni:rtx:minimal:dlss:execMode` | `token` | `"auto"` | ["performance", "balanced", "quality", "auto", "rtxaa", "manual"] | DLSS Mode |
| `omni:rtx:sceneDb:ambientLightColor` | `color3f` | `(0, 0, 0)` | — | Ambient Light Color |
| `omni:rtx:sceneDb:ambientLightIntensity` | `float` | `0` | — | Ambient Light Intensity |

### OmniRtxSettingsRtAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:dlss:frameGeneration` | `bool` | `false` | — | Frame generation |
| `omni:rtx:dlss:frameGenerationInterpolatedFrameCount` | `int` | `0` | — | Frame generation interpolated frame count |
| `omni:rtx:post:dlss:execMode` | `token` | `"auto"` | ["performance", "balanced", "quality", "auto", "rtxaa", "manual"] | Mode |
| `omni:rtx:rt:ambientLight:color` | `color3f` | `(0, 0, 0)` | — | Color |
| `omni:rtx:rt:ambientLight:intensity` | `float` | `0` | — | Intensity |
| `omni:rtx:rt:ambientocclusion:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:rt:ambientocclusion:rayLength` | `float` | `35` | — | Ray length (cm) |
| `omni:rtx:rt:directLighting:samples` | `uint` | `2` | — | Samples |
| `omni:rtx:rt:ecoMode:enabled` | `bool` | `1` | — | Eco mode |
| `omni:rtx:rt:ecoMode:maxFramesWithoutChange` | `uint` | `500` | — | Max frames without change |
| `omni:rtx:rt:fractionalOpacity` | `bool` | `0` | — | Fractional opacity |
| `omni:rtx:rt:indirectdiffuse:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:rt:indirectdiffuse:intensity` | `float` | `1` | — | Intensity |
| `omni:rtx:rt:indirectdiffuse:maxBounces` | `int` | `2` | — | Max bounces |
| `omni:rtx:rt:indirectdiffuse:maxRayUnexposedIntensity` | `float` | `6400` | — | Max ray intensity |
| `omni:rtx:rt:indirectdiffuse:samples` | `uint` | `1` | — | Samples |
| `omni:rtx:rt:reflections:maxBounces` | `int` | `1` | — | Max bounces |
| `omni:rtx:rt:reflections:roughnessCacheThreshold` | `float` | `0.3` | — | Roughness cache threshold |
| `omni:rtx:rt:reflections:samples` | `uint` | `1` | — | Samples |
| `omni:rtx:rt:refractions:maxBounces` | `int` | `6` | — | Max bounces |
| `omni:rtx:rt:sss:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:rt:sss:samples` | `int` | `32` | — | Samples |

### OmniRtxSettingsRtAdvancedAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rt:caustics:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:rt:caustics:filterIterations` | `int` | `5` | — | Filter iterations |
| `omni:rtx:rt:caustics:photonCount` | `int` | `20` | — | Photon count |
| `omni:rtx:rt:caustics:photonMaxBounces` | `int` | `4` | — | Photon max bounces |
| `omni:rtx:rt:directLighting:enabled` | `bool` | `1` | — | Sampled direct lighting |
| `omni:rtx:rt:directLighting:maxRayUnexposedIntensity` | `float` | `6400` | — | Max ray intensity |
| `omni:rtx:rt:directLighting:ris:meshLights` | `bool` | `0` | — | Enable RT mesh light sampling |
| `omni:rtx:rt:reflections:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:rt:reflections:maxRayUnexposedIntensity` | `float` | `19200` | — | Max ray intensity |
| `omni:rtx:rt:refractions:depthCorrection` | `bool` | `1` | — | Depth correction |
| `omni:rtx:rt:refractions:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:rt:refractions:maxRayUnexposedIntensity` | `float` | `19200` | — | Max ray intensity |
| `omni:rtx:rt:refractions:motionCorrection` | `bool` | `1` | — | Motion vector correction |
| `omni:rtx:rt:refractions:reflectionInRefraction` | `bool` | `0` | — | Reflections in refraction |
| `omni:rtx:rt:refractions:roughnessSampling` | `bool` | `0` | — | Roughness sampling (experimental) |
| `omni:rtx:rt:sss:transmission:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:rt:sss:transmission:samples` | `int` | `1` | — | Samples |
| `omni:rtx:rt:sss:transmission:scatteringSamples` | `int` | `1` | — | Scattering samples |

### OmniRtxSettingsPtAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:adaptiveSampling:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:pt:adaptiveSampling:targetError` | `float` | `0.001` | — | Target error |
| `omni:rtx:pt:denoising:blendFactor` | `float` | `0` | — | Blend factor |
| `omni:rtx:pt:denoising:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:pt:denoising:optix:denoiseAOVs` | `bool` | `1` | — | Temporal mode |
| `omni:rtx:pt:denoising:optix:temporal` | `bool` | `0` | — | Temporal mode |
| `omni:rtx:pt:limits:maxBounces` | `uint` | `4` | — | Max bounces |
| `omni:rtx:pt:limits:maxFogBounces` | `uint` | `2` | — | Max fog bounces |
| `omni:rtx:pt:limits:extraSpecularAndTransmissiveBounces` | `uint` | `2` | — | Extra specular and transmissive bounces |
| `omni:rtx:pt:limits:maxVolumeBounces` | `uint` | `2` | — | Max volume bounces |
| `omni:rtx:pt:pixelFilter:filter` | `token` | `"triangle"` | ["box", "triangle", "gaussian", "uniform"] | Filter |
| `omni:rtx:pt:pixelFilter:radius` | `float` | `1` | — | Radius |
| `omni:rtx:pt:samplesPerPixel` | `uint` | `512` | — | Samples per pixel |

### OmniRtxSettingsPtAdvancedAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:pt:fireflyFilter:enabled` | `bool` | `1` | — | enabled |
| `omni:rtx:pt:fireflyFilter:maxUnexposedIntensityPerSampleDiffuse` | `float` | `3200` | — | Max intensity diffuse |
| `omni:rtx:pt:fireflyFilter:maxUnexposedIntensityPerSample` | `float` | `3200` | — | Max intensity glossy |
| `omni:rtx:pt:fireflyFilter:maxPerEmissiveUnexposedIntensity` | `float` | `3200` | — | Max intensity glossy |
| `omni:rtx:pt:lightCache:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:pt:ris:meshLights` | `bool` | `0` | — | Enabled PT mesh light sampling |
| `omni:rtx:pt:radianceCache:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:pt:samplesPerIteration` | `int` | `1` | — | Samples per iteration |
| `omni:rtx:pt:volumes:tracking:maxScatteringSteps` | `int` | `1024` | — | Max scattering steps |
| `omni:rtx:pt:volumes:tracking:maxShadowSteps` | `int` | `32` | — | Max scattering steps |
| `omni:rtx:pt:volumes:transmittanceMethod` | `token` | `"biasedRayMarching"` | ["biasedRayMarching", "ratioTracking"] | Transmittance method |

### OmniRtxCameraExposureAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `exposure:fStop` | `float` | `5` | — |  |
| `exposure:iso` | `float` | `100` | — |  |
| `exposure:responsivity` | `float` | `1` | — |  |
| `exposure:time` | `float` | `1` | — |  |

### OmniRtxCameraAutoExposureAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:autoExposure:adaptationSpeed` | `float` | `3.5` | — | Adaptation speed |
| `omni:rtx:autoExposure:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:autoExposure:histogramClamping:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:autoExposure:histogramClamping:maxLuminance` | `float` | `100000` | — | Max luminance |
| `omni:rtx:autoExposure:histogramClamping:minLuminance` | `float` | `50` | — | Min luminance |
| `omni:rtx:autoExposure:histogramFilter` | `token` | `"median"` | ["median", "average"] | Histogram filter |
| `omni:rtx:autoExposure:whitePointScale` | `float` | `10` | — | White point scale |

### OmniRtxRollingShutterAPI

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rollingShutter:scanOrder` | `token` | `"none"` | ["none", "topToBottom", "bottomToTop", "leftToRight", "rightToLeft"] | Scan order |
| `omni:rtx:rollingShutter:lineOffset` | `double2` | `(0, 1)` | — | Line offset |
| `omni:rtx:rollingShutter:lineExposure` | `double2` | `(0, 1)` | — | Line exposure |

### OmniRtxPostColorGradingAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:grade:blackPoint` | `color3f` | `(0, 0, 0)` | — | Black point |
| `omni:rtx:post:grade:contrast` | `color3f` | `(1, 1, 1)` | — | Contrast |
| `omni:rtx:post:grade:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:post:grade:gain` | `color3f` | `(1, 1, 1)` | — | Gain |
| `omni:rtx:post:grade:gamma` | `color3f` | `(1, 1, 1)` | — | Gamma |
| `omni:rtx:post:grade:lift` | `color3f` | `(0, 0, 0)` | — | Lift |
| `omni:rtx:post:grade:multiply` | `color3f` | `(1, 1, 1)` | — | Multiply |
| `omni:rtx:post:grade:offset` | `color3f` | `(0, 0, 0)` | — | Offset |
| `omni:rtx:post:grade:saturation` | `color3f` | `(1, 1, 1)` | — | Saturation |
| `omni:rtx:post:grade:whitePoint` | `color3f` | `(1, 1, 1)` | — | White point |

### OmniRtxPostChromaticAberrationAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:chromab:algorithm` | `token` | `"radial"` | ["radial", "barrel"] | Red Algorithm |
| `omni:rtx:post:chromab:algorithmG` | `token` | `"radial"` | ["radial", "barrel"] | Green Algorithm |
| `omni:rtx:post:chromab:algorithmB` | `token` | `"radial"` | ["radial", "barrel"] | Blue Algorithm |
| `omni:rtx:post:chromab:boundaryBlend:blendFalloff` | `float` | `0.75` | — | Blend falloff |
| `omni:rtx:post:chromab:boundaryBlend:blendSize` | `float` | `0.25` | — | Blend size |
| `omni:rtx:post:chromab:boundaryBlend:mirror` | `bool` | `1` | — | Mirror |
| `omni:rtx:post:chromab:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:post:chromab:strengthB` | `float` | `0.015` | — | Strength B |
| `omni:rtx:post:chromab:strengthG` | `float` | `-0.075` | — | Strength G |
| `omni:rtx:post:chromab:strengthR` | `float` | `-0.055` | — | Strength R |
| `omni:rtx:post:chromab:useLanczosSampler` | `bool` | `0` | — | Use Lanczos sampler |

### OmniRtxPostBloomPhysicalAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:bloom:alphaChannelScale` | `float` | `1` | — | Alpha channel scale |
| `omni:rtx:post:bloom:aperture:blades` | `int` | `5` | — | Blades |
| `omni:rtx:post:bloom:apertureShapeCircular` | `bool` | `0` | — | Circular Aperture |
| `omni:rtx:post:bloom:aperture:dust` | `float` | `0` | — | Dust |
| `omni:rtx:post:bloom:aperture:noise` | `float` | `0` | — | Noise |
| `omni:rtx:post:bloom:aperture:rotation` | `float` | `5` | — | Rotation |
| `omni:rtx:post:bloom:aperture:scratches` | `float` | `0` | — | Scratches |
| `omni:rtx:post:bloom:aspectRatio` | `float` | `1.5` | — | Aspect ratio |
| `omni:rtx:post:bloom:cutoff` | `float3` | `(2, 2, 2)` | — | Cutoff point |
| `omni:rtx:post:bloom:cutoffFuzziness` | `float` | `0.5` | — | Cutoff fuzziness |
| `omni:rtx:post:bloom:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:post:bloom:energyConservingBlend` | `bool` | `0` | — | Energy-conserving blend |
| `omni:rtx:post:bloom:focalLength` | `float` | `35` | — | Focal length |
| `omni:rtx:post:bloom:fStop` | `float` | `5` | — | f-stop |
| `omni:rtx:post:bloom:scale` | `float` | `1` | — | Scale |
| `omni:rtx:post:bloom:sensorDiagonal` | `float` | `60` | — | Sensor diagonal |
| `omni:rtx:post:bloom:spectral:debugVisualization` | `token` | `"off"` | ["off", "aperture", "starburst"] | Debug visualization |
| `omni:rtx:post:bloom:spectral:samples` | `float` | `0` | — | Samples |
| `omni:rtx:post:bloom:spectral:scale` | `float` | `10` | — | Scale |
| `omni:rtx:post:bloom:spectral:wavelengths` | `float3` | `(380, 550, 770)` | — | Wavelengths |

### OmniRtxPostMatteObjectAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:matteobject:compositeShift` | `float` | `0` | — | Composite shift |
| `omni:rtx:post:matteobject:enabled` | `bool` | `1` | — | Enabled |
| `omni:rtx:post:matteobject:fadeOut` | `float` | `0` | — | Fade out |
| `omni:rtx:post:matteobject:shadowContrast` | `float` | `0` | — | Shadow contrast |
| `omni:rtx:post:matteobject:shadowsOnly` | `bool` | `0` | — | Shadows only |
| `omni:rtx:post:matteobject:useApproximateIBL` | `bool` | `0` | — | Use approximate IBL |
| `omni:rtx:post:matteObject:enableAmbientShadowCatcher` | `bool` | `0` | — | Enable ambient shadow catcher |
| `omni:rtx:post:matteObject:ambientShadowCatcherFactor` | `float` | `1.0` | — | Ambient shadow catcher ease Factor |
| `omni:rtx:post:matteObject:visibility:reflection` | `bool` | `0` | — | Visible in reflection |
| `omni:rtx:post:matteObject:visibility:refraction` | `bool` | `0` | — | Visible in refraction |

### OmniRtxPostCompositingAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:compositing:blackBackground` | `bool` | `0` | — | Force black background |
| `omni:rtx:post:compositing:postTonemapBackgroundComposite` | `bool` | `0` | — | Composite background after the tone mapping |
| `omni:rtx:post:compositing:doComposite` | `bool` | `1` | — | Do composite |
| `omni:rtx:post:compositing:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:post:compositing:outputAlpha` | `bool` | `0` | — | Output alpha |
| `omni:rtx:post:compositing:premultiply` | `bool` | `0` | — | Premultiply color by alpha |

### OmniRtxPostTonemapAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:tonemap:dither` | `float` | `0` | — | Dither strength |
| `omni:rtx:post:tonemap:operator` | `token` | `"acesApproximation"` | ["raw", "none", "reinhard", "modifiedReinhard", "hejiHableAlu", "hableUc2", "acesApproximation", "iray"] | Operator |

### OmniRtxPostTonemapIrayReinhardAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:tonemap:irayReinhard:burnHighlights` | `float` | `0.7` | — | Burn Highlights |
| `omni:rtx:post:tonemap:irayReinhard:burnHighlightsMaxComponent` | `bool` | `0` | — | Burn Highlights max Component |
| `omni:rtx:post:tonemap:irayReinhard:burnHighlightsPerComponent` | `bool` | `1` | — | Burn Highlights per Component |
| `omni:rtx:post:tonemap:irayReinhard:crushBlacks` | `float` | `0.5` | — | Crush Blacks |
| `omni:rtx:post:tonemap:irayReinhard:saturation` | `float` | `1` | — | Saturation |

### OmniRtxPostDofAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:dof:anisotropy` | `float` | `0` | — | Anisotropy |
| `omni:rtx:post:dof:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:post:dof:focalLength` | `float` | `100` | — | Focal length |
| `omni:rtx:post:dof:fStop` | `float` | `1` | — | f-stop |
| `omni:rtx:post:dof:subjectDistance` | `float` | `400` | — | Subject distance |

### OmniRtxPostMotionBlurAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:motionblur:enabled` | `bool` | `0` | — | Enabled |
| `omni:rtx:post:motionblur:exposureFraction` | `float` | `1` | — | Exposure Fraction |
| `omni:rtx:post:motionblur:maxBlurDiameterFraction` | `float` | `0.02` | — | Blur Diameter Fraction |
| `omni:rtx:post:motionblur:numSamples` | `int` | `8` | — | Number of Samples |

### OmniRtxPostTvNoiseAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:tvNoise:colorAmount` | `float` | `0.6` | — | Color Amount |
| `omni:rtx:post:tvNoise:enabled` | `bool` | `0` | — | TV Noise |
| `omni:rtx:post:tvNoise:filmGrain:amount` | `float` | `0.05` | — | Grain Amount |
| `omni:rtx:post:tvNoise:filmGrain:enabled` | `bool` | `1` | — | Enable Film Grain |
| `omni:rtx:post:tvNoise:filmGrain:size` | `float` | `1.6` | — | Grain Size |
| `omni:rtx:post:tvNoise:fixedTime:seed` | `bool` | `0` | — |  |
| `omni:rtx:post:tvNoise:fixedTime:seedCount` | `float` | `0` | — |  |
| `omni:rtx:post:tvNoise:ghostFlickering:enabled` | `bool` | `0` | — | Enable Ghost Flickering |
| `omni:rtx:post:tvNoise:lumAmount` | `float` | `1` | — | Luminance Amount |
| `omni:rtx:post:tvNoise:randomSplotches:enabled` | `bool` | `0` | — | Enable Random Splotches |
| `omni:rtx:post:tvNoise:scanlines:enabled` | `bool` | `0` | — | Enable Scanlines |
| `omni:rtx:post:tvNoise:scanlines:spread` | `float` | `1` | — | Scanline Spreading |
| `omni:rtx:post:tvNoise:scrollBug:enabled` | `bool` | `0` | — | Enable Scroll Bug |
| `omni:rtx:post:tvNoise:verticalLines:enabled` | `bool` | `0` | — | Enable Vertical Lines |
| `omni:rtx:post:tvNoise:vignetting:enabled` | `bool` | `0` | — | Enable Vignetting |
| `omni:rtx:post:tvNoise:vignetting:flickering:enabled` | `bool` | `0` | — | Enable Vignetting Flickering |
| `omni:rtx:post:tvNoise:vignetting:size` | `float` | `107` | — | Vignetting Size |
| `omni:rtx:post:tvNoise:vignetting:strength` | `float` | `0.7` | — | Vignetting Strength |
| `omni:rtx:post:tvNoise:waveDistortion:enabled` | `bool` | `0` | — | Enable Wavy Distortion |

### OmniRtxDebugSettingsAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:ambientOcclusion:denoiserMode` | `token` | `"aggressive"` | ["none", "aggressive", "simple"] |  |
| `omni:rtx:ambientOcclusion:maxSamples` | `int` | `9` | — | Maximum Samples Per Pixel |
| `omni:rtx:ambientOcclusion:minSamples` | `int` | `3` | — | Minimum Samples Per Pixel |
| `omni:rtx:ambientOcclusion:stratification:enabled` | `bool` | `1` | — | Ambient Occlusion Stratification |
| `omni:rtx:ambientOcclusion:temporalSqrtLength` | `int` | `3` | — |  |
| `omni:rtx:debug:addTileGpuAnnotations` | `bool` | `0` | — |  |
| `omni:rtx:debug:enableDebugUtils` | `bool` | `0` | — |  |
| `omni:rtx:debug:onlyOpaqueRayFlags` | `bool` | `0` | — | Hide Geometry That Uses Opacity (debug) |
| `omni:rtx:debug:onlyDiffuse` | `bool` | `0` | — | Only Diffuse Lighting (debug) |
| `omni:rtx:debug:valueBool0` | `bool` | `0` | — |  |
| `omni:rtx:debug:valueBool1` | `bool` | `0` | — |  |
| `omni:rtx:debug:valueBool2` | `bool` | `0` | — |  |
| `omni:rtx:debug:valueBool3` | `bool` | `0` | — |  |
| `omni:rtx:debug:valueFloat0` | `float` | `0` | — |  |
| `omni:rtx:debug:valueFloat1` | `float` | `0` | — |  |
| `omni:rtx:debug:valueFloat2` | `float` | `0` | — |  |
| `omni:rtx:debug:valueFloat3` | `float` | `0` | — |  |
| `omni:rtx:debug:view:allowDebugViewOnMgpu` | `bool` | `0` | — |  |
| `omni:rtx:debug:view:drawDebugOverTarget` | `bool` | `0` | — |  |
| `omni:rtx:debug:view:enablePreTonemap` | `bool` | `0` | — |  |
| `omni:rtx:debug:view:heatMapColorPalette` | `int` | `0` | — |  |
| `omni:rtx:debug:view:heatMapMaxAnyHitCount` | `int` | `10` | — |  |
| `omni:rtx:debug:view:heatMapMaxIntersectionCount` | `int` | `10` | — |  |
| `omni:rtx:debug:view:heatMapMaxTime` | `float` | `500` | — |  |
| `omni:rtx:debug:view:heatMapOverlayHeatMapScale` | `bool` | `1` | — |  |
| `omni:rtx:debug:view:heatMapPass` | `int` | `1` | — |  |
| `omni:rtx:debug:view:lightPowerMeter:enabled` | `int` | `0` | — |  |
| `omni:rtx:debug:view:pixelDebug:blinkInvalidValues` | `bool` | `0` | — |  |
| `omni:rtx:debug:view:pixelDebug:debugAsUint` | `bool` | `0` | — |  |
| `omni:rtx:debug:view:pixelDebug:debugPosX` | `float` | `0` | — |  |
| `omni:rtx:debug:view:pixelDebug:debugPosY` | `float` | `0` | — |  |
| `omni:rtx:debug:view:pixelDebug:enabled` | `bool` | `0` | — | Pixel Debug |
| `omni:rtx:debug:view:pixelDebug:enableFixedTextPos` | `bool` | `0` | — |  |
| `omni:rtx:debug:view:pixelDebug:magnifyingGlass:enabled` | `bool` | `0` | — | Magnifying Glass |
| `omni:rtx:debug:view:pixelDebug:magnifyingGlass:size` | `float` | `60` | — |  |
| `omni:rtx:debug:view:pixelDebug:magnifyingGlass:zoomFactor` | `float` | `0.2` | — |  |
| `omni:rtx:debug:view:pixelDebug:textColor` | `color3f` | `(0, 1e18, 0)` | — |  |
| `omni:rtx:debug:view:pixelDebug:textPosX` | `float` | `50` | — |  |
| `omni:rtx:debug:view:pixelDebug:textPosY` | `float` | `50` | — |  |
| `omni:rtx:debug:view:pixelDebug:textScaling` | `float` | `1` | — |  |
| `omni:rtx:debug:view:pixelDebug:useMouse` | `bool` | `1` | — |  |
| `omni:rtx:debug:view:scaleToTargetRes` | `bool` | `1` | — |  |
| `omni:rtx:debug:view:scaling` | `float` | `1` | — | Output Value Scaling |
| `omni:rtx:debug:view:selectedChannels` | `int` | `0` | — |  |
| `omni:rtx:debug:view:target` | `string` | `""` | — |  |
| `omni:rtx:debug:view:viewIndex` | `int` | `-1` | — |  |
| `omni:rtx:debugMaterialType` | `token` | `"Normal"` | ["Normal", "WhiteMode", "WhiteEmissive", "WhiteShadowCatcher"] |  |
| `omni:rtx:debugMaterialWhite` | `string` | `"DebugWhite"` | — |  |
| `omni:rtx:directLighting:diffuseBackscattering:enabled` | `bool` | `0` | — | Denoiseiffuse Backscattering |
| `omni:rtx:directLighting:diffuseBackscattering:extinction` | `float` | `1` | — |  |
| `omni:rtx:directLighting:diffuseBackscattering:shadowOffset` | `float` | `10` | — |  |
| `omni:rtx:directLighting:domeLight:approxIbl:enabled` | `bool` | `1` | — | DomeLight approximate IBL |
| `omni:rtx:directLighting:domeLight:denoisingTechnique` | `token` | `"ReLAX"` | ["None", "Optix", "SVGF", "IndirectDiffuse", "ReLAX", "NRD ReLAX", "NRD ReBLUR"] |  |
| `omni:rtx:directLighting:domeLight:enabled` | `bool` | `1` | — | DomeLight |
| `omni:rtx:directLighting:domeLight:reflections:enabled` | `bool` | `0` | — | DomeLight Reflection |
| `omni:rtx:directLighting:domeLight:sampleCount` | `int` | `2` | — |  |
| `omni:rtx:directLighting:sampledLighting:autoEnable` | `bool` | `1` | — |  |
| `omni:rtx:directLighting:sampledLighting:autoEnableLightCountThreshold` | `int` | `10` | — |  |
| `omni:rtx:directLighting:sampledLighting:clampSamplesPerPixelToNumberOfLights` | `bool` | `0` | — |  |
| `omni:rtx:directLighting:sampledLighting:clampSamplesToNumberOfLights` | `bool` | `1` | — |  |
| `omni:rtx:directLighting:sampledLighting:denoiserInputNormalType` | `token` | `"weightsum"` | ["weightsum", "maxweight", "toplayer", "glossylayer", "baselayer"] |  |
| `omni:rtx:directLighting:sampledLighting:denoisingTechnique` | `token` | `"NRD ReLAX"` | ["None", "Optix", "SVGF", "IndirectDiffuse", "ReLAX", "NRD ReLAX", "NRD ReBLUR"] |  |
| `omni:rtx:directLighting:sampledLighting:enabled` | `bool` | `1` | — | Sampled Lighting |
| `omni:rtx:directLighting:sampledLighting:enforceDenoiser` | `bool` | `0` | — |  |
| `omni:rtx:directLighting:sampledLighting:irradiance:denoiser:enabled` | `bool` | `0` | — | Denoise Irradiance Input |
| `omni:rtx:directLighting:sampledLighting:lightcache:spatialCache:enabled` | `bool` | `1` | — | Sampled Lighting Spatial Cache |
| `omni:rtx:directLighting:sampledLighting:lightcache:stochastic:refresh` | `bool` | `1` | — |  |
| `omni:rtx:directLighting:sampledLighting:lightcache:stochastic:updateMaxTileSize` | `uint` | `8` | — |  |
| `omni:rtx:directLighting:sampledLighting:lightcache:stochastic:useGGX` | `bool` | `1` | — |  |
| `omni:rtx:directLighting:sampledLighting:maxRoughness` | `float` | `0.3` | — |  |
| `omni:rtx:directLighting:sampledLighting:mis:enabled` | `bool` | `1` | — | Sampled Lighting MIS |
| `omni:rtx:directLighting:sampledLighting:optixDenoiser:blendFactor` | `float` | `0.085` | — |  |
| `omni:rtx:directLighting:sampledLighting:optixDenoiser:useAlbedo` | `bool` | `0` | — |  |
| `omni:rtx:directLighting:sampledLighting:optixDenoiser:useNormals` | `bool` | `0` | — |  |
| `omni:rtx:rt:directLighting:ris:meshLights` | `bool` | `0` | — | Enable RT mesh light sampling |
| `omni:rtx:rt:directLighting:meshLights:risCount` | `int` | `1` | — | Ris samples per light sample |
| `omni:rtx:directLighting:sampledLighting:separateGlossyDiffuseContrib` | `bool` | `0` | — |  |
| `omni:rtx:directLighting:separateGlossyDiffuseContrib` | `bool` | `0` | — |  |
| `omni:rtx:directLighting:showLights` | `bool` | `0` | — |  |
| `omni:rtx:domeLight:baking:spp` | `int` | `4` | — |  |
| `omni:rtx:domeLight:misCompensation` | `int` | `0` | — |  |
| `omni:rtx:domeLight:resolutionFactor` | `float` | `1` | — |  |
| `omni:rtx:fishEye:enablePrimDrawingAndSelection` | `bool` | `0` | — |  |
| `omni:rtx:fishEye:enableUnboundedResolutions` | `bool` | `0` | — |  |
| `omni:rtx:fishEye:enableUvCropping` | `bool` | `1` | — |  |
| `omni:rtx:fishEye:enableVerboseInfoLogging` | `bool` | `0` | — |  |
| `omni:rtx:fishEye:faceBorder` | `int` | `16` | — |  |
| `omni:rtx:fishEye:faceTintIntensity` | `float` | `0` | — |  |
| `omni:rtx:fishEye:useCubemap` | `bool` | `0` | — |  |
| `omni:rtx:fog:color` | `color3f` | `(0.75, 0.75, 0.75)` | — | Color |
| `omni:rtx:fog:colorIntensity` | `float` | `1` | — | Intensity |
| `omni:rtx:fog:distanceDensity` | `float` | `1` | — | Distance Density |
| `omni:rtx:fog:enabled` | `bool` | `0` | — | Fog |
| `omni:rtx:fog:endDist` | `float` | `5000` | — | End Distance to Camera |
| `omni:rtx:fog:height:density` | `float` | `1` | — | Height Density |
| `omni:rtx:fog:height:falloff` | `float` | `1` | — | Height Falloff |
| `omni:rtx:fog:start:distance` | `float` | `0` | — | Start Distance to Camera |
| `omni:rtx:fog:start:height` | `float` | `1` | — | Height-based Fog - Plane Height |
| `omni:rtx:fog:zUp:enabled` | `bool` | `0` | — | Height-based Fog - Use +Z Axis |
| `omni:rtx:indirectDiffuse:denoiser:enabled` | `bool` | `1` | — | Indirect Diffuse Denoiser |
| `omni:rtx:indirectDiffuse:denoiser:iterations` | `int` | `4` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:kernelRadius` | `int` | `32` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:method` | `int` | `0` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:temporal:enabled` | `bool` | `1` | — | Indirect Diffuse Temporal Denoiser |
| `omni:rtx:indirectDiffuse:denoiser:temporal:halfResolution` | `bool` | `0` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:temporal:maxHistory` | `int` | `100` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:temporal:phi:deviation` | `float` | `0.1` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:temporal:phi:normal` | `float` | `0.1` | — |  |
| `omni:rtx:indirectDiffuse:denoiser:temporal:phi:planarDistance` | `float` | `0.01` | — |  |
| `omni:rtx:indirectDiffuse:jitterScale` | `float` | `2` | — |  |
| `omni:rtx:indirectDiffuse:nrd:enabled` | `bool` | `1` | — | Indirect Diffuse NRD |
| `omni:rtx:indirectDiffuse:pstf:tileSize` | `int` | `5` | — |  |
| `omni:rtx:indirectDiffuse:restir:mode` | `int` | `1` | — |  |
| `omni:rtx:indirectDiffuse:separateCacheUpdate` | `bool` | `1` | — |  |
| `omni:rtx:indirectDiffuse:updateSampleCount` | `int` | `1` | — |  |
| `omni:rtx:lightspeed:lightspeed:nrd:reblur:diffuse:blurRadius` | `float` | `30` | — |  |
| `omni:rtx:lightspeed:lightspeed:nrd:reblur:diffuse:maxAccumulatedFrameNum` | `int` | `31` | — |  |
| `omni:rtx:lightspeed:lightspeed:nrd:reblur:diffuse:planeDistanceSensitivity` | `float` | `0.005` | — |  |
| `omni:rtx:lightspeed:nrd:common:denoisingRange` | `float` | `500000` | — |  |
| `omni:rtx:lightspeed:nrd:common:disocclusionThreshold` | `float` | `0.005` | — |  |
| `omni:rtx:lightspeed:nrd:relax:aTrousIterations` | `int` | `5` | — |  |
| `omni:rtx:lightspeed:nrd:relax:diffuseFastHistoryFrames` | `int` | `2` | — |  |
| `omni:rtx:lightspeed:nrd:relax:diffuseHistoryFrames` | `int` | `31` | — |  |
| `omni:rtx:lightspeed:nrd:relax:diffusePhiLuminance` | `float` | `2` | — |  |
| `omni:rtx:lightspeed:nrd:relax:disocclusionFixEdgeStoppingNormalPower` | `float` | `8` | — |  |
| `omni:rtx:lightspeed:nrd:relax:disocclusionFixMaxRadius` | `float` | `14` | — |  |
| `omni:rtx:lightspeed:nrd:relax:disocclusionFixNumFramesToFix` | `int` | `3` | — |  |
| `omni:rtx:lightspeed:nrd:relax:fireflySuppressionEnabled` | `bool` | `0` | — |  |
| `omni:rtx:lightspeed:nrd:relax:historyClampingColorBoxSigmaScale` | `float` | `1` | — |  |
| `omni:rtx:lightspeed:nrd:relax:luminanceEdgeStoppingRelaxation` | `float` | `0.5` | — |  |
| `omni:rtx:lightspeed:nrd:relax:normalEdgeStoppingRelaxation` | `float` | `0.3` | — |  |
| `omni:rtx:lightspeed:nrd:relax:roughnessEdgeStoppingRelaxation` | `float` | `0.3` | — |  |
| `omni:rtx:lightspeed:nrd:relax:spatialVarianceEstimationHistoryThreshold` | `int` | `3` | — |  |
| `omni:rtx:lightspeed:nrd:relax:specular:blurRadius` | `float` | `50` | — |  |
| `omni:rtx:lightspeed:nrd:relax:specular:fastHistoryFrames` | `int` | `8` | — |  |
| `omni:rtx:lightspeed:nrd:relax:specular:historyFrames` | `int` | `31` | — |  |
| `omni:rtx:lightspeed:nrd:relax:specular:phiLuminance` | `float` | `1` | — |  |
| `omni:rtx:lightspeed:nrd:relax:specular:varianceBoost` | `float` | `0` | — |  |
| `omni:rtx:lightspeed:relax:aTrousIterations` | `int` | `5` | — |  |
| `omni:rtx:lightspeed:relax:bicubicFilterForReprojectionEnabled` | `bool` | `1` | — |  |
| `omni:rtx:lightspeed:relax:diffuseAlpha` | `float` | `0.03` | — |  |
| `omni:rtx:lightspeed:relax:diffuseMomentsAlpha` | `float` | `0.1` | — |  |
| `omni:rtx:lightspeed:relax:diffusePhiLuminance` | `float` | `2` | — |  |
| `omni:rtx:lightspeed:relax:diffuseResponsiveAlpha` | `float` | `0.05` | — |  |
| `omni:rtx:lightspeed:relax:disocclusion:fix:enabled` | `bool` | `1` | — | ReLax Disocclusion |
| `omni:rtx:lightspeed:relax:disocclusion:fix:maxRadius` | `float` | `16` | — |  |
| `omni:rtx:lightspeed:relax:disocclusion:fix:numFramesToFix` | `float` | `3` | — |  |
| `omni:rtx:lightspeed:relax:disocclusion:fixEdge:stoppingNormalPower` | `float` | `50` | — |  |
| `omni:rtx:lightspeed:relax:disocclusion:fixEdge:stoppingZSigma` | `float` | `0.15` | — |  |
| `omni:rtx:lightspeed:relax:disocclusionFixUseFacetNormal` | `bool` | `0` | — |  |
| `omni:rtx:lightspeed:relax:facetNormalsForFireflySuppressionEnabled` | `bool` | `0` | — |  |
| `omni:rtx:lightspeed:relax:fireflySuppressionType` | `token` | `"Cross-Bilateral Median"` | ["None", "Cross-Bilateral Median", "Cross-Bilateral RCRS"] |  |
| `omni:rtx:lightspeed:relax:history:clamping:colorBoxSigmaScale` | `float` | `1` | — |  |
| `omni:rtx:lightspeed:relax:history:clamping:enabled` | `bool` | `1` | — | ReLax History Clamping |
| `omni:rtx:lightspeed:relax:lowResSpatialFilteringEnabled` | `bool` | `0` | — |  |
| `omni:rtx:lightspeed:relax:phi:depth` | `float` | `1.5` | — |  |
| `omni:rtx:lightspeed:relax:phi:normal` | `float` | `10` | — |  |
| `omni:rtx:lightspeed:relax:reprojection:roughnessWeightEnabled` | `bool` | `0` | — |  |
| `omni:rtx:lightspeed:relax:spatialVariance:estimationHistoryThreshold` | `int` | `4` | — |  |
| `omni:rtx:lightspeed:relax:specular:alpha` | `float` | `0.03` | — |  |
| `omni:rtx:lightspeed:relax:specular:momentsAlpha` | `float` | `0.1` | — |  |
| `omni:rtx:lightspeed:relax:specular:phiLuminance` | `float` | `3` | — |  |
| `omni:rtx:lightspeed:relax:specular:responsiveAlpha` | `float` | `0.25` | — |  |
| `omni:rtx:material:db:compileMdlAsLibrary` | `bool` | `0` | — |  |
| `omni:rtx:material:db:generatedCodeDiskMirror:directory` | `string` | `"../../../mdlGeneratedShaders"` | — |  |
| `omni:rtx:material:db:generateMipMaps` | `int` | `1` | — |  |
| `omni:rtx:material:db:MDLGeneratedCodeDiskMirror:enable` | `bool` | `0` | — |  |
| `omni:rtx:material:db:MDLGeneratedCodeDump` | `bool` | `0` | — |  |
| `omni:rtx:material:db:MDLGeneratedCodeDumpAll` | `bool` | `0` | — |  |
| `omni:rtx:material:db:MDLGeneratedCodeReplacement` | `bool` | `0` | — |  |
| `omni:rtx:material:db:MDLModificationList` | `string` | `""` | — |  |
| `omni:rtx:material:db:perInstanceOpacityToggle` | `bool` | `1` | — |  |
| `omni:rtx:material:db:rtSensorMaterialLogs` | `bool` | `0` | — |  |
| `omni:rtx:material:db:rtSensorNameToIdMap` | `string` | `""` | — |  |
| `omni:rtx:material:db:syncLoads` | `bool` | `0` | — |  |
| `omni:rtx:material:enableMDLDisplacement` | `bool` | `0` | — |  |
| `omni:rtx:material:enableRefraction` | `bool` | `1` | — |  |
| `omni:rtx:material:mdltranslator:distillTargetModel` | `string` | `"rtx_distiller"` | — |  |
| `omni:rtx:material:mdltranslator:foldParameterNames` | `string` | `""` | — |  |
| `omni:rtx:material:mdltranslator:mdlDistilling` | `bool` | `1` | — |  |
| `omni:rtx:material:mdltranslator:printMaterialStructure` | `bool` | `0` | — |  |
| `omni:rtx:material:normalMapRoughness` | `bool` | `1` | — |  |
| `omni:rtx:material:textures:anisotropy` | `int` | `16` | — |  |
| `omni:rtx:meshlights:enabled` | `bool` | `0` | — | Force disable mesh light processing |
| `omni:rtx:newDenoiser:enabled` | `bool` | `1` | — | New Denoiser |
| `omni:rtx:pt:adaptiveSampling:filterError` | `bool` | `1` | — | Filter Error |
| `omni:rtx:pt:adaptiveSampling:fixedSppIterations` | `uint` | `30` | — | Fixed Sample Per Pixel Iterations |
| `omni:rtx:pt:backgroundAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:cached:directionalJittering:enabled` | `bool` | `0` | — | Directional Jittering |
| `omni:rtx:pt:cached:distanceHash:base` | `float` | `1.5` | — |  |
| `omni:rtx:pt:cached:distanceHash:resolution` | `int` | `42` | — |  |
| `omni:rtx:pt:cached:distanceOverride` | `float` | `0` | — |  |
| `omni:rtx:pt:cached:dontResolveConflicts` | `bool` | `0` | — |  |
| `omni:rtx:pt:cached:forceReset` | `bool` | `0` | — |  |
| `omni:rtx:pt:cached:invCdf:enabled` | `bool` | `0` | — | Inverse CDF |
| `omni:rtx:pt:cached:maxAgeForEviction` | `int` | `512` | — |  |
| `omni:rtx:pt:cached:nanChecks:enabled` | `bool` | `0` | — | Nan Checks |
| `omni:rtx:pt:cached:retrace` | `float` | `2` | — |  |
| `omni:rtx:pt:cached:showDebugView` | `int` | `0` | — |  |
| `omni:rtx:pt:cached:spatialJittering:enabled` | `bool` | `1` | — | Spatial Jittering |
| `omni:rtx:pt:cached:temporalAlpha` | `float` | `0` | — |  |
| `omni:rtx:pt:cached:temporalReuse` | `int` | `2048` | — |  |
| `omni:rtx:pt:cached:truncated:associativity` | `int` | `0` | — |  |
| `omni:rtx:pt:cached:truncated:length` | `int` | `0` | — |  |
| `omni:rtx:pt:cached:truncated:probability` | `float` | `0` | — |  |
| `omni:rtx:pt:clampSpp` | `int` | `32` | — |  |
| `omni:rtx:pt:depth32BitAov` | `bool` | `0` | — |  |
| `omni:rtx:pt:diAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:diffuseFilterAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:dlss:enabled` | `bool` | `0` | — | DLSS |
| `omni:rtx:pt:domeLight:primaryRaysEvaluateDomelightMdlDirectly` | `bool` | `0` | — |  |
| `omni:rtx:pt:dynamicResolution:ratio` | `float` | `1` | — |  |
| `omni:rtx:pt:dynamicResolution:sppRatio` | `uint` | `1` | — |  |
| `omni:rtx:pt:fractionalCutoutOpacity` | `bool` | `1` | — |  |
| `omni:rtx:pt:giAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:directionalJittering:enabled` | `bool` | `0` | — | Directional Jittering |
| `omni:rtx:pt:lightcache:cached:distanceHash:base` | `float` | `1.5` | — |  |
| `omni:rtx:pt:lightcache:cached:distanceHash:resolution` | `int` | `8` | — |  |
| `omni:rtx:pt:lightcache:cached:distanceOverride` | `float` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:dontResolveConflicts` | `bool` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:forceReset` | `bool` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:invCdf:enabled` | `bool` | `0` | — | Inverse CDF |
| `omni:rtx:pt:lightcache:cached:maxAgeForEviction` | `int` | `-1` | — | Max Age For Eviction |
| `omni:rtx:pt:lightcache:cached:nanChecks:enabled` | `bool` | `1` | — | Nan Checks |
| `omni:rtx:pt:lightcache:cached:retrace` | `float` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:showDebugView` | `int` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:spatialJittering:enabled` | `bool` | `1` | — | Spatial Jittering |
| `omni:rtx:pt:lightcache:cached:temporalAlpha` | `float` | `0.2` | — |  |
| `omni:rtx:pt:lightcache:cached:temporalReuse` | `int` | `48` | — |  |
| `omni:rtx:pt:lightcache:cached:truncated:associativity` | `int` | `32` | — |  |
| `omni:rtx:pt:lightcache:cached:truncated:length` | `int` | `512` | — |  |
| `omni:rtx:pt:lightcache:cached:truncated:probability` | `float` | `0` | — |  |
| `omni:rtx:pt:lightcache:cached:truncatedLightCacheMaxUnexposedContrib` | `float` | `1024` | — |  |
| `omni:rtx:pt:lightcache:stochastic:useGGX` | `bool` | `1` | — |  |
| `omni:rtx:pt:maxSamplesPerLaunch` | `uint` | `460800` | — |  |
| `omni:rtx:pt:maxVolumeBounces` | `uint` | `15` | — |  |
| `omni:rtx:pt:mgpu:autoLoadBalancing:enabled` | `bool` | `1` | — | MultiGPU Auto LoadBalancing |
| `omni:rtx:pt:mgpu:autoLoadBalancingWeightGPU0` | `float` | `0.65` | — |  |
| `omni:rtx:pt:mgpu:broadcastLightCache` | `bool` | `0` | — |  |
| `omni:rtx:pt:mgpu:compressAlbedo` | `bool` | `1` | — |  |
| `omni:rtx:pt:mgpu:compressNormals` | `bool` | `1` | — |  |
| `omni:rtx:pt:mgpu:compressRadiance` | `bool` | `0` | — |  |
| `omni:rtx:pt:mgpu:maxPixelsPerRegionExponent` | `uint` | `7` | — |  |
| `omni:rtx:pt:mgpu:printLog` | `bool` | `0` | — |  |
| `omni:rtx:pt:mgpu:printWeights` | `bool` | `0` | — |  |
| `omni:rtx:pt:mgpu:resetAccumulation` | `bool` | `0` | — |  |
| `omni:rtx:pt:mgpu:showCompositingPattern` | `bool` | `0` | — |  |
| `omni:rtx:pt:mgpu:weightGpu0` | `float` | `0.65` | — |  |
| `omni:rtx:pt:multimatte:channel0` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel0_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel1` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel1_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel2` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel2_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel3` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel3_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel4` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel4_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel5` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel5_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel6` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel6_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel7` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel7_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel8` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel8_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel9` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel9_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel10` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel10_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel11` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel11_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel12` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel12_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel13` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel13_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel14` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel14_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel15` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel15_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel16` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel16_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel17` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel17_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel18` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel18_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel19` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel19_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel20` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel20_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel21` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel21_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel22` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel22_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channel23` | `int` | `-1` | — |  |
| `omni:rtx:pt:multimatte:channel23_isMat` | `bool` | `0` | — |  |
| `omni:rtx:pt:multimatte:channelCount` | `uint` | `0` | — |  |
| `omni:rtx:pt:nrc:enabled` | `bool` | `0` | — |  |
| `omni:rtx:pt:optixDenoiser:intensity` | `float` | `0` | — |  |
| `omni:rtx:pt:optixDenoiser:useAlbedo` | `bool` | `1` | — |  |
| `omni:rtx:pt:optixDenoiser:useNormals` | `bool` | `1` | — |  |
| `omni:rtx:pt:ptfog:ZUp` | `bool` | `0` | — |  |
| `omni:rtx:pt:ptvol:enabled` | `bool` | `0` | — | Pathtraced Volumes |
| `omni:rtx:pt:ptvol:fogHeightFallOff` | `float` | `10` | — | Fog Height Fall Off |
| `omni:rtx:pt:ptvol:maxRoughBouncesBeforeIgnoreVolume` | `int` | `2` | — |  |
| `omni:rtx:pt:ptvol:raySky` | `bool` | `0` | — |  |
| `omni:rtx:pt:ptvol:raySkyDomelight` | `bool` | `0` | — |  |
| `omni:rtx:pt:ptvol:raySkyScale` | `float` | `1` | — |  |
| `omni:rtx:pt:reflectionFilterAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:reflectionsAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:refractionFilterAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:refractionsAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:ris:meshLights` | `bool` | `0` | — | Enable PT mesh Light Sampling |
| `omni:rtx:pt:meshLights:risCount` | `int` | `1` | — | Ris samples per light sample |
| `omni:rtx:pt:roughnessClamp` | `float` | `0.15` | — |  |
| `omni:rtx:pt:rrDepth` | `uint` | `1` | — |  |
| `omni:rtx:pt:rrDepthVol` | `uint` | `1` | — |  |
| `omni:rtx:pt:rtptEnabled` | `bool` | `0` | — |  |
| `omni:rtx:pt:selfIllumAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:showLights:enabled` | `bool` | `0` | — | Show Lights |
| `omni:rtx:pt:svgf:alpha` | `float` | `0.5` | — |  |
| `omni:rtx:pt:svgf:enabled` | `bool` | `0` | — | SVGF |
| `omni:rtx:pt:svgf:momentsAlpha` | `float` | `0.5` | — |  |
| `omni:rtx:pt:svgf:numIterations` | `uint` | `4` | — |  |
| `omni:rtx:pt:svgf:phiColor` | `float` | `100` | — |  |
| `omni:rtx:pt:svgf:phiNormal` | `float` | `128` | — |  |
| `omni:rtx:pt:temporalAccumulation` | `bool` | `0` | — |  |
| `omni:rtx:pt:volumesAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:worldNormalsAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:worldPosAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:zDepthAOV` | `bool` | `0` | — |  |
| `omni:rtx:pt:zDepthMax` | `float` | `10000` | — |  |
| `omni:rtx:pt:zDepthMin` | `float` | `0.1` | — |  |
| `omni:rtx:realtime:mgpu:autoTiling:enabled` | `bool` | `1` | — | MultiGPU Auto-Tiling |
| `omni:rtx:realtime:mgpu:autoTiling:minMegaPixelsPerTile` | `float` | `0.4` | — |  |
| `omni:rtx:realtime:mgpu:masterDeviceLoadBalancingWeight` | `float` | `0.5` | — |  |
| `omni:rtx:realtime:mgpu:oversubscribe` | `bool` | `0` | — |  |
| `omni:rtx:realtime:mgpu:tileCount` | `int` | `1` | — |  |
| `omni:rtx:realtime:mgpu:tileOverlap` | `int` | `128` | — |  |
| `omni:rtx:reflections:denoiser:enabled` | `bool` | `1` | — | Reflection Denoising |
| `omni:rtx:reflections:giInReflections` | `bool` | `1` | — |  |
| `omni:rtx:reflections:halfResolution` | `bool` | `0` | — |  |
| `omni:rtx:reflections:importantLightsOnly` | `bool` | `0` | — |  |
| `omni:rtx:reflections:maxImportanceSamplingBias` | `float` | `0.5` | — |  |
| `omni:rtx:reflections:maxRoughnessForMinSamplingBias` | `float` | `0.25` | — |  |
| `omni:rtx:reflections:minImportanceSamplingBias` | `float` | `0.25` | — |  |
| `omni:rtx:reflections:minRoughnessForMaxSamplingBias` | `float` | `0` | — |  |
| `omni:rtx:reflections:outputDefaultAlbedoOn1stBounceLowRoughness` | `bool` | `1` | — |  |
| `omni:rtx:reflections:sampledLighting:clampSamplesPerPixelToNumberOfLights` | `bool` | `0` | — |  |
| `omni:rtx:reflections:sampledLighting:enabled` | `bool` | `1` | — | Reflection Sampled Lighting |
| `omni:rtx:reflections:sampledLighting:lightcache:spatialCache:enabled` | `bool` | `1` | — | Reflection Sampled Lighting Spatial Cache |
| `omni:rtx:reflections:sampledLighting:mis:enabled` | `bool` | `1` | — | Reflection Sampled Lighting MIS |
| `omni:rtx:reflections:sampledLighting:stochasticLCRefresh` | `bool` | `1` | — |  |
| `omni:rtx:rt:accumulation:enabled` | `bool` | `0` | — | Accumulation |
| `omni:rtx:rt:accumulationLimit` | `int` | `200` | — |  |
| `omni:rtx:rt:autoToggleDenoiserSettings` | `bool` | `1` | — |  |
| `omni:rtx:rt:cached:enabled` | `bool` | `1` | — | Cached Raytracing |
| `omni:rtx:rt:caustics:temporalFiltering:enabled` | `bool` | `0` | — | Caustic Temporal Filtering |
| `omni:rtx:rt:caustics:normalPhi` | `float` | `0.8` | — | Normal Phi |
| `omni:rtx:rt:caustics:positionPhi` | `float` | `2` | — | Position Phi |
| `omni:rtx:rt:caustics:useFrameSeed` | `bool` | `0` | — |  |
| `omni:rtx:rt:curve:radiusOffset` | `float` | `0` | — |  |
| `omni:rtx:rt:curve:radiusScale` | `float` | `1` | — |  |
| `omni:rtx:rt:debug:oneUberPermutation` | `bool` | `0` | — |  |
| `omni:rtx:rt:demoire` | `bool` | `1` | — |  |
| `omni:rtx:rt:demoireStrength` | `float` | `1` | — |  |
| `omni:rtx:rt:demoireStrengthBias` | `float` | `0` | — |  |
| `omni:rtx:rt:fp32Target` | `bool` | `0` | — |  |
| `omni:rtx:rt:globalVolumetricEffects:enabled` | `bool` | `0` | — | Global Volumetric Effects |
| `omni:rtx:rt:globalVolumetricEffectsFullRes:enabled` | `bool` | `0` | — | Full Resolution |
| `omni:rtx:rt:groundTruth:enabled` | `bool` | `0` | — | Raytracing Ground Truth |
| `omni:rtx:rt:groundTruth:loopingFunc` | `int` | `0` | — |  |
| `omni:rtx:rt:groundTruth:loopingHybridMax` | `int` | `8192` | — |  |
| `omni:rtx:rt:groundTruth:resolution:width` | `int` | `1920` | — |  |
| `omni:rtx:rt:groundTruth:resolution:height` | `int` | `1080` | — |  |
| `omni:rtx:rt:groundTruth:accumulateInEvenHigherRes` | `bool` | `0` | — |  |
| `omni:rtx:rt:groundTruth:exportInEvenHigherRes` | `bool` | `0` | — |  |
| `omni:rtx:rt:iesTextureRes` | `int` | `1024` | — |  |
| `omni:rtx:rt:indexdirect:enabled` | `bool` | `1` | — |  |
| `omni:rtx:rt:indexdirect:NanoVDBCompression` | `token` | `"None"` | ["None", "Fp4", "Fp8", "Fp16", "FpN"] | NanoVDBCompression |
| `omni:rtx:rt:indexdirect:NanoVDBCompressionDither` | `bool` | `1` | — |  |
| `omni:rtx:rt:indexdirect:showDetailledMemoryInfo` | `bool` | `0` | — |  |
| `omni:rtx:rt:indexdirect:svo:brickBorder` | `int` | `0` | — |  |
| `omni:rtx:rt:indexdirect:svo:brickSize` | `int3` | `(32, 32, 32)` | — |  |
| `omni:rtx:rt:indexdirect:volumeType` | `token` | `"IndeXSVO"` | ["IndeXSVO", "NanoVDB"] |  |
| `omni:rtx:rt:inscattering:anisotropyFactor` | `float` | `0` | — | Anisotropy Factor (g) |
| `omni:rtx:rt:inscattering:atmosphereHeight` | `float` | `1000` | — | Fog Height |
| `omni:rtx:rt:inscattering:blurSigma` | `float` | `1.2` | — | Inscatter Blur Sigma |
| `omni:rtx:rt:inscattering:debugMode` | `int` | `0` | — |  |
| `omni:rtx:rt:inscattering:debugProbeScale` | `float` | `0.1` | — |  |
| `omni:rtx:rt:inscattering:debugVoxelIdxX` | `uint` | `0` | — |  |
| `omni:rtx:rt:inscattering:debugVoxelIdxY` | `uint` | `0` | — |  |
| `omni:rtx:rt:inscattering:debugVoxelIdxZ` | `uint` | `0` | — |  |
| `omni:rtx:rt:inscattering:densityMult` | `float` | `1` | — | Density Multiplier |
| `omni:rtx:rt:inscattering:depthSlices` | `int` | `96` | — | Depth Slices Count |
| `omni:rtx:rt:inscattering:detailNoiseScale` | `float` | `0.002` | — |  |
| `omni:rtx:rt:inscattering:ditheringScale` | `float` | `10` | — | Inscatter Dithering Scale |
| `omni:rtx:rt:inscattering:flowDensityOffset` | `float` | `1` | — | Density Offset |
| `omni:rtx:rt:inscattering:flowDensityScale` | `float` | `250` | — | Density Scale |
| `omni:rtx:rt:inscattering:flowSampling:enabled` | `int` | `0` | — | Flow Sampling |
| `omni:rtx:rt:inscattering:inscatterUpsample` | `int` | `1` | — | Inscatter Upsample |
| `omni:rtx:rt:inscattering:lowPassFilter:enabled` | `bool` | `1` | — | Inscattering LowPass Filter |
| `omni:rtx:rt:inscattering:maxAccumulationFrames` | `int` | `128` | — | Accumulation Frames |
| `omni:rtx:rt:inscattering:maxDistance` | `float` | `50000` | — | Maximum inscattering Distance |
| `omni:rtx:rt:inscattering:maxFlowLayer` | `int` | `100` | — | Max Layer |
| `omni:rtx:rt:inscattering:maxRTSampleUnexposedIntensity` | `float` | `204800` | — |  |
| `omni:rtx:rt:inscattering:minFlowLayer` | `int` | `0` | — | Min Layer |
| `omni:rtx:rt:inscattering:noiseAnimationSpeedX` | `float` | `0` | — |  |
| `omni:rtx:rt:inscattering:noiseAnimationSpeedY` | `float` | `0` | — |  |
| `omni:rtx:rt:inscattering:noiseAnimationSpeedZ` | `float` | `0` | — |  |
| `omni:rtx:rt:inscattering:noiseNumOctaves` | `uint` | `4` | — |  |
| `omni:rtx:rt:inscattering:noiseScaleRangeMax` | `float` | `1` | — |  |
| `omni:rtx:rt:inscattering:noiseScaleRangeMin` | `float` | `0` | — |  |
| `omni:rtx:rt:inscattering:pixelRatio` | `int` | `8` | — | Pixel Density |
| `omni:rtx:rt:inscattering:singleScatteringAlbedo` | `color3f` | `(0.9, 0.9, 0.9)` | — | Single Scattering Albedo |
| `omni:rtx:rt:inscattering:sliceDistributionExponent` | `float` | `3` | — | Slice Distribution Exponent |
| `omni:rtx:rt:inscattering:spatialJitterScale` | `float` | `1` | — | Spatial Sample Jittering Scale |
| `omni:rtx:rt:inscattering:temporalJitterScale` | `float` | `0.5` | — | Temporal Reprojection Jittering Scale |
| `omni:rtx:rt:inscattering:transmittanceColor` | `color3f` | `(0.5, 0.5, 0.5)` | — | Transmittance Color |
| `omni:rtx:rt:inscattering:transmittanceMeasurementDistance` | `float` | `10000` | — | Transmittance Measurment Distance |
| `omni:rtx:rt:inscattering:use32bitPrecision` | `int` | `0` | — | Use 32-bit Precision |
| `omni:rtx:rt:inscattering:useDetailNoise` | `bool` | `0` | — | Apply Density Noise |
| `omni:rtx:rt:picking:minExtent` | `int` | `5` | — |  |
| `omni:rtx:rt:procedural:binderIntersector` | `bool` | `0` | — |  |
| `omni:rtx:rt:radianceClamp` | `float` | `0` | — |  |
| `omni:rtx:rt:subpixel:filterRadius` | `float` | `0.5` | — |  |
| `omni:rtx:rt:subpixel:mode` | `token` | `"box"` | ["box", "triangle", "gaussian"] |  |
| `omni:rtx:rt:subpixel:modulateRndSequence` | `bool` | `1` | — |  |
| `omni:rtx:rt:subpixel:uniformSubpixelJittering` | `bool` | `1` | — |  |
| `omni:rtx:rt:subsurface:denoiser:enabled` | `bool` | `0` | — | Subsurface Denoising |
| `omni:rtx:rt:subsurface:historyWeight` | `float` | `0.1` | — |  |
| `omni:rtx:rt:subsurface:shadowRayThreshold` | `float` | `0` | — |  |
| `omni:rtx:rt:subsurface:targetVariance` | `float` | `0.01` | — |  |
| `omni:rtx:rt:subsurface:transmission:denoiser:enabled` | `bool` | `1` | — | Subsurface Transmission Denoising |
| `omni:rtx:rt:subsurface:transmission:halfResolutionBackfaceLighting` | `bool` | `1` | — | Half-Resolution Rendering |
| `omni:rtx:rt:subsurface:transmission:ReSTIR:enabled` | `bool` | `0` | — | Sample Guiding |
| `omni:rtx:rt:subsurface:transmission:screenSpaceFallbackThresholdScale` | `float` | `0.1` | — | Screen-Space Fallback Threshold |
| `omni:rtx:rtpt:ris:meshLights` | `bool` | `0` | — | Enable RTPT mesh light sampling |
| `omni:rtx:rtpt:meshLights:risCount` | `int` | `1` | — | Ris samples per light sample |
| `omni:rtx:rtpt:subsurface:indirectHitInfo:enabled` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:splitGlass` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:splitClearcoat` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:splitRoughReflection` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:translucency:virtualMotion:enabled` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:fireflyFilter:enabled` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:fireflyFilter:maxUnexposedIntensityPerSample` | `float` | `3200` | — |  |
| `omni:rtx:rtpt:fireflyFilter:maxUnexposedIntensityPerSampleDiffuse` | `float` | `3200` | — |  |
| `omni:rtx:rtpt:fireflyFilter:maxPerEmissiveUnexposedIntensity` | `float` | `3200` | — |  |
| `omni:rtx:rtpt:splittingRoughnessThreshold` | `float` | `0.3` | — |  |
| `omni:rtx:rtpt:splitRateRoughReflection` | `float` | `0.75` | — |  |
| `omni:rtx:rtpt:modulatingRoughnessThreshold` | `float` | `0.04` | — |  |
| `omni:rtx:rtpt:spp` | `int` | `1` | — |  |
| `omni:rtx:rtpt:maxBounces` | `uint` | `3` | — |  |
| `omni:rtx:rtpt:extraSpecularAndTransmissiveBounces` | `uint` | `0` | — | Extra specular and transmissive bounces |
| `omni:rtx:rtpt:maxVolumeBounces` | `uint` | `3` | — |  |
| `omni:rtx:rtpt:usePathSplitting` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:cached:jitterScale` | `float` | `2` | — |  |
| `omni:rtx:rtpt:cached:maxBounces` | `int` | `4` | — |  |
| `omni:rtx:rtpt:cached:pstf:tileSize` | `int` | `5` | — |  |
| `omni:rtx:rtpt:cached:separateCacheUpdate` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:cached:separatePassCacheUpdate` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:cached:terminatePathOnFirstDiffuseHit` | `bool` | `1` | — |  |
| `omni:rtx:rtpt:cached:updateSampleCount` | `int` | `1` | — |  |
| `omni:rtx:rtpt:cached:useDirectionalBinningHash` | `bool` | `0` | — |  |
| `omni:rtx:rtpt:maxRoughness` | `float` | `0.3` | — |  |
| `omni:rtx:rtpt:rtCompatibility` | `bool` | `0` | — |  |
| `omni:rtx:rtpt:subsurface:randomWalk:enabled` | `bool` | `0` | — | Enable Random Walk SSS |
| `omni:rtx:rtpt:cfgpuCameraJitter` | `bool` | `1` | — | Enable CFGPU Camera Jitter for RTPT |
| `omni:rtx:sampledLighting:maxShadowRays` | `int` | `8` | — |  |
| `omni:rtx:scene:compaction:enabled` | `bool` | `1` | — | SceneDB Compaction |
| `omni:rtx:scene:cudaInterop:enabled` | `bool` | `0` | — | Cuda Interop |
| `omni:rtx:scene:domeLight:sdiio:enabled` | `bool` | `0` | — | DomeLight SDIIO |
| `omni:rtx:scene:forceSingleDomeLight` | `bool` | `0` | — | Force Single Dome Light |
| `omni:rtx:scene:enableUpdateBufferResizing` | `bool` | `1` | — |  |
| `omni:rtx:scene:enableXformUpdateLogging` | `bool` | `0` | — |  |
| `omni:rtx:scene:gatherColorToDisplayDevice` | `bool` | `0` | — |  |
| `omni:rtx:scene:GPUProceduralAABB:enabled` | `bool` | `1` | — | GPU Procedural AABB |
| `omni:rtx:scene:gpuSkinning:enabled` | `bool` | `1` | — | GPU Skinning |
| `omni:rtx:scene:hydra:alwaysTickRenderer` | `bool` | `0` | — |  |
| `omni:rtx:scene:hydra:geometrySyncLoads` | `bool` | `0` | — |  |
| `omni:rtx:scene:hydra:instancePickingEnabled` | `bool` | `1` | — | Instance Selection |
| `omni:rtx:scene:hydra:materialSyncLoads` | `bool` | `0` | — |  |
| `omni:rtx:scene:hydra:mdlMaterialWarmup` | `bool` | `0` | — |  |
| `omni:rtx:scene:hydra:minFreeDeviceMemory` | `int` | `1024` | — |  |
| `omni:rtx:scene:hydra:minFreeSystemMemory` | `int` | `3072` | — |  |
| `omni:rtx:scene:hydra:perMaterialSyncLoads` | `bool` | `0` | — |  |
| `omni:rtx:scene:hydra:primvars:silenceSizeWarnings` | `bool` | `0` | — |  |
| `omni:rtx:scene:hydra:releaseUnusedInstanceTransformMemory` | `bool` | `1` | — |  |
| `omni:rtx:scene:hydra:subdivision:refinementLevel` | `int` | `0` | — | Global Refinement Level |
| `omni:rtx:scene:hydra:TBNFrameMode` | `int` | `0` | — | Normal & Tangent Space Generation Mode |
| `omni:rtx:scene:hydra:uvsets:stIsDefaultUvSet` | `bool` | `1` | — | USD ST Main Texcoord as Default UV Set |
| `omni:rtx:scene:hydra:weldVertex` | `bool` | `1` | — |  |
| `omni:rtx:scene:instanceMaxScaleFilter` | `float` | `0` | — |  |
| `omni:rtx:scene:minPickPdf` | `float` | `0.0001` | — |  |
| `omni:rtx:scene:multiview:viewGridSize` | `int` | `1` | — |  |
| `omni:rtx:scene:renderMeterPerUnit` | `float` | `-1` | — | Renderer-Internal Meters Per Unit |
| `omni:rtx:scene:reprojection:motionDifference` | `bool` | `1` | — |  |
| `omni:rtx:scene:reprojection:positionDifferenceConstant` | `float` | `0.1` | — |  |
| `omni:rtx:scene:reservedInstances` | `int` | `16384` | — |  |
| `omni:rtx:scene:resetPtAccumOnAnimTimeChange` | `bool` | `0` | — |  |
| `omni:rtx:scene:sectionPlane:enabled` | `bool` | `0` | — | Scetion Plane |
| `omni:rtx:scene:sectionPlane:plane` | `float[]` | `[0, 0, 0, 0, 0]` | — |  |
| `omni:rtx:scene:sectionPlane:sectionLight` | `bool` | `1` | — |  |
| `omni:rtx:scene:selectionRaster:enabled` | `bool` | `0` | — | Selection Raster |
| `omni:rtx:scene:selectionRaster:initialize` | `bool` | `0` | — |  |
| `omni:rtx:scene:skipCmdListMangerDestroy` | `bool` | `0` | — |  |
| `omni:rtx:scene:skipMostLights` | `bool` | `0` | — | Use First Distant Light & First Dome Light Only |
| `omni:rtx:scene:tlasInstanceList:useElementArray` | `bool` | `0` | — |  |
| `omni:rtx:scene:translatedWorldSpace:enabled` | `bool` | `1` | — | Translated World-Space |
| `omni:rtx:scene:translucencyAsOpacity` | `bool` | `0` | — |  |
| `omni:rtx:scene:useDataDeduplication` | `bool` | `1` | — |  |
| `omni:rtx:scene:useGeometryValidation` | `bool` | `0` | — |  |
| `omni:rtx:scene:useSimulationTime` | `bool` | `0` | — |  |
| `omni:rtx:scene:useViewLightingMode` | `bool` | `0` | — |  |
| `omni:rtx:sdg:crossCamera:bilateral:normal:sigmaExponent` | `float` | `16` | — |  |
| `omni:rtx:sdg:crossCamera:bilateral:normal:weightCutoff` | `float` | `0.1` | — |  |
| `omni:rtx:sdg:crossCamera:bilateral:position:sigma` | `float` | `0.001` | — |  |
| `omni:rtx:sdg:crossCamera:bilateral:position:sigmaExponent` | `float` | `1.5` | — |  |
| `omni:rtx:sdg:crossCamera:bilateral:position:sigmaScale` | `float` | `100` | — |  |
| `omni:rtx:sdg:crossCamera:bilateral:position:weightCutoff` | `float` | `0.1` | — |  |
| `omni:rtx:sdg:crossCamera:debugOutput:reprojectedNormals` | `bool` | `0` | — |  |
| `omni:rtx:sdg:crossCamera:occlusion:checkRange` | `float` | `300` | — |  |
| `omni:rtx:sdg:crossCamera:occlusion:weightCutoff` | `float` | `0.1` | — |  |
| `omni:rtx:shadows:constantSeed` | `bool` | `1` | — |  |
| `omni:rtx:shadows:denoiser:enabled` | `bool` | `1` | — | Shadow Denoising |
| `omni:rtx:shadows:denoiser:quarterRes` | `bool` | `1` | — |  |
| `omni:rtx:shadows:enabled` | `bool` | `1` | — | Shadows Enabled |
| `omni:rtx:shadows:fractionalCutoutOpacity` | `bool` | `1` | — |  |
| `omni:rtx:shadows:sampleCount` | `int` | `1` | — |  |
| `omni:rtx:shadows:spatialFiltering:enabled` | `bool` | `1` | — | Shadow Sptial Filtering |
| `omni:rtx:shadows:stratifySamples` | `bool` | `1` | — |  |
| `omni:rtx:translucency:magnificationGbufferThreshold` | `float` | `0` | — |  |
| `omni:rtx:translucency:randomisedSamplingScale` | `float` | `2` | — |  |
| `omni:rtx:translucency:reflectionThroughputThreshold` | `float` | `0.1` | — | Secondary Bounce Reflection Throughput Threshold |
| `omni:rtx:translucency:worldEps` | `float` | `1` | — | World Epsilon Threshold |
| `omni:rtx:viewLighting:lightType` | `token` | `"distant"` | ["distant", "spot"] | Light Type |
| `omni:rtx:viewLighting:color` | `color3f` | `(1, 1, 1)` | — | Color |
| `omni:rtx:viewLighting:intensity` | `float` | `3000` | — | Intensity |
| `omni:rtx:viewLighting:angle` | `float` | `0` | — | Angle |
| `omni:rtx:viewLighting:radius` | `float` | `0.05` | — | Radius |
| `omni:rtx:viewLighting:coneAngle` | `float` | `90` | — | Cone Angle |
| `omni:rtx:viewLighting:coneSoftness` | `float` | `0` | — | Cone Softness |
| `omni:rtx:viewLighting:normalize` | `bool` | `1` | — | Normalize |

### OmniRtxPostDebugSettingsAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:post:aa:autoExposureMode` | `token` | `"prioritizePPAutoexposure"` | ["internal", "prioritizePPAutoexposure", "fixed"] |  |
| `omni:rtx:post:aa:exposure` | `float` | `1` | — |  |
| `omni:rtx:post:aa:exposureMultiplier` | `float` | `0.1` | — |  |
| `omni:rtx:post:aa:limitedOps` | `bool` | `1` | — | Limits AA Ops |
| `omni:rtx:post:aa:op` | `token` | `"dlss"` | ["none", "taa", "fxaa", "dlss", "rtxaa"] | Super Resolution |
| `omni:rtx:post:aa:sharpness` | `float` | `0.5` | — |  |
| `omni:rtx:post:aovConverter:linearizeDepthFilterBackground` | `bool` | `1` | — |  |
| `omni:rtx:post:backgroundZeroAlpha:backplateLuminanceScale` | `float` | `1000` | — |  |
| `omni:rtx:post:backgroundZeroAlpha:lensDistortionCorrection:enabled` | `bool` | `0` | — | Lens Distortion |
| `omni:rtx:post:backgroundZeroAlpha:sdiio:enabled` | `int` | `0` | — |  |
| `omni:rtx:post:backgroundZeroAlpha:sdiio:streamIndex` | `int` | `1` | — |  |
| `omni:rtx:post:chromab:modeB` | `token` | `"radial"` | ["radial", "barrel"] | Algorithm Blue |
| `omni:rtx:post:chromab:modeG` | `token` | `"radial"` | ["radial", "barrel"] | Algorithm Green |
| `omni:rtx:post:colorcorr:contrast` | `color3f` | `(1, 1, 1)` | — | Contrast |
| `omni:rtx:post:colorcorr:enabled` | `bool` | `0` | — | Color Correction |
| `omni:rtx:post:colorcorr:gain` | `color3f` | `(1, 1, 1)` | — | Gain |
| `omni:rtx:post:colorcorr:gamma` | `color3f` | `(1, 1, 1)` | — | Gamma |
| `omni:rtx:post:colorcorr:mode` | `int` | `0` | — | Mode |
| `omni:rtx:post:colorcorr:offset` | `color3f` | `(0, 0, 0)` | — | Offset |
| `omni:rtx:post:colorcorr:outputMode` | `token` | `"sRGBLinear"` | ["sRGBLinear", "ACEScg"] | Output Color Space |
| `omni:rtx:post:colorgrade:mode` | `int` | `0` | — | Mode |
| `omni:rtx:post:colorgrade:outputMode` | `token` | `"sRGBLinear"` | ["sRGBLinear", "ACEScg"] | Output Color Space |
| `omni:rtx:post:dlss:manualScaling` | `float` | `1` | — |  |
| `omni:rtx:post:dof:eightResThreshold` | `float` | `64` | — |  |
| `omni:rtx:post:dof:halfResThreshold` | `float` | `4` | — |  |
| `omni:rtx:post:dof:overrideEnabled` | `bool` | `0` | — |  |
| `omni:rtx:post:dof:quarterResThreshold` | `float` | `32` | — |  |
| `omni:rtx:post:fxaa:quality:edgeThreshold` | `float` | `0.166` | — |  |
| `omni:rtx:post:fxaa:quality:edgeThresholdMin` | `float` | `0.0833` | — |  |
| `omni:rtx:post:fxaa:quality:subPixel` | `float` | `0.75` | — |  |
| `omni:rtx:post:histogram:loglumrange` | `float` | `26` | — | Logarithmic Luminance Range |
| `omni:rtx:post:histogram:minloglum` | `float` | `-10` | — | Minimum Logarithmic Luminance |
| `omni:rtx:post:lensDistortion:cameraFocalLength` | `float` | `100` | — |  |
| `omni:rtx:post:lensDistortion:distortionMap` | `asset` | `@@` | — | Distortion Map |
| `omni:rtx:post:lensDistortion:enabled` | `bool` | `0` | — | Lens Distortion |
| `omni:rtx:post:lensDistortion:lensFocalLengthArray` | `float3` | `(10, 30, 50)` | — |  |
| `omni:rtx:post:lensDistortion:overrideEnabled` | `bool` | `0` | — |  |
| `omni:rtx:post:lensDistortion:undistortionMap` | `asset` | `@@` | — | Undistortion Map |
| `omni:rtx:post:lensFlares:anisoFlareFalloffX` | `float3` | `(450, 475, 500)` | — | Aniso Falloff X |
| `omni:rtx:post:lensFlares:anisoFlareFalloffY` | `float3` | `(10, 10, 10)` | — | Aniso Falloff Y |
| `omni:rtx:post:lensFlares:anisoFlareWeight` | `float` | `0.6` | — | Aniso Flare Weight |
| `omni:rtx:post:lensFlares:haloFlareFalloff` | `float3` | `(10, 10, 10)` | — | Halo Flare Falloff |
| `omni:rtx:post:lensFlares:haloFlareRadius` | `float3` | `(75, 75, 75)` | — | Halo Radius |
| `omni:rtx:post:lensFlares:haloFlareWeight` | `float` | `0.01` | — | Halo Flare Weight |
| `omni:rtx:post:lensFlares:isotropicFlareFalloff` | `float3` | `(50, 50, 50)` | — | Isotropic Flare Falloff |
| `omni:rtx:post:lensFlares:isotropicFlareWeight` | `float` | `0.4` | — | Isotropic Flare Weight |
| `omni:rtx:post:lensFlares:physicalSettings` | `bool` | `1` | — | Physical Model |
| `omni:rtx:post:lensFlares:use2KFFT` | `bool` | `0` | — |  |
| `omni:rtx:post:registeredCompositing:enabled` | `bool` | `1` | — | Use Registered Compositing |
| `omni:rtx:post:registeredCompositing:invertColorCorrection` | `bool` | `0` | — |  |
| `omni:rtx:post:registeredCompositing:invertToneMap` | `bool` | `0` | — |  |
| `omni:rtx:post:scaling:staticRatio` | `float` | `1` | — |  |
| `omni:rtx:post:taa:alpha` | `float` | `1` | — |  |
| `omni:rtx:post:taa:colorBoxSigma` | `float` | `2` | — |  |
| `omni:rtx:post:taa:samples` | `int` | `8` | — |  |
| `omni:rtx:post:tonemap:colorMode` | `token` | `"sRGBLinear"` | ["sRGBLinear", "ACEScg"] | Output Color Space |
| `omni:rtx:post:tonemap:enableSrgbToGamma` | `bool` | `1` | — | SRGB To Gamma Conversion |
| `omni:rtx:post:tonemap:exposureKey` | `float` | `0.25` | — |  |
| `omni:rtx:post:tonemap:maxWhiteLuminance` | `float` | `10` | — | Max White Luminance |
| `omni:rtx:post:tonemap:whitepoint` | `color3f` | `(1, 1, 1)` | — | White Point |
| `omni:rtx:post:tonemap:whiteScale` | `float` | `40.2` | — | White Scale Value |
| `omni:rtx:post:tonemap:wrapValue` | `float` | `0` | — | Wrap Value |
| `omni:rtx:viewTile:limit` | `uint` | `0` | — | Limit the number of view-tiles to this number |
| `omni:rtx:viewTile:resolution` | `int2` | `(0, 0)` | — | The resolution of an individual view-tile |
| `omni:rtx:viewTile:renderHistoryReset:requestId` | `int` | `0` | — | Render history reset request ID |
| `omni:rtx:viewTile:renderHistoryReset:tileIndices` | `float[]` | `[-2, -2, -2, -2, -2]` | — | Render history reset tile indices |

### OmniRtxXrAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:xr:xrdepth:hitType` | `token` | `"Opaque"` | ["Opaque", "First", "Refracted"] | Hit Type |
| `omni:rtx:xr:xrdepth:refraction:mask:enabled` | `bool` | `1` | — | Refraction Mask |
| `omni:rtx:xr:xrdepth:refraction:mask:maxCurvature` | `float` | `0.01` | — | Max Curvature |
| `omni:rtx:xr:xrdepth:refraction:mask:maxRefractionAngle` | `float` | `1.0` | — | Max Refraction Angle |

### OmniRtxXrFoveationAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:xr:foveation:unwarp` | `bool` | `0` | — | Unwarp Output |
| `omni:rtx:xr:foveation:unwarpedResolution` | `int2` | `(0, 0)` | — | Unwarped Resolution |
| `omni:rtx:xr:foveation:center` | `float2` | `(0.5, 0.5)` | — | Center |
| `omni:rtx:xr:foveation:radius` | `float2` | `(0.2, 0.2)` | — | Radius |

### OmniRtxSettingsParticleFieldAPI_1

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `omni:rtx:rtpt:gaussian:accumulatedDepth:enabled` | `bool` | `1` | — | Accumulate depth |
| `omni:rtx:rtpt:gaussian:accumulatedAlbedo:enabled` | `bool` | `1` | — | Accumulate albedo |
| `omni:rtx:rtpt:gaussian:maxGaussiansToAccumulate` | `int` | `48` | — | Max gaussians to accumulate |


## Standard USD camera/render declarations

### RenderSettingsBase

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `aspectRatioConformPolicy` | `token` | `"expandAperture"` | ["expandAperture", "cropAperture", "adjustApertureWidth", "adjustApertureHeight", "adjustPixelAspectRatio"] |  |
| `camera` | `relationship` | `(not declared)` | — |  |
| `dataWindowNDC` | `float4` | `(0, 0, 1, 1)` | — |  |
| `disableDepthOfField` | `bool` | `0` | — |  |
| `disableMotionBlur` | `bool` | `0` | — |  |
| `instantaneousShutter` | `bool` | `0` | — |  |
| `pixelAspectRatio` | `float` | `1` | — |  |
| `resolution` | `int2` | `(2048, 1080)` | — |  |

### RenderSettings

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `aspectRatioConformPolicy` | `token` | `` | ["expandAperture", "cropAperture", "adjustApertureWidth", "adjustApertureHeight", "adjustPixelAspectRatio"] |  |
| `camera` | `relationship` | `(not declared)` | — |  |
| `dataWindowNDC` | `float4` | `` | — |  |
| `disableDepthOfField` | `bool` | `` | — |  |
| `disableMotionBlur` | `bool` | `` | — |  |
| `includedPurposes` | `token[]` | `` | — |  |
| `instantaneousShutter` | `bool` | `` | — |  |
| `materialBindingPurposes` | `token[]` | `` | ["full", "preview", ""] |  |
| `pixelAspectRatio` | `float` | `` | — |  |
| `products` | `relationship` | `(not declared)` | — |  |
| `renderingColorSpace` | `token` | `(not declared)` | — |  |
| `resolution` | `int2` | `` | — |  |

### RenderVar

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `dataType` | `token` | `` | — |  |
| `sourceName` | `string` | `` | — |  |
| `sourceType` | `token` | `` | ["raw", "primvar", "lpe", "intrinsic"] |  |

### RenderProduct

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `aspectRatioConformPolicy` | `token` | `` | ["expandAperture", "cropAperture", "adjustApertureWidth", "adjustApertureHeight", "adjustPixelAspectRatio"] |  |
| `camera` | `relationship` | `(not declared)` | — |  |
| `dataWindowNDC` | `float4` | `` | — |  |
| `disableDepthOfField` | `bool` | `` | — |  |
| `disableMotionBlur` | `bool` | `` | — |  |
| `instantaneousShutter` | `bool` | `` | — |  |
| `orderedVars` | `relationship` | `(not declared)` | — |  |
| `pixelAspectRatio` | `float` | `` | — |  |
| `productName` | `token` | `` | — |  |
| `productType` | `token` | `` | ["raster", "deepRaster"] |  |
| `resolution` | `int2` | `` | — |  |

### Camera

| Attribute | Type | Declared default | Allowed tokens | Label |
|---|---|---|---|---|
| `clippingPlanes` | `float4[]` | `` | — |  |
| `clippingRange` | `float2` | `` | — |  |
| `exposure` | `float` | `` | — |  |
| `exposure:fStop` | `float` | `` | — |  |
| `exposure:iso` | `float` | `` | — |  |
| `exposure:responsivity` | `float` | `` | — |  |
| `exposure:time` | `float` | `` | — |  |
| `focalLength` | `float` | `` | — |  |
| `focusDistance` | `float` | `` | — |  |
| `fStop` | `float` | `` | — |  |
| `horizontalAperture` | `float` | `` | — |  |
| `horizontalApertureOffset` | `float` | `` | — |  |
| `projection` | `token` | `` | ["perspective", "orthographic"] |  |
| `proxyPrim` | `relationship` | `(not declared)` | — |  |
| `purpose` | `token` | `` | ["default", "render", "proxy", "guide"] |  |
| `shutter:close` | `double` | `` | — |  |
| `shutter:open` | `double` | `` | — |  |
| `stereoRole` | `token` | `` | ["mono", "left", "right"] |  |
| `verticalAperture` | `float` | `` | — |  |
| `verticalApertureOffset` | `float` | `` | — |  |
| `visibility` | `token` | `` | ["inherited", "invisible"] |  |
| `xformOpOrder` | `token[]` | `(not declared)` | — |  |

## Documented camera outputs

These are documented outputs, not an exhaustive runtime-discovered AOV list. The selected source documents only LdrColor and HdrColor for PathTracing and Minimal; additional AOV coverage must be measured separately. Do not infer MoonRay LPE support from an RTX output name.

| Mode | sourceName | Type | Shape | Description |
|---|---|---|---|---|
| Real-Time Path-Tracing | `LdrColor` | uint8 | `(H, W, 4)` | Tone-mapped color in sRGB space. Standard final image output suitable for display or saving as PNG/JPEG. |
| Real-Time Path-Tracing | `HdrColor` | float16 | `(H, W, 4)` | Linear-space HDR color preserving full scene luminance. Use for post-processing, compositing, or linear-space workflows. |
| Real-Time Path-Tracing | `NormalSD` | float32 | `(H, W, 4)` | World-space surface normals. |
| Real-Time Path-Tracing | `DepthSD` | float32 | `(H, W, 1)` | **Deprecated.** Unitless raster depth mapped from 1 (near clip plane) to 0 (far clip plane). Use `DistanceToImagePlaneSD` or `DistanceToCameraSD` instead. Known C API issue: currently returns all zeros through C readback. |
| Real-Time Path-Tracing | `DistanceToCameraSD` | float32 | `(H, W, 1)` | Euclidean distance from the camera origin to each surface point, in meters. |
| Real-Time Path-Tracing | `DistanceToImagePlaneSD` | float32 | `(H, W, 1)` | Perpendicular distance from the image plane to each surface point, in meters. |
| Real-Time Path-Tracing | `DiffuseAlbedoSD` | uint8 | `(H, W, 4)` | Diffuse surface albedo (base color without lighting). |
| Real-Time Path-Tracing | `Camera3dPositionSD` | float32 | `(H, W, 4)` | Camera-space 3D position of each visible surface point, in scene units. |
| Real-Time Path-Tracing | `SemanticSegmentation` | uint32 | `(H, W, 1)` | Per-pixel semantic ID. Decode `SemanticIdMap` to map each integer ID to its semantic label string. |
| Real-Time Path-Tracing | `SemanticIdMap` | uint8 | Buffer | Packed metadata buffer mapping semantic IDs to label strings. Each entry contains `uint32 id[4]`, label length, and label offset, followed by packed label bytes and a trailing entry count. |
| Path Tracing | `LdrColor` | uint8 | `(H, W, 4)` | Tone-mapped color in sRGB space. |
| Path Tracing | `HdrColor` | float16 | `(H, W, 4)` | Linear-space HDR color preserving full scene luminance. |
| Minimal | `LdrColor` | uint8 | `(H, W, 4)` | Tone-mapped color in sRGB space. |
| Minimal | `HdrColor` | float16 | `(H, W, 4)` | Linear-space HDR color preserving full scene luminance. |

## Reproduce

Run `tools/export_ovrtx_settings.py --help` with a Python interpreter containing `pxr.Sdf`. Supply the SDK package directory (containing `ovrtx` and its dist-info), matching public source checkout, and output directory. The script rejects mismatched Python configuration sources and records SHA-256 hashes. It does not initialize ovRTX or modify the source packages.

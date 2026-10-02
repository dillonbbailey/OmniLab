#!/usr/bin/env python3
"""Inventory an installed ovrtx package without loading its renderer.

Run with a Python environment containing pxr.Sdf. The USD files are read as
layers; the ovrtx library and its schema plugins are never imported/registered.
This is a source inventory, not a runtime capability or effective-value probe.
"""
import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pxr import Sdf, Usd


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Sdf.AssetPath):
        return v.path
    if isinstance(v, dict):
        return {str(k): value(x) for k, x in v.items()}
    try:
        return [value(x) for x in v]
    except TypeError:
        return str(v)


def flat(s):
    return " ".join(s.split()).replace("``", "`")


def cell(v):
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False)
    return flat(v).replace("|", "\\|")


def read_schema(path, surface, classes=None):
    layer = Sdf.Layer.FindOrOpen(str(path))
    if layer is None:
        raise RuntimeError(f"Cannot read schema: {path}")
    lines = path.read_text().splitlines()
    declarations = {}
    group = None
    for line_no, line in enumerate(lines, 1):
        m = re.match(r'^class\s+"([^"]+)"', line)
        if m:
            group = m[1]
        m = re.match(r'^    (?:uniform |custom )?(\w+(?:\[\])?) ([\w:]+)(?:\s*=\s*(.*?))?\s*(?:\(\s*)?$', line)
        if m:
            declarations[(group, m[2])] = (line_no, (m[3] or "").strip())
    result = []
    for prim in layer.rootPrims:
        if classes and prim.name not in classes:
            continue
        for prop in prim.properties:
            is_attr = isinstance(prop, Sdf.AttributeSpec)
            line_no, literal = declarations.get((prim.name, prop.name), (None, ""))
            result.append({
                "surface": surface, "group": prim.name, "name": prop.name,
                "type": str(prop.typeName) if is_attr else "relationship",
                "default": value(prop.default) if is_attr else None,
                "default_literal": literal,
                "has_default": prop.HasInfo("default") if is_attr else False,
                "allowed_tokens": value(prop.GetInfo("allowedTokens")) if is_attr else [],
                "display_name": prop.GetInfo("displayName"),
                "description": prop.GetInfo("documentation"),
                "source": str(path), "source_line": line_no,
                "status": "schema_declared_not_runtime_verified",
            })
    return result


def config_rows(source):
    types = source / "python/ovrtx/_src/types.py"
    module = ast.parse(types.read_text())
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "RendererConfig")
    rows = []
    for i, n in enumerate(cls.body):
        if not isinstance(n, ast.AnnAssign):
            continue
        doc = cls.body[i + 1] if i + 1 < len(cls.body) else None
        doc = doc.value.value if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) else ""
        rows.append({"surface": "RendererConfig", "group": "Renderer creation", "name": n.target.id,
                     "type": ast.unparse(n.annotation), "default": ast.literal_eval(n.value),
                     "default_literal": ast.unparse(n.value), "has_default": True,
                     "allowed_tokens": [], "display_name": n.target.id, "description": doc,
                     "source": str(types), "source_line": n.lineno,
                     "status": "public_API_declared_not_runtime_verified"})
    header = source / "include/ovrtx/ovrtx_types.h"
    text = header.read_text()
    c_rows = []
    for kind in ("bool", "string", "int64"):
        block = re.search(r'typedef enum ovrtx_config_' + kind + r'_t\s*\{(.*?)\}', text, re.S)
        for m in re.finditer(r'/\*\*(.*?)\*/\s*(OVRTX_CONFIG_\w+)', block[1], re.S):
            doc = flat(re.sub(r'\n\s*\* ?', ' ', m[1]))
            name = m[2]
            c_rows.append({"surface": "C configuration", "group": kind, "name": name,
                           "type": kind, "description": doc,
                           "retired": "DEPRECATED" in name,
                           "source": str(header),
                           "source_line": text[:block.start(1) + m.start(2)].count("\n") + 1})
    return rows, c_rows


def doc_rows(source):
    """Read all explicit renderer-setting tables in the SDK render-settings skill.

    Preserve these separately from schema defaults: the release sources disagree
    in some places, and a documented setting can be absent from the schema.
    """
    p = source / "skills/render-settings/SKILL.md"
    rows = []
    group = "Render settings"
    columns = []
    for line_no, line in enumerate(p.read_text().splitlines(), 1):
        if line.startswith("#"):
            group = line.lstrip("# ")
        if line.startswith("| Setting |"):
            columns = [x.strip().lower() for x in line.strip("| ").split("|")]
        if not re.match(r'\| `omni:rtx:', line):
            continue
        fields = [x.strip() for x in line.strip("| ").split("|")]
        entries = dict(zip(columns, fields))
        rows.append({"surface": "Documented RenderProduct", "group": group,
                     "name": fields[0].strip("`"), "type": fields[1].strip("`"),
                     "default_literal": entries.get("default", "").strip("`"), "default": None,
                     "has_default": "default" in entries, "allowed_tokens": [], "display_name": "",
                     "description": entries.get("description", ""),
                     "source": str(p), "source_line": line_no,
                     "status": "documented_not_runtime_verified"})
    return rows


def camera_outputs(source):
    p = source / "docs/sensors/cameras/outputs.rst"
    rows, mode, active = [], "", None
    lines = p.read_text().splitlines()
    for i, line in enumerate(lines, 1):
        m = re.search(r'\.\. tab-item:: (.*)', line)
        if m:
            mode = m[1]
        m = re.match(r'         \* - ``([^`]+)``', line)
        if m:
            active = {"mode": mode, "source_name": m[1], "cells": [], "source": str(p), "source_line": i}
            if m[1] != "sourceName":
                rows.append(active)
        elif active and line.startswith("           - "):
            active["cells"].append(flat(line[13:]))
        elif active and line.startswith("             ") and active["cells"]:
            active["cells"][-1] += " " + flat(line)
    for row in rows:
        cells = row.pop("cells")
        for key, x in zip(("format", "type", "shape", "description"), cells):
            row[key] = x
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-package", type=Path, required=True, help="Directory containing ovrtx/ and dist-info/")
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).date().isoformat(), help="Evidence date (YYYY-MM-DD)")
    args = parser.parse_args()
    sdk, source, out = args.sdk_package.resolve(), args.source_checkout.resolve(), args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    package = sdk / "ovrtx"
    schema = package / "bin/usd_plugins/rtx_settings/generatedSchema.usda"
    rtx = read_schema(schema, "RTX schema")
    usd_render = package / "bin/plugins/usd/usdRender/resources/generatedSchema.usda"
    usd_geom = package / "bin/plugins/usd/usdGeom/resources/generatedSchema.usda"
    standard = read_schema(usd_render, "USD render schema", {"RenderSettingsBase", "RenderSettings", "RenderProduct", "RenderVar"})
    standard += read_schema(usd_geom, "USD camera schema", {"Camera"})
    configs, c_configs = config_rows(source)
    documented = doc_rows(source)
    outputs = camera_outputs(source)
    # A local wheel and a similarly named source checkout need not be identical.
    source_types = source / "python/ovrtx/_src/types.py"
    wheel_types = package / "_src/types.py"
    if digest(source_types) != digest(wheel_types):
        raise RuntimeError("RendererConfig source differs from installed package; choose matching sources")
    indexed = defaultdict(list)
    for row in rtx:
        indexed[row["name"]].append(row)
    doc_only, differences = [], []
    for row in documented:
        if row["name"] not in indexed:
            doc_only.append(row)
            continue
        for s in indexed[row["name"]]:
            raw = row["default_literal"].replace("true", "True").replace("false", "False")
            try:
                dv = value(ast.literal_eval(raw))
                sv = s["default"]
                equal = dv == sv or (isinstance(dv, (int, float)) and isinstance(sv, (int, float)) and abs(dv-sv) < 1e-6)
            except (ValueError, SyntaxError):
                equal = raw == s["default_literal"]
            if (row['has_default'] and not equal) or row["type"] != s["type"]:
                differences.append({"name": row["name"], "schema_group": s["group"],
                                    "schema_type": s["type"], "schema_default": s["default_literal"],
                                    "documented_type": row["type"], "documented_default": row["default_literal"]})
    dist = next(sdk.glob("ovrtx-*.dist-info"))
    meta = {"generated_date": args.as_of, "package": dist.name.removesuffix(".dist-info"),
            "source_commit": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
            "extraction_openusd": list(Usd.GetVersion()),
            "scope": "All declarations in this package's rtx_settings schema, all public RendererConfig fields and C config keys, documented RenderProduct settings, and shipped Camera/UsdRender declarations. No live renderer queried; schema presence does not prove operational support.",
            "source_hashes": {str(p): digest(p) for p in (schema, usd_render, usd_geom, source_types, source / "include/ovrtx/ovrtx_types.h", source / "skills/render-settings/SKILL.md", source / "docs/sensors/cameras/outputs.rst")},
            "counts": {"rtx_schema_declarations": len(rtx), "rtx_schema_unique_names": len(indexed),
                       "rtx_schema_classes": len({r['group'] for r in rtx}), "python_config_fields": len(configs),
                       "active_C_config_keys": sum(not r['retired'] for r in c_configs),
                       "retired_C_config_keys": sum(r['retired'] for r in c_configs),
                       "standard_USD_declarations": len(standard), "documented_setting_rows": len(documented),
                       "documented_names_missing_from_schema": len({r['name'] for r in doc_only}),
                       "default_or_type_differences": len(differences)}}
    payload = {"metadata": meta, "renderer_config": configs, "c_configuration": c_configs,
               "rtx_schema": rtx, "standard_usd_schema": standard, "documented_settings": documented,
               "documented_missing_from_schema": doc_only, "schema_documentation_differences": differences,
               "documented_camera_outputs": outputs}
    (out / "ovrtx-settings.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    all_rows = configs + rtx + standard + documented
    columns = ["surface", "group", "name", "type", "default_literal", "has_default", "allowed_tokens", "display_name", "description", "source", "source_line", "status"]
    with (out / "ovrtx-settings.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, columns, extrasaction="ignore")
        w.writeheader()
        for row in all_rows:
            w.writerow({**row, "allowed_tokens": json.dumps(row['allowed_tokens']), "description": flat(row['description'])})
    with (out / "ovrtx-c-configuration.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, list(c_configs[0]))
        w.writeheader(); w.writerows(c_configs)
    md = ["# ovRTX settings inventory", "", f"Extracted {args.as_of} from `{meta['package']}`; source commit `{meta['source_commit']}`.", "",
          "This is a complete extraction of the selected **RTX settings schema and public creation configuration**, plus the SDK's documented settings and standard camera/render declarations. It is **not** a dump of effective settings in a running renderer, and it does not imply every shipped property is implemented by standalone ovRTX. Schema groups include legacy, debug and XR entries. Sensor-specific LiDAR/radar model parameters, shader inputs, SPG program parameters and private Carb settings are separate domains, outside this renderer/editor catalog.", "",
          "Schema defaults, SDK-documented defaults, application presets and effective runtime values are different. Keep them separate. An unset Python field (`None`) delegates to the native runtime; it does not mean false or zero. No runtime validation was performed.", "",
          "Use [JSON](ovrtx-settings.json) for full descriptions, source provenance and conflicts; [CSV](ovrtx-settings.csv) for filtering; [C config CSV](ovrtx-c-configuration.csv) for the public C keys.", "",
          "## Coverage", "", "| Item | Count |", "|---|---:|"]
    md += [f"| {k} | {v} |" for k, v in meta['counts'].items()]
    md += ["", "## Interpretation and authoring", "",
           "Documented `omni:rtx:*` rendering controls are authored on the selected RenderProduct. Camera lens/shutter properties belong on Camera prims; relationships and output declarations belong on RenderProduct/RenderVar. The raw schema class sections below preserve declarations and are not an authoring-target or supported-mode guarantee. Check global/camera/post-process scope and actual behavior before exposing each control.", "",
           "The 0.5 SDK uses `RealTimePathTracing`, `PathTracing`, and `MinimalRendering` for the public render-mode API. The shipped schema enumerates `Real-Time Path-Tracing`, `PathTracing`, and `Minimal`. Preserve this discrepancy; implement and test a version-specific adapter rather than directly feeding schema tokens to the runtime.", "",
           "Also check `renderingColorSpace` versus `omni:rtx:renderingColorSpace`. Do not silently rewrite assets. Retired creation controls `use_vulkan` and `dome_baking_resolution` must not be exposed as active 0.5 options. Dome MDL baking resolution is now a RenderProduct attribute but is consumed per scene; products sharing that scene must agree.", "",
           "Create an allowlist from successful GPU checks for ordinary UI controls. Keep unverified/legacy schema properties in an explicitly labeled advanced inspector. The schema's old Carb paths are historical metadata, not a promise that standalone ovRTX exposes a Carb settings API.", "",
           "## Schema/documentation differences", "", "| Attribute | Schema type/default | SDK documentation type/default |", "|---|---|---|"]
    for d in differences:
        md.append(f"| `{d['name']}` | `{cell(d['schema_type'])}` / `{cell(d['schema_default'])}` | `{cell(d['documented_type'])}` / `{cell(d['documented_default'])}` |")
    md += ["", "## Python renderer creation", "", "| Field | Type | Python default | Meaning and native-default notes |", "|---|---|---|---|"]
    for r in configs:
        md.append(f"| `{r['name']}` | `{cell(r['type'])}` | `None` | {cell(r['description'])} |")
    md += ["", "## C configuration keys", "", "| Key | Type | State | Meaning |", "|---|---|---|---|"]
    for r in c_configs:
        md.append(f"| `{r['name']}` | `{r['type']}` | {'Retired — reject' if r['retired'] else 'Public'} | {cell(r['description'])} |")
    for title, rows in [("Documented RenderProduct settings", documented), ("All shipped RTX schema declarations", rtx), ("Standard USD camera/render declarations", standard)]:
        md += ["", "## " + title, ""]
        groups = defaultdict(list)
        for row in rows:
            groups[row['group']].append(row)
        for group, group_rows in groups.items():
            md += ["### " + group, "", "| Attribute | Type | Declared default | Allowed tokens | Label |", "|---|---|---|---|---|"]
            for r in group_rows:
                default = r['default_literal'] if r['has_default'] else '(not declared)'
                md.append(f"| `{r['name']}` | `{r['type']}` | `{cell(default)}` | {cell(r['allowed_tokens']) if r['allowed_tokens'] else '—'} | {cell(r['display_name'])} |")
            md.append("")
    md += ["## Documented camera outputs", "", "These are documented outputs, not an exhaustive runtime-discovered AOV list. The selected source documents only LdrColor and HdrColor for PathTracing and Minimal; additional AOV coverage must be measured separately. Do not infer MoonRay LPE support from an RTX output name.", "", "| Mode | sourceName | Type | Shape | Description |", "|---|---|---|---|---|"]
    for r in outputs:
        md.append(f"| {r['mode']} | `{r['source_name']}` | {cell(r.get('type',''))} | {cell(r.get('shape',''))} | {cell(r.get('description',''))} |")
    md += ["", "## Reproduce", "", "Run `tools/export_ovrtx_settings.py --help` with a Python interpreter containing `pxr.Sdf`. Supply the SDK package directory (containing `ovrtx` and its dist-info), matching public source checkout, and output directory. The script rejects mismatched Python configuration sources and records SHA-256 hashes. It does not initialize ovRTX or modify the source packages.", ""]
    (out / "OVRTX_SETTINGS.md").write_text("\n".join(md))
    # Coverage checks compare the emitted inventory directly with Sdf's parser.
    checked_layer = Sdf.Layer.FindOrOpen(str(schema))
    assert len(rtx) == sum(len(p.properties) for p in checked_layer.rootPrims)
    assert len({(r['group'], r['name']) for r in rtx}) == len(rtx)
    assert all(r['source_line'] for r in rtx), "Unlocated schema declarations"
    print(json.dumps(meta['counts'], indent=2))


if __name__ == "__main__":
    main()

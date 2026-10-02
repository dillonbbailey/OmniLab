"""Repeatable, local P0 evidence. Run: omnilab-probe --output artifacts/p0."""
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import time
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/p0")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    import numpy as np
    from pxr import Sdr, Gf
    from .core.camera import ViewCamera, camera_payload
    from .core.document import Document
    from .core.fixtures import demo_document
    from .render.snapshot import publish, MODES
    from .render.backend import Backend

    report = dict(platform=platform.platform(), python=platform.python_version(),
                  packages={name: version(name) for name in ["ovrtx", "ovstage", "usd-core", "PySide6-Essentials", "numpy"]},
                  gpu=subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], text=True).strip(),
                  checks={}, limitations=["PT intermediate checkpoints are unverified; Cancel terminates the owned worker.",
                                         "The authoring usd-core build has no MaterialX Sdr node catalog; graph UI is P3.",
                                         "MinimalRendering + HdrColor + LdrColor returned stale color with an SDK tonemap error; excluded from the UI.",
                                         "The SDK reports a nonfatal MaterialX cache permission error under /usr/bin/cache with system Python."])
    report["checks"]["materialx_sdr_registry"] = bool(Sdr.Registry().GetShaderNodeByIdentifier("ND_open_pbr_surface_surfaceshader"))
    started = time.perf_counter()
    backend = Backend(output / "ovrtx.log")
    report["renderer_init_seconds"] = time.perf_counter() - started
    camera = ViewCamera(target=[-.5, .8, 0], distance=12, yaw=24, pitch=18)
    doc = demo_document()
    previous = None
    try:
        for mode in MODES:
            label = mode.lower()
            if mode == "MinimalRendering":
                # This combination must be tested from a fresh renderer; a preceding
                # HDR product can leave stale color buffers in this SDK build.
                backend.close()
                backend = Backend(output / "minimal-ovrtx.log")
            snapshot = publish(doc, output / label, camera.camera(1.6), (640, 400), mode, 8,
                               aovs=("LdrColor",) if mode == "MinimalRendering" else ("LdrColor", "HdrColor", "Depth"))
            try:
                load_ms = backend.load(snapshot)
                for _ in range(4 if mode == MODES[0] else 1):
                    arrays, hits, render_ms = backend.render(pick=[.45, .4, .6, .6])
                Image.fromarray(arrays["LdrColor"]).save(output / (label + ".png"))
                if arrays["LdrColor"][..., :3].std() < 1:
                    raise AssertionError("Empty or constant color output.")
                report["checks"][mode] = dict(status="passed", load_ms=load_ms, render_ms=render_ms,
                    outputs={name: dict(shape=list(a.shape), dtype=str(a.dtype), finite=bool(np.isfinite(a).all())) for name, a in arrays.items()},
                    hits=hits, color_std=float(arrays["LdrColor"][..., :3].std()),
                    scope="Fresh renderer; LdrColor only" if mode == "MinimalRendering" else "LdrColor + HdrColor + Depth")
                if mode == MODES[0]:
                    previous = arrays["LdrColor"].copy()
                    camera.orbit(80, 0)
                    backend.update_camera(camera_payload(camera.camera(1.6)))
                    moved = backend.render()[0]["LdrColor"]
                    Image.fromarray(moved).save(output / "camera-moved.png")
                    report["checks"]["camera_delta"] = dict(mean_pixel_difference=float(np.abs(moved.astype(float) - previous).mean()))
                    if report["checks"]["camera_delta"]["mean_pixel_difference"] <= 1:
                        raise AssertionError("Camera write did not visibly update the image.")
                    camera.orbit(-80, 0)
            except Exception:
                report["checks"][mode] = dict(status="failed", error=traceback.format_exc())
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        backend.close()
        backend = Backend(output / "materials-ovrtx.log")
        for material in ("openpbr", "mdl"):
            try:
                material_doc = demo_document(material)
                attr = "inputs:base_color" if material == "openpbr" else "inputs:diffuse_color_constant"
                data = dict(path="/World/Looks/Surface/Shader", group="Attributes", name=attr, value=[.8, .07, .02])
                material_doc.command("set_property", data)
                material_doc.command("set_transform", dict(path="/World/Sphere", values={"translate": [1, 1, 0]}))
                material_doc.save(output / (material + ".usda"))
                reopened = Document.open(output / (material + ".usda"))
                snapshot = publish(reopened, output / material, camera.camera(1.6), (640, 400))
                backend.load(snapshot)
                for _ in range(5):
                    arrays, _, ms = backend.render()
                Image.fromarray(arrays["LdrColor"]).save(output / (material + ".png"))
                view = camera.camera(1.6).frustum
                center = (view.ComputeViewMatrix() * view.ComputeProjectionMatrix()).Transform(Gf.Vec3d(1, 1, 0))
                x, y = round((center[0] + 1) * 320), round((1 - center[1]) * 200)
                rgb = arrays["LdrColor"][y-6:y+7, x-6:x+7, :3].mean(axis=(0, 1))
                if not rgb[0] > rgb[1] * 1.2:
                    raise AssertionError(f"Authored red {material} material did not render red at the sphere center: {rgb}")
                baseline = arrays["LdrColor"].copy()
                backend.update_attributes([dict(path=data["path"], attribute=attr, value=[.02, .8, .05], dtype="float32", lanes=3)])
                for _ in range(5):
                    changed = backend.render()[0]["LdrColor"]
                Image.fromarray(changed).save(output / (material + "-delta.png"))
                green = changed[y-6:y+7, x-6:x+7, :3].mean(axis=(0, 1))
                if not green[1] > green[0] * 1.2:
                    raise AssertionError(f"Native {material} color delta did not render green: {green}")
                material_doc.command("restore")
                material_doc.command("restore")
                report["checks"][material] = dict(status="passed", render_ms=ms,
                    authored_pixel_rgb=rgb.tolist(), delta_pixel_rgb=green.tolist(),
                    delta_mean_pixel_difference=float(np.abs(changed.astype(float) - baseline).mean()),
                    saved_color=list(reopened.stage.GetPrimAtPath(data["path"]).GetAttribute(attr).Get()),
                    undone_color=list(material_doc.stage.GetPrimAtPath(data["path"]).GetAttribute(attr).Get()))
            except Exception:
                report["checks"][material] = dict(status="failed", error=traceback.format_exc())
    finally:
        backend.close()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(output / "report.json")
    return 1 if any(isinstance(c, dict) and c.get("status") == "failed" for c in report["checks"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())

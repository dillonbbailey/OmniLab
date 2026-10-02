"""Publish a composed prim subtree into a portable reference/payload asset.

Imported only by the native USD worker. Publication captures current variant
selections and all authored time samples, without editing the source stage.
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile

from pxr import Ar, Gf, Sdf, Usd, UsdGeom, UsdShade

from .asset_publish import publish_destination
from .usd_project import anchor_asset, remap_assets


PRIM_COMPOSITION = {"specifier", "typeName", "references", "payload", "inheritPaths", "specializes",
                    "variantSelection", "variantSetNames", "instanceable", "clips", "clipSets", "relocates"}
PROPERTY_STRUCTURE = {"typeName", "custom", "variability", "default", "timeSamples", "connectionPaths", "targetPaths"}
TEXTURES = {".tx", ".exr", ".hdr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".bmp", ".dds", ".ktx", ".ktx2"}


def _binding(name):
    return name == "material:binding" or name.startswith("material:binding:")


def _shade(prim):
    return bool(prim) and (prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.NodeGraph) or prim.IsA(UsdShade.Shader))


class Publisher:
    def __init__(self, stage, path, name, folder, *, placement, frame, progress, layout="single"):
        self.source = stage
        self.selected = stage.GetPrimAtPath(path)
        if not self.selected or self.selected.IsPseudoRoot() or not self.selected.IsActive() or not self.selected.IsDefined():
            raise ValueError("Select an active, defined prim to publish.")
        if self.selected.IsA(UsdGeom.Subset):
            raise ValueError("A geometry subset needs its owning mesh. Select the mesh to publish its geometry and material subsets.")
        if placement not in ("local", "world"):
            raise ValueError("Choose local origin or world placement.")
        if layout not in ("single", "sections"):
            raise ValueError("Choose a single geometry payload or separate section payloads.")
        self.layout = layout
        self.name, self.folder = name, Path(folder)
        self.root = Sdf.Path("/" + name)
        self.placement, self.frame = placement, Usd.TimeCode(float(frame))
        self.progress = progress
        self.prims, self.paths, self.bindings = {}, {}, {}
        self.wrappers = {}
        self.resources = {}
        self.filename_paths = set()
        self.geometry = Sdf.Layer.CreateAnonymous("geometry.usda")
        self.materials = Sdf.Layer.CreateAnonymous("materials.usda")
        self.assignments = Sdf.Layer.CreateAnonymous("bindings.usda")
        self.contents = Sdf.Layer.CreateAnonymous("contents.usda")
        self.contents.subLayerPaths = [self.assignments.identifier, self.materials.identifier, self.geometry.identifier]
        self.stage = Usd.Stage.Open(self.contents)
        self.stage.SetEditTarget(self.geometry)
        UsdGeom.Xform.Define(self.stage, self.root)
        for scope in ("Geometry", "Materials", "Dependencies"):
            UsdGeom.Scope.Define(self.stage, self.root.AppendChild(scope))
        self.origin = UsdGeom.XformCache(self.frame).GetLocalToWorldTransform(self.selected)
        if placement == "local" and abs(self.origin.GetDeterminant()) < 1e-12:
            raise ValueError("The selected prim has a singular world transform. Use world placement or fix its zero scale.")
        self.origin_inverse = self.origin.GetInverse() if placement == "local" else Gf.Matrix4d(1)

    def add_tree(self, prim, scope):
        source_path = prim.GetPath()
        if source_path in self.prims:
            return
        target = self.root.AppendChild(scope).AppendChild(prim.GetName())
        if target in self.paths.values() or target in self.wrappers.values():
            target = target.GetParentPath().AppendChild(prim.GetName() + "_" + hashlib.sha256(str(source_path).encode()).hexdigest()[:8])
        if not UsdGeom.Xformable(prim) and not _shade(prim):
            self.wrappers[source_path] = target
            target = target.AppendChild(prim.GetName())
        predicate = Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract
        for child in Usd.PrimRange(prim, Usd.TraverseInstanceProxies(predicate)):
            if child.HasPayload() and not child.IsLoaded():
                raise ValueError(f"Load the payload at {child.GetPath()} before publishing this asset.")
            path = child.GetPath()
            if path not in self.prims:
                self.prims[path] = child
                self.paths[path] = path.ReplacePrefix(source_path, target)

    def dependency(self, path, owner):
        path = path.MakeAbsolutePath(owner.GetPath())
        if path == Sdf.Path.absoluteRootPath or path.GetPrimPath() in self.prims:
            return
        prim = self.source.GetPrimAtPath(path.GetPrimPath())
        if not prim:
            raise ValueError(f"Missing prim dependency {path} used by {owner.GetPath()}.")
        if self.selected.GetPath().HasPrefix(prim.GetPath()):
            raise ValueError(f"{owner.GetPath()} depends on ancestor {path}. Publish a containing prim instead.")
        if _shade(prim):
            # Include the enclosing network when a connection targets one shader.
            parent = prim.GetParent()
            while parent and _shade(parent):
                prim, parent = parent, parent.GetParent()
        self.add_tree(prim, "Materials" if _shade(prim) else "Dependencies")

    def gather(self):
        self.add_tree(self.selected, "Materials" if _shade(self.selected) else "Geometry")
        scanned = set()
        while set(self.prims) - scanned:
            for path in sorted(set(self.prims) - scanned):
                prim = self.prims[path]
                scanned.add(path)
                for prop in prim.GetAuthoredProperties():
                    if _binding(prop.GetName()):
                        continue  # Resolved below, including inherited/collection bindings.
                    targets = prop.GetConnections() if isinstance(prop, Usd.Attribute) else prop.GetTargets()
                    for target in targets:
                        self.dependency(target, prim)
                if UsdGeom.Imageable(prim) or prim.IsA(UsdGeom.Subset):
                    bindings = {}
                    for purpose in (UsdShade.Tokens.allPurpose, UsdShade.Tokens.preview, UsdShade.Tokens.full):
                        material, relationship = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(purpose)
                        if material:
                            bindings[purpose] = material.GetPath()
                            self.dependency(material.GetPath(), prim)
                        elif relationship and relationship.GetTargets():
                            raise ValueError(f"Unresolved material binding on {path}: {relationship.GetTargets()}")
                    self.bindings[path] = bindings
        # Imported MaterialX graphs may use string-valued filename inputs.
        # Publish these as assets so USD resolves the relocated resources.
        from omnilab.materials.catalog import default_catalog
        catalog = default_catalog()
        for prim in self.prims.values():
            shader = UsdShade.Shader(prim)
            shader_id = shader.GetIdAttr().Get() if shader else None
            if shader_id in catalog.definitions:
                for name, definition in catalog.definition(shader_id).inputs.items():
                    if definition.type == "filename":
                        prop = prim.GetAttribute("inputs:" + name)
                        pending = [prop] if prop else []
                        while pending:
                            prop = pending.pop()
                            if prop.GetPath() in self.filename_paths:
                                continue
                            self.filename_paths.add(prop.GetPath())
                            pending.extend(p for path in prop.GetConnections()
                                           if (p := self.source.GetAttributeAtPath(path)))
        # Material networks already inside the selection also belong in Materials.
        for path in sorted(self.prims, key=lambda p: p.pathElementCount):
            prim = self.prims[path]
            if _shade(prim) and not _shade(prim.GetParent()) and not self.paths[path].HasPrefix(self.root.AppendChild("Materials")):
                target = self.root.AppendChild("Materials").AppendChild(prim.GetName())
                if target in self.paths.values():
                    target = target.GetParentPath().AppendChild(prim.GetName() + "_" + hashlib.sha256(str(path).encode()).hexdigest()[:8])
                for child in self.paths:
                    if child.HasPrefix(path):
                        self.paths[child] = child.ReplacePrefix(path, target)

    def map_path(self, path, owner):
        absolute = path.MakeAbsolutePath(owner.GetPath())
        if absolute == Sdf.Path.absoluteRootPath:
            return self.root
        target = self.paths.get(absolute.GetPrimPath())
        if target is None:
            raise ValueError(f"Unmapped dependency {absolute} on {owner.GetPath()}.")
        return absolute.ReplacePrefix(absolute.GetPrimPath(), target)

    def snapshot(self):
        """Flatten an isolated, population-masked view, then copy only our trees.

        The private session layer lets us expand instances without editing any
        source layer. Ancestor opinions still compose in the masked view; the
        existing placement/primvar/binding pass preserves their inherited effect.
        """
        self.progress("Flattening a temporary view of the selected asset and its dependencies…")
        roots = [path for path in sorted(self.prims, key=lambda p: p.pathElementCount)
                 if not any(parent in self.prims for parent in path.GetPrefixes()[:-1])]
        session = Sdf.Layer.CreateAnonymous("publish-session.usda")
        source_session = self.source.GetSessionLayer()
        if source_session:
            session.TransferContent(source_session)
            remap_assets(session, lambda path: anchor_asset(source_session, path))
        mask = Usd.StagePopulationMask(roots)
        working = Usd.Stage.OpenMasked(self.source.GetRootLayer(), session,
                                      self.source.GetPathResolverContext(), mask, Usd.Stage.LoadNone)
        working.MuteAndUnmuteLayers(self.source.GetMutedLayers(), [])
        working.SetInterpolationType(self.source.GetInterpolationType())
        working.SetLoadRules(self.source.GetLoadRules())
        working.SetEditTarget(session)
        # Flatten otherwise preserves instance prototype references. Expand only
        # the masked working view so CopySpec never leaves a prototype behind.
        while True:
            instances = [prim for prim in working.Traverse() if prim.IsInstance()]
            if not instances:
                break
            for prim in instances:
                prim.SetInstanceable(False)
        flat = working.Flatten(addSourceFileComment=False)
        selected = Sdf.Layer.CreateAnonymous("publish-selection.usda")
        for path in roots:
            Sdf.CreatePrimInLayer(selected, path.GetParentPath())
            if not Sdf.CopySpec(flat, path, selected, path):
                raise ValueError(f"Could not copy {path} from the temporary flattened stage.")
        self.snapshot_stage = Usd.Stage.Open(selected)
        return self.snapshot_stage

    def resource(self, asset, prop, time):
        if not asset.path:
            return Sdf.AssetPath()
        anchored = asset.resolvedPath or asset.path
        if not asset.resolvedPath:
            original = self.source.GetPropertyAtPath(prop.GetPath()) or prop
            for spec in original.GetPropertyStack(time):
                if spec.HasInfo("default") or not time.IsDefault() and spec.HasInfo("timeSamples"):
                    anchored = anchor_asset(spec.layer, asset.path)
                    break
        if anchored in self.resources:
            return Sdf.AssetPath(self.resources[anchored])
        udim = UsdShade.UdimUtils.IsUdimIdentifier(anchored)
        files = UsdShade.UdimUtils.ResolveUdimTilePaths(anchored, None) if udim else [(str(Ar.GetResolver().Resolve(anchored)), None)]
        if not files or not all(path for path, _ in files):
            raise ValueError(f"Missing asset file {asset.path} on {prop.GetPath()}.")
        filename = Path(Ar.SplitPackageRelativePathInner(anchored)[1] if Ar.IsPackageRelativePath(anchored) else anchored).name
        group = "textures" if Path(filename).suffix.lower() in TEXTURES else "resources"
        relative = Path(group) / hashlib.sha256(anchored.encode()).hexdigest()[:12] / filename
        for resolved, tile in files:
            target = self.folder / str(relative).replace("<UDIM>", tile or "")
            target.parent.mkdir(parents=True, exist_ok=True)
            if Path(resolved).is_file():
                shutil.copy2(resolved, target)
                if prop.GetName() == 'info:mdl:sourceAsset' and Path(resolved).suffix.lower() == '.mdl':
                    bundle = Path(resolved).parent
                    manifest_path = bundle / 'omnilab_bundle.json'
                    if not manifest_path.is_file():
                        raise ValueError('Load this MDL module through the Material Editor before publishing so imports and resources can be packaged: ' + resolved)
                    manifest = json.loads(manifest_path.read_text())
                    if manifest.get('format') != 'omnilab-mdl-bundle' or manifest.get('version') != 1:
                        raise ValueError('Unsupported MDL dependency manifest.')
                    for filename, digest in manifest['files'].items():
                        resource = (bundle / filename).resolve()
                        if Path(filename).is_absolute() or not resource.is_relative_to(bundle.resolve()) or not resource.is_file():
                            raise ValueError('Invalid MDL bundle resource: ' + filename)
                        if hashlib.sha256(resource.read_bytes()).hexdigest() != digest:
                            raise ValueError('MDL cache content changed; reload the original module before publishing.')
                        dependency = target.parent / filename
                        dependency.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(resource, dependency)
                    shutil.copy2(manifest_path, target.parent / manifest_path.name)
            else:
                resource = Ar.GetResolver().OpenAsset(Ar.ResolvedPath(resolved))
                if not resource:
                    raise ValueError(f"Cannot read asset file {resolved}.")
                with target.open("wb") as stream:
                    offset = 0
                    while offset < resource.GetSize():
                        count = min(8 * 1024 * 1024, resource.GetSize() - offset)
                        block = resource.Read(count, offset)
                        if not block:
                            raise OSError(f"Could not finish reading {resolved}.")
                        stream.write(block)
                        offset += len(block)
        self.resources[anchored] = "../" + relative.as_posix()
        self.progress(f"Copied {len(self.resources)} asset dependencies…")
        return Sdf.AssetPath(self.resources[anchored])

    def value(self, value, prop, time):
        if prop.GetPath() in self.filename_paths and isinstance(value, str):
            value = Sdf.AssetPath(os.path.expandvars(os.path.expanduser(value)).replace("<udim>", "<UDIM>").replace("%(UDIM)d", "<UDIM>"))
        if isinstance(value, Sdf.AssetPath):
            return self.resource(value, prop, time)
        if isinstance(value, Sdf.AssetPathArray):
            return Sdf.AssetPathArray([self.resource(item, prop, time) for item in value])
        if isinstance(value, Sdf.Path):
            return self.map_path(value, prop.GetPrim())
        return value

    def copy_property(self, source, target):
        if isinstance(source, Usd.Attribute):
            value_type = Sdf.ValueTypeNames.Asset if source.GetPath() in self.filename_paths else source.GetTypeName()
            prop = target.CreateAttribute(source.GetName(), value_type, source.IsCustom(), source.GetVariability())
            for time in [Usd.TimeCode.Default(), *map(Usd.TimeCode, source.GetTimeSamples())]:
                value = source.Get(time)
                if value is not None:
                    prop.Set(self.value(value, source, time), time)
                elif source.GetResolveInfo(time).ValueIsBlocked():
                    prop.Set(Sdf.ValueBlock(), time)
            if source.HasAuthoredConnections():
                prop.SetConnections([self.map_path(p, source.GetPrim()) for p in source.GetConnections()])
        else:
            prop = target.CreateRelationship(source.GetName(), source.IsCustom())
            prop.SetTargets([self.map_path(p, source.GetPrim()) for p in source.GetTargets()])
        for key, value in source.GetAllAuthoredMetadata().items():
            if key not in PROPERTY_STRUCTURE:
                prop.SetMetadata(key, value)

    def transform_times(self, prim):
        times = set()
        while prim and not prim.IsPseudoRoot():
            xform = UsdGeom.Xformable(prim)
            if xform:
                times.update(xform.GetTimeSamples())
                if xform.GetResetXformStack():
                    break
            prim = prim.GetParent()
        return times

    def detached(self, prim):
        return self.paths[prim.GetPath()].GetParentPath() != self.paths.get(prim.GetParent().GetPath())

    def copy_transform(self, prim, target, *, wrapper=False):
        source_xform = UsdGeom.Xformable(prim)
        if not source_xform and not wrapper:
            return
        detached = self.detached(prim)
        if not detached and not source_xform.GetResetXformStack():
            return  # Its authored local transform stack is already portable.
        xform = UsdGeom.Xformable(target)
        for attr in list(target.GetAttributes()):
            if attr.GetName().startswith("xformOp:"):
                target.RemoveProperty(attr.GetName())
        xform.ClearXformOpOrder()
        op = xform.AddTransformOp()
        times = self.transform_times(prim)
        if not detached:
            times.update(self.transform_times(prim.GetParent()))
        for time in [Usd.TimeCode.Default(), *map(Usd.TimeCode, sorted(times | ({self.frame.GetValue()} if times else set())))]:
            cache = UsdGeom.XformCache(time)
            world = cache.GetLocalToWorldTransform(prim)
            if detached:
                matrix = world * self.origin_inverse
            else:
                parent = cache.GetLocalToWorldTransform(prim.GetParent())
                if abs(parent.GetDeterminant()) < 1e-12:
                    raise ValueError(f"Cannot detach reset transform {prim.GetPath()} from a singular parent transform.")
                matrix = world * parent.GetInverse()
            op.Set(matrix, time)

    def copy(self):
        snapshot = self.snapshot()
        self.progress(f"Publishing {len(self.prims)} prims…")
        for path in sorted(self.prims, key=lambda p: (self.paths[p].pathElementCount, str(self.paths[p]))):
            prim, target_path = self.prims[path], self.paths[path]
            composed = snapshot.GetPrimAtPath(path)
            if not composed:
                raise ValueError(f"Missing prim in publishing snapshot: {path}")
            self.stage.SetEditTarget(self.materials if target_path.HasPrefix(self.root.AppendChild("Materials")) else self.geometry)
            if path in self.wrappers:
                wrapper = UsdGeom.Xform.Define(self.stage, self.wrappers[path]).GetPrim()
                self.copy_transform(prim, wrapper, wrapper=True)
            target = self.stage.DefinePrim(target_path, prim.GetTypeName())
            for key, value in composed.GetAllAuthoredMetadata().items():
                if key not in PRIM_COMPOSITION:
                    if key == "kind":
                        value = "subcomponent"
                    elif key == "customData":
                        value = copy.deepcopy(value)
                        # Published shaders must not reconnect to the source
                        # document or overwrite themselves from its saved graph.
                        for namespace, names in (("editor", ("usdCamera", "usdTransform")),
                                                 ("moonrayEditor", ("materialSync", "previewCamera"))):
                            data = value.get(namespace)
                            if isinstance(data, dict):
                                for name in names:
                                    data.pop(name, None)
                                if not data:
                                    value.pop(namespace)
                    target.SetMetadata(key, value)
            for prop in composed.GetAuthoredProperties():
                if not _binding(prop.GetName()):
                    self.copy_property(prop, target)
            self.copy_transform(prim, target)
            if self.detached(prim):
                # Primvars and purpose authored above the selected subtree would
                # otherwise disappear when it is referenced as its own asset.
                for primvar in UsdGeom.PrimvarsAPI(prim).FindPrimvarsWithInheritance():
                    if primvar.GetAttr().GetPrim() != prim:
                        self.copy_property(primvar.GetAttr(), target)
                        if primvar.IsIndexed():
                            self.copy_property(primvar.GetIndicesAttr(), target)
                imageable = UsdGeom.Imageable(prim)
                if imageable:
                    UsdGeom.Imageable(target).CreatePurposeAttr(imageable.ComputePurpose())
                    times = set()
                    ancestor = prim
                    while ancestor and not ancestor.IsPseudoRoot():
                        attr = ancestor.GetAttribute("visibility")
                        if attr:
                            times.update(attr.GetTimeSamples())
                        ancestor = ancestor.GetParent()
                    attr = UsdGeom.Imageable(target).CreateVisibilityAttr()
                    for time in [Usd.TimeCode.Default(), *map(Usd.TimeCode, sorted(times))]:
                        attr.Set(imageable.ComputeVisibility(time), time)
        self.stage.SetEditTarget(self.assignments)
        for path, bindings in self.bindings.items():
            if bindings:
                api = UsdShade.MaterialBindingAPI.Apply(self.stage.GetPrimAtPath(self.paths[path]))
                for purpose, material in bindings.items():
                    api.Bind(UsdShade.Material(self.stage.GetPrimAtPath(self.paths[material])),
                             bindingStrength=UsdShade.Tokens.weakerThanDescendants, materialPurpose=purpose)

    def write(self):
        payload = self.folder / "payload"
        payload.mkdir()
        (self.folder / "textures").mkdir(exist_ok=True)
        for layer in (self.geometry, self.materials, self.assignments, self.contents):
            layer.defaultPrim = self.name
            layer.pseudoRoot.SetInfo("upAxis", UsdGeom.GetStageUpAxis(self.source))
            layer.pseudoRoot.SetInfo("metersPerUnit", UsdGeom.GetStageMetersPerUnit(self.source))
            layer.startTimeCode = self.source.GetStartTimeCode()
            layer.endTimeCode = self.source.GetEndTimeCode()
            layer.timeCodesPerSecond = self.source.GetTimeCodesPerSecond()
            layer.framesPerSecond = self.source.GetFramesPerSecond()
        for layer, filename, encoding in ((self.materials, "materials.usda", "usda"),
                                          (self.assignments, "bindings.usda", "usda")):
            if not layer.Export(str(payload / filename), args={"format": encoding}):
                raise OSError(f"Could not write {filename}.")
        sections = []
        if self.layout == "sections":
            from .usd_asset_sections import write_sections
            sections = write_sections(self, payload)
        else:
            if not self.geometry.Export(str(payload / "geometry.usdc")):
                raise OSError("Could not write geometry.usdc.")
            contents = Sdf.Layer.CreateAnonymous("contents.usda")
            contents.TransferContent(self.contents)
            contents.subLayerPaths = ["./bindings.usda", "./materials.usda", "./geometry.usdc"]
            if not contents.Export(str(payload / "contents.usda")):
                raise OSError("Could not write the asset payload.")
        interface = Usd.Stage.CreateInMemory()
        root = UsdGeom.Xform.Define(interface, self.root).GetPrim()
        interface.SetDefaultPrim(root)
        UsdGeom.SetStageUpAxis(interface, UsdGeom.GetStageUpAxis(self.source))
        UsdGeom.SetStageMetersPerUnit(interface, UsdGeom.GetStageMetersPerUnit(self.source))
        interface.SetStartTimeCode(self.source.GetStartTimeCode())
        interface.SetEndTimeCode(self.source.GetEndTimeCode())
        interface.SetTimeCodesPerSecond(self.source.GetTimeCodesPerSecond())
        interface.SetFramesPerSecond(self.source.GetFramesPerSecond())
        model = Usd.ModelAPI(root)
        model.SetKind("component")
        model.SetAssetName(self.name)
        # Compute bounds before introducing the relative payload on an anonymous
        # interface layer. They remain accessible when the published payload is unloaded.
        self.stage.SetEditTarget(self.contents)
        Usd.ModelAPI(self.stage.GetPrimAtPath(self.root)).SetKind("component")
        bounds_model = UsdGeom.ModelAPI.Apply(self.stage.GetPrimAtPath(self.root))
        hints = UsdGeom.ModelAPI.Apply(root)
        times = {t for p in self.stage.Traverse() for a in p.GetAttributes() for t in a.GetTimeSamples()}
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render", "proxy"], useExtentsHint=False)
        for time in [Usd.TimeCode.Default(), *map(Usd.TimeCode, sorted(times))]:
            cache.SetTime(time)
            bounds = bounds_model.ComputeExtentsHint(cache)
            if any(not Gf.Range3f(bounds[i], bounds[i + 1]).IsEmpty() for i in range(0, len(bounds), 2)):
                hints.SetExtentsHint(bounds, time)
        # A detached Sdf layer avoids trying to resolve this relative payload
        # against the anonymous working stage before the file exists.
        interface_layer = Sdf.Layer.CreateAnonymous("interface.usda")
        interface_layer.TransferContent(interface.GetRootLayer())
        root_spec = interface_layer.GetPrimAtPath(self.root)
        if self.layout == "sections":
            root_spec.referenceList.prependedItems = [Sdf.Reference("./payload/" + name) for name in
                                                      ("bindings.usda", "materials.usda", "structure.usda")]
        else:
            root_spec.payloadList.prependedItems = [Sdf.Payload("./payload/contents.usda")]
        entry = self.folder / (self.name + ".usda")
        if not interface_layer.Export(str(entry), args={"format": "usda"}):
            raise OSError("Could not write the asset interface.")
        manifest = dict(format="lunatic-usd-asset", version=2, name=self.name, source_prim=str(self.selected.GetPath()),
                        placement=self.placement, origin_frame=self.frame.GetValue(),
                        layout=self.layout, sections=sections,
                        snapshot="temporary population-masked stage flatten, selected trees copied with Sdf.CopySpec",
                        composition="current variant selections; composed time samples preserved",
                        prim_paths={str(k): str(v) for k, v in self.paths.items()},
                        resources=[path.removeprefix("../") for path in self.resources.values()])
        (self.folder / "publish.json").write_text(json.dumps(manifest, indent=2) + "\n")
        self.progress("Validating published asset…")
        published = Usd.Stage.Open(str(entry))
        if not published or not published.GetDefaultPrim() or published.GetCompositionErrors():
            raise ValueError("The published asset failed USD composition validation.")
        for prim in published.Traverse():
            for prop in prim.GetAuthoredProperties():
                targets = prop.GetConnections() if isinstance(prop, Usd.Attribute) else prop.GetTargets()
                for target in targets:
                    if not published.GetObjectAtPath(target):
                        raise ValueError(f"Published dependency does not resolve: {prop.GetPath()} -> {target}")
        return dict(entry=entry.name, prim_count=len(self.prims), dependency_count=len(self.resources))


def publish_asset(stage, prim_path, directory, name, *, placement="local", frame=0, progress=None, layout="single"):
    """Create directory/name/name.usda; never overwrite or edit the source stage."""
    destination = publish_destination(directory, name)
    report = progress or (lambda message: None)
    with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
        with tempfile.TemporaryDirectory(prefix=f".{name}-publish-", dir=destination.parent) as temporary:
            publisher = Publisher(stage, prim_path, name, temporary, placement=placement, frame=frame, progress=report, layout=layout)
            publisher.gather()
            publisher.copy()
            result = publisher.write()
            # Exclusively reserve the final name after validation, then replace
            # only our own empty directory with the complete publication.
            destination.mkdir()
            try:
                os.rename(temporary, destination)
            except OSError:
                try:
                    destination.rmdir()
                except OSError:
                    pass
                raise
    return dict(path=str(destination / result.pop("entry")), directory=str(destination), **result)

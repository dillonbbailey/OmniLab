"""Layer inspection for the isolated USD worker."""
from pxr import Ar, Sdf

from .usd_composition import sublayer_entries


def retain_layers(stage, editing):
    from .usd_project import stage_layers
    for identifier, layer in stage_layers(stage).items():
        editing.layer_cache[identifier] = Sdf.Layer.FindOrOpen(identifier)


def layer_entries(stage, editing, sources=None):
    retain_layers(stage, editing)
    active_local = set(stage.GetLayerStack(includeSessionLayers=True))
    contributing = active_local | set(stage.GetUsedLayers())
    # Muted layers disappear from USD's layer stacks. Walk authored sublayer
    # links so they remain visible, including children of muted parents.
    local = []
    def visit(layer):
        if not layer or layer in local:
            return
        local.append(layer)
        for path in layer.subLayerPaths:
            visit(Sdf.Layer.FindRelativeToLayer(layer, path))
    with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
        visit(stage.GetSessionLayer())
        visit(stage.GetRootLayer())
    external = sorted((layer for layer in stage.GetUsedLayers() if layer not in local),
                      key=lambda layer: layer.identifier)
    for identifier in stage.GetMutedLayers():
        layer = editing.layer_cache.get(identifier)
        if layer and layer not in local and layer not in external:
            external.append(layer)
    entries = []
    layers = [*local, *external]
    identifiers = {layer.identifier for layer in layers}
    with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
        for layer in layers:
            role = ("Session" if layer == stage.GetSessionLayer() else
                    "Root" if layer == stage.GetRootLayer() else
                    "Sublayer" if layer in local else "Referenced")
            muted = stage.IsLayerMuted(layer.identifier)
            editable = layer in active_local and layer.permissionToEdit
            reason = ("Muted; this layer does not contribute to composition." if muted else
                      "Not contributing while an ancestor layer is muted." if layer in local and layer not in active_local else
                      "" if editable else "Layer does not permit editing." if layer in local else
                      "Referenced layers are inspectable; choose a local layer to author overrides.")
            sublayers = sublayer_entries(layer)
            children = []
            for sublayer in sublayers:
                # Resolve relative paths against their owning layer. Inspection
                # uses only already-open layers and never loads new scene data.
                child = Sdf.Layer.FindRelativeToLayer(layer, sublayer["path"])
                identifier = child.identifier if child and child.identifier in identifiers else None
                children.append(dict(sublayer, identifier=identifier))
            source = (sources or {}).get(layer.identifier) or layer.realPath
            name = (Sdf.Layer.GetDisplayNameFromIdentifier(source) if source else
                    ("anon:" if layer.anonymous else "") + layer.GetDisplayName())
            entries.append(dict(identifier=layer.identifier, name=name, role=role,
                                anonymous=layer.anonymous, real_path=layer.realPath,
                                editable=editable, reason=reason, active=layer == editing.layer,
                                muted=muted, contributing=layer in contributing, can_mute=layer != stage.GetRootLayer(),
                                can_save=layer in local and layer.permissionToEdit and (layer.anonymous or layer.permissionToSave)
                                and (not source or source.lower().endswith((".usd", ".usda", ".usdc"))),
                                source=source,
                                modified=editing.modified(layer), sublayers=sublayers, children=children))
    return entries


def layer_text(stage, identifier, editing=None):
    # Restrict requests to layers participating in this stage, including session.
    layer = next((layer for layer in [*stage.GetLayerStack(), *stage.GetUsedLayers()]
                  if layer.identifier == identifier), None)
    if layer is None and editing is not None:
        layer = editing.layer_cache.get(identifier)
    if layer is None:
        raise ValueError("This layer is no longer part of the open stage.")
    return layer.ExportToString()

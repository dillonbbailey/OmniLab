"""Composed variant choices and undoable authoring in the native USD worker."""
from pxr import Sdf


def valid_selection(set_name, variant_name):
    if not isinstance(set_name, str) or not isinstance(variant_name, str):
        return False
    text = "/Asset{" + set_name + "=" + variant_name + "}"
    return bool(Sdf.Path.IsValidPathString(text)) and Sdf.Path(text).GetVariantSelection() == (set_name, variant_name)


def variant_choices(prim):
    if not prim or prim.IsPseudoRoot():
        return []
    sets = prim.GetVariantSets()
    return [dict(name=name, selection=sets.GetVariantSet(name).GetVariantSelection(),
                 variants=sets.GetVariantSet(name).GetVariantNames()) for name in sets.GetNames()]


def edit_variant(edits, path, operation, set_name, variant_name=""):
    from .usd_editing import editable_prim
    prim = edits.stage.GetPrimAtPath(path)
    if not editable_prim(prim) or prim.IsPseudoRoot():
        raise ValueError("Choose an editable prim outside instance contents.")
    if operation not in ("create", "add", "select"):
        raise ValueError("Choose create set, add variant, or select variant.")
    if not isinstance(set_name, str) or not Sdf.Path.IsValidIdentifier(set_name):
        raise ValueError("Enter a valid variant set name, such as geometry or look.")
    sets = prim.GetVariantSets()
    exists = set_name in sets.GetNames()
    if operation == "create" and exists:
        raise ValueError("This variant set already exists.")
    if operation != "create" and not exists:
        raise ValueError("This variant set no longer exists. Reopen the Variants menu.")
    variant_set = sets.GetVariantSet(set_name)
    if operation != "create":
        if not isinstance(variant_name, str) or not variant_name.strip():
            raise ValueError("Enter a nonempty variant name.")
        if not valid_selection(set_name, variant_name):
            raise ValueError("Enter a valid USD variant name, such as warm-red or high_res.")
        names = variant_set.GetVariantNames()
        if operation == "add" and variant_name in names:
            raise ValueError("This variant already exists.")
        if operation == "select" and variant_name not in names:
            raise ValueError("This variant no longer exists. Reopen the Variants menu.")
        if operation == "select" and variant_set.GetVariantSelection() == variant_name:
            return path

    def author():
        if operation == "create":
            if not sets.AddVariantSet(set_name):
                raise ValueError("USD could not create the variant set.")
            if set_name not in sets.GetNames():
                raise ValueError("The variant set is overridden. Choose a stronger edit target, such as the session layer.")
        else:
            if operation == "add" and not variant_set.AddVariant(variant_name):
                raise ValueError("USD could not add the variant.")
            if not variant_set.SetVariantSelection(variant_name):
                raise ValueError("USD could not select the variant.")
            if variant_set.GetVariantSelection() != variant_name:
                raise ValueError("The variant selection is overridden. Choose a stronger edit target, such as the session layer.")
        return path

    label = {"create": "Create variant set", "add": "Add variant", "select": "Select variant"}[operation]
    return edits.change(f"{label} {path} {set_name}" + (" = " + variant_name if variant_name else ""), author)

"""Honor legacy camera locks without loading MoonRay graph code."""

def is_locked(prim):
    data = prim.GetCustomDataByKey("moonrayEditor:previewCamera") if prim else None
    return bool(isinstance(data, dict) and data.get("locked"))

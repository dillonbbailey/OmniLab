"""First-run dock layout; user layout persists thereafter."""

from pathlib import Path
import omni.ui as ui


def initialize_layout(reset=False):
    path = Path("imgui.ini")
    if path.exists() and not reset:
        return
    scale = ui.Workspace.get_dpi_scale()
    sizes = {
        name: round(n * scale)
        for name, n in dict(
            w=1440, h=900, left=290, right=355, top=110, lower=270
        ).items()
    }
    w, h, left, right, top, lower = [
        sizes[k] for k in ("w", "h", "left", "right", "top", "lower")
    ]
    mid = w - left - right
    nodes = [
        ("OmniLab", 1, 0, 0, w, top),
        ("Stage Browser", 5, 0, top, left, h - top - lower),
        ("Layers", 6, 0, h - lower, left, lower),
        ("Viewport", 7, left, top, mid, h - top),
        ("Property Inspector", 8, w - right, top, right, h - top),
    ]
    parts = []
    for title, node, x, y, width, height in nodes:
        parts.append(
            f"[Window][{title}]\nPos={x},{y}\nSize={width},{height}\nCollapsed=0\nDockId=0x{node:08X},0\n"
        )
    parts.append(f"""[Docking][Data]
DockSpace ID=0x0FCAA000 Window=0x3DA2F1DE Pos=0,0 Size={w},{h} Split=Y
  DockNode ID=0x00000001 Parent=0x0FCAA000 SizeRef={w},{top}
  DockNode ID=0x00000002 Parent=0x0FCAA000 SizeRef={w},{h - top} Split=X
    DockNode ID=0x00000003 Parent=0x00000002 SizeRef={left},{h - top} Split=Y
      DockNode ID=0x00000005 Parent=0x00000003 SizeRef={left},{h - top - lower}
      DockNode ID=0x00000006 Parent=0x00000003 SizeRef={left},{lower}
    DockNode ID=0x00000004 Parent=0x00000002 SizeRef={w - left},{h - top} Split=X
      DockNode ID=0x00000007 Parent=0x00000004 SizeRef={mid},{h - top} CentralNode=1
      DockNode ID=0x00000008 Parent=0x00000004 SizeRef={right},{h - top}
""")
    path.write_text("\n".join(parts))

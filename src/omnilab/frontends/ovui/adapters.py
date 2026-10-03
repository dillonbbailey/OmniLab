"""Stock ovUI read models with all authoring routed into OmniLab history.

The NVIDIA adapters supply inspection, change notices, filters and badges.
Their independent mutation/undo implementation is deliberately not installed.
"""

from ovui_data_adapters.common import ReparentPosition
from ovui_data_adapters.openusd import UsdStageAdapter, UsdPropertyAdapter
from pxr import Usd
from omnilab.usd.usd_editing import encode_value, property_info


class DocumentStageAdapter(UsdStageAdapter):
    def __init__(self, document, changed=lambda: None, call_later=None):
        super().__init__(document.stage, call_later=call_later)
        self.document, self.changed = document, changed
        self.group = None

    def command(self, name, *args, **kwargs):
        if self.group is not None:
            self.group.append(dict(name=name, data=args[0]))
            return
        result = self.document.command(name, *args, **kwargs)
        self.changed()
        return result

    def _push(self, command):
        raise RuntimeError("This action must use an OmniLab document command.")

    def set_visibility(self, item, visible):
        self.command(
            "set_property",
            dict(
                path=str(item.GetPath()),
                group="Attributes",
                name="visibility",
                value="inherited" if visible else "invisible",
            ),
        )

    def rename(self, item, new_name):
        path = item.GetPath()
        self.command(
            "reparent_prim",
            dict(
                path=str(path),
                parent=str(path.GetParentPath()),
                name=new_name,
                mode="namespace",
            ),
        )
        return new_name

    def reparent(self, items, new_parent, position):
        if position != ReparentPosition.CHILD:
            raise ValueError(
                "Drop onto a parent to move prims; sibling ordering is not implemented."
            )
        # NamespaceEditor preserves relationships and contributing layers.
        operations = [
            dict(
                name="reparent_prim",
                data=dict(
                    path=str(item.GetPath()),
                    parent=str(new_parent.GetPath()),
                    mode="namespace",
                ),
            )
            for item in items
        ]
        if self.group is not None:
            self.group.extend(operations)
        else:
            self.command("edit_prims", operations, label="Reparent selected prims")

    def begin_undo_group(self, label):
        if self.group is not None:
            raise ValueError("An edit group is already active.")
        self.group, self.group_label = [], label

    def end_undo_group(self):
        operations, self.group = self.group, None
        if operations:
            self.command("edit_prims", operations, label=self.group_label)

    def abort_undo_group(self):
        self.group = None  # Buffered edits have not touched the document.


class DocumentPropertyAdapter(UsdPropertyAdapter):
    """Stage writes happen only on end-edit; a cancelled drag authors nothing."""

    def __init__(self, document, paths, changed=lambda: None):
        super().__init__(document.stage, paths)
        self.document, self.changed = document, changed
        self.pending = {}
        self.targets = {}
        self.initial = {}

    def begin_edit(self, name):
        if name in self.pending:
            raise ValueError("An edit is already active for " + name)
        self.initial[name] = encode_value(self.get_value(name))
        self.pending[name] = self.get_value(name)
        self.targets[name] = self.document.stage.GetEditTarget()

    def set_value(self, name, value):
        if name not in self.pending:
            self.begin_edit(name)
        self.pending[name] = value

    def end_edit(self, name):
        if name not in self.pending:
            return
        value = self.pending.pop(name)
        target = self.targets.pop(name)
        initial = self.initial.pop(name)
        if target != self.document.stage.GetEditTarget():
            raise ValueError(
                "Edit target changed during the edit; value was not committed."
            )
        if encode_value(value) == initial:
            return
        self.document.command(
            "set_properties",
            [
                dict(
                    path=path, group="Attributes", name=name, value=encode_value(value)
                )
                for path in self._paths
            ],
        )
        self._refresh()
        self.changed()

    def cancel_edit(self, name):
        self.pending.pop(name, None)
        self.targets.pop(name, None)
        self.initial.pop(name, None)

    def clear_value(self, name):
        def author():
            for path in self._paths:
                prim = self.document.stage.GetPrimAtPath(path)
                property_info(
                    prim, "Attributes", name, Usd.TimeCode.Default(), use_default=True
                )
                if not prim.GetAttribute(name).Clear():
                    raise ValueError("USD could not clear " + path + "." + name)

        self.document.edits.change("Clear " + name, author)
        self.document.revision += 1
        self.changed()

"""Searchable typed RTX overrides, preserving declaration/effect distinction."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QTreeWidget,
    QTreeWidgetItem, QLabel, QPushButton, QFileDialog)

from omnilab.core.document import atomic_json
from omnilab.render.settings import definitions, validate, export_settings, CONTROLLED


class SettingsEditor(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('ovRTX settings — OmniLab')
        self.resize(1280, 760)
        layout = QVBoxLayout(self)
        hint = QLabel('Overrides are saved in the OmniLab project. Schema defaults are declarations; effective runtime values remain unknown. Renderer creation changes restart active workers. Double-click to author a typed value.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItems(['Viewport', 'Material preview', 'Final render', 'Renderer creation'])
        row.addWidget(self.scope)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search names, descriptions, groups')
        row.addWidget(self.search, 1)
        for text, callback in [('Reset override', self.reset), ('Export all settings…', self.export)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, callback=callback: owner.safe(callback))
            row.addWidget(button)
        layout.addLayout(row)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Setting', 'Type', 'Schema / API default', 'Authored override', 'Group / evidence'])
        self.table.itemDoubleClicked.connect(lambda item, column: owner.safe(lambda: self.edit(item)))
        layout.addWidget(self.table)
        self.search.textChanged.connect(self.populate)
        self.scope.currentIndexChanged.connect(self.populate)
        self.populate()

    def values(self):
        if self.scope.currentIndex() == 3:
            return self.owner.document.view.setdefault('renderer_config', {})
        profile = ('viewport', 'material', 'final')[self.scope.currentIndex()]
        return self.owner.document.view.setdefault('rtx_settings', {}).setdefault(profile, {})

    def populate(self, *_):
        self.table.clear()
        values = self.values()
        words = self.search.text().lower().split()
        for name, definition in definitions(self.scope.currentIndex() == 3).items():
            if not all(word in (name+' '+definition['description']+' '+definition['group']).lower() for word in words):
                continue
            value = 'controlled in render controls' if name in CONTROLLED else json.dumps(values[name]) if name in values else '—'
            item = QTreeWidgetItem([name, definition['type'], json.dumps(definition['default']), value, definition['group']])
            item.setData(0, Qt.UserRole, name)
            for column in range(5):
                item.setToolTip(column, definition['description'] + '\n' + definition['status'])
            self.table.addTopLevelItem(item)
        for name in values.keys() - definitions(self.scope.currentIndex() == 3).keys():
            if all(word in name.lower() for word in words):
                item = QTreeWidgetItem([name, 'unknown', 'unknown', json.dumps(values[name]), 'Imported; unsupported by this catalog'])
                item.setData(0, Qt.UserRole, name)
                self.table.addTopLevelItem(item)
        self.table.setColumnWidth(0, 460)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 200)

    def edit(self, item):
        from .window import json_dialog
        name = item.data(0, Qt.UserRole)
        definition = definitions(self.scope.currentIndex() == 3).get(name)
        if definition is None:
            raise ValueError('This imported entry is preserved. Reset it to remove it; its type is unknown to this catalog.')
        # Wrap the value so JSON null is distinguishable from Cancel.
        result = json_dialog(self, name, {'value': self.values().get(name, definition['default'])})
        if result is not None:
            self.values()[name] = validate(name, result['value'], self.scope.currentIndex() == 3)
            self.changed()

    def reset(self):
        item = self.table.currentItem()
        if item:
            self.values().pop(item.data(0, Qt.UserRole), None)
            self.changed()

    def changed(self):
        self.populate()
        if self.scope.currentIndex() == 3 and self.owner.render_enabled:
            self.owner.restart_renderer()
        else:
            self.owner.schedule_view()
        editor = getattr(self.owner, 'material_editor', None)
        if editor and editor.preview.enabled:
            if self.scope.currentIndex() == 3:
                editor.preview.stop()
                editor.preview.start()
            else:
                editor.preview.schedule()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export declared and authored settings', 'ovrtx-settings.json', 'JSON (*.json)')
        if path:
            atomic_json(path, export_settings(self.owner.document))

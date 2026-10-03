"""Searchable typed RTX overrides, preserving declaration/effect distinction."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QTreeWidget,
    QTreeWidgetItem, QLabel, QPushButton, QFileDialog, QMenu)

from omnilab.core.document import atomic_json
from omnilab.render.settings import definitions, validate, export_settings, CONTROLLED
from .numeric_editor import numeric_editor
from .value_menu import copy_value


class SettingsEditor(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.generation = 0
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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.value_menu)
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
        self.generation += 1
        self.table.setColumnHidden(1, not self.owner.application_settings.show_property_types())
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
            if definition['type'] == 'color3f' and name not in CONTROLLED:
                editor = numeric_editor(definition['type'], values.get(name, definition['default']),
                                        self.owner.application_settings)
                if editor is not None:
                    origin = 'Authored override.' if name in values else 'No override; showing the schema default. Edit to author.'
                    editor.setToolTip(origin + '\nRGB values; the last square opens the color picker.')
                    generation, document = self.generation, self.owner.document
                    editor.committed.connect(lambda value, n=name, g=generation, d=document:
                        self.owner.safe(lambda: self.set_color(n, value, g, d)), Qt.QueuedConnection)
                    self.table.setItemWidget(item, 3, editor)
        for name in values.keys() - definitions(self.scope.currentIndex() == 3).keys():
            if all(word in name.lower() for word in words):
                item = QTreeWidgetItem([name, 'unknown', 'unknown', json.dumps(values[name]), 'Imported; unsupported by this catalog'])
                item.setData(0, Qt.UserRole, name)
                self.table.addTopLevelItem(item)
        self.table.setColumnWidth(0, 460)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 265)

    def set_color(self, name, value, generation, document):
        if generation != self.generation or document is not self.owner.document:
            return
        self.values()[name] = validate(name, value, self.scope.currentIndex() == 3)
        self.changed()

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

    def value_menu(self, position):
        item = self.table.itemAt(position)
        column = self.table.columnAt(position.x())
        if item is None or column not in (2, 3):
            return
        name = item.data(0, Qt.UserRole)
        definition = definitions(self.scope.currentIndex() == 3).get(name, {})
        value = definition.get('default') if column == 2 else self.values().get(name, definition.get('default'))
        menu = QMenu(self)
        menu.addAction('Copy values', lambda: copy_value(value))
        menu.exec(self.table.viewport().mapToGlobal(position))

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

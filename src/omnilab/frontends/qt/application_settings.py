"""User preferences shared by the Qt property editors, outside scene documents."""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel, QSpinBox,
                               QDialogButtonBox, QCheckBox)


class ApplicationSettings:
    DEFAULTS = {'float': 6, 'double': 12}

    def __init__(self, storage=None):
        self.storage = storage if storage is not None else QSettings('OmniLab', 'OmniLab')

    def decimals(self, kind):
        try:
            value = int(self.storage.value('propertyEditors/' + kind + 'Decimals', self.DEFAULTS[kind]))
            return max(0, min(323, value))  # QDoubleSpinBox's supported range.
        except (TypeError, ValueError):
            return self.DEFAULTS[kind]

    def save_precision(self, floats, doubles):
        for kind, value in (('float', floats), ('double', doubles)):
            self.storage.setValue('propertyEditors/' + kind + 'Decimals', max(0, min(323, int(value))))
        self.storage.sync()

    def timeline_visible(self):
        return self.storage.value('workspace/showTimeline', True, type=bool)

    def set_timeline_visible(self, visible):
        self.storage.setValue('workspace/showTimeline', visible)
        self.storage.sync()

    def show_property_types(self):
        return self.storage.value('propertyEditors/showTypes', True, type=bool)

    def set_show_property_types(self, visible):
        self.storage.setValue('propertyEditors/showTypes', visible)
        self.storage.sync()


class ApplicationSettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('Application Settings — OmniLab')
        self.resize(410, 220)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Property editor precision'))
        form = QFormLayout()
        self.precision = {}
        for kind in settings.DEFAULTS:
            spin = QSpinBox()
            spin.setRange(0, 323)
            spin.setSuffix(' decimal places')
            spin.setValue(settings.decimals(kind))
            form.addRow(kind.title(), spin)
            self.precision[kind] = spin
        layout.addLayout(form)
        self.show_types = QCheckBox('Show property types')
        self.show_types.setChecked(settings.show_property_types())
        self.show_types.setToolTip('Show the Type column in Properties, Material Editor and ovRTX settings.')
        layout.addWidget(self.show_types)
        note = QLabel('Applies to Properties and the Material Editor. Changing precision does not change stored scene values.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)

    def restore_defaults(self):
        for kind, value in self.settings.DEFAULTS.items():
            self.precision[kind].setValue(value)
        self.show_types.setChecked(True)

    def accept(self):
        self.settings.save_precision(self.precision['float'].value(), self.precision['double'].value())
        self.settings.set_show_property_types(self.show_types.isChecked())
        super().accept()

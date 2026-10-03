"""Inline scalar editors that commit once when the user finishes an edit."""
import math
import re
import sys

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDoubleSpinBox, QSizePolicy, QWidget, QHBoxLayout, QPushButton, QColorDialog
from shiboken6 import isValid
from .value_menu import install_editor_menu


class NumericEditor(QDoubleSpinBox):
    committed = Signal(float)

    def __init__(self, value, decimals, parent=None):
        super().__init__(parent)
        self.setDecimals(decimals)
        self.setRange(-sys.float_info.max, sys.float_info.max)
        self.setSingleStep(10 ** -min(decimals, 2))
        self.setKeyboardTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setValue(value)
        # Compare the displayed, rounded value: merely focusing a field must
        # never author its rounded representation back into USD.
        self.original = self.value()
        self.editingFinished.connect(self.finish)
        install_editor_menu(self, self.value)

    def sizeHint(self):
        return QSize(130, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(65, super().minimumSizeHint().height())

    def finish(self):
        value = self.value()
        if value != self.original:
            self.original = value
            self.committed.emit(value)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.setValue(self.original)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class VectorEditor(QWidget):
    committed = Signal(object)

    def __init__(self, values, decimals, color=False, parent=None):
        super().__init__(parent)
        self.values = list(values)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.fields = []
        for index, value in enumerate(values):
            field = NumericEditor(value, decimals, self)
            field.setAccessibleName(('RGBA' if color else 'XYZW')[index])
            field.committed.connect(lambda value, index=index: self.commit_component(index, value))
            layout.addWidget(field, 1)
            self.fields.append(field)
        self.swatch = None
        if color:
            self.swatch = QPushButton()
            self.swatch.setFixedSize(22, 22)
            self.swatch.setFocusPolicy(Qt.NoFocus)
            self.swatch.setToolTip('Choose color; numeric fields retain HDR values.')
            self.swatch.setAccessibleName('Choose color')
            self.swatch.clicked.connect(self.choose_color)
            layout.addWidget(self.swatch)
            self.update_swatch()
        install_editor_menu(self, lambda: list(self.values))

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def commit_component(self, index, value):
        self.values[index] = value
        if self.swatch:
            self.update_swatch()
        self.committed.emit(list(self.values))

    def color(self):
        return QColor.fromRgbF(*[max(0., min(1., value)) for value in self.values])

    def update_swatch(self):
        color = self.color()
        self.swatch.setStyleSheet(f'background-color: {color.name()}; border: 1px solid #777;')

    def choose_color(self):
        initial = self.color()
        # Opening a dialog must not commit/rebuild this cell halfway through
        # handling its button click. The picker replaces the entire color.
        for field in self.fields:
            field.blockSignals(True)
        options = QColorDialog.ShowAlphaChannel if len(self.values) == 4 else QColorDialog.ColorDialogOption(0)
        color = QColorDialog.getColor(initial, self.window(), 'Choose color', options)
        if not isValid(self):
            return  # A playback refresh may have removed this inspector cell.
        for field in self.fields:
            field.blockSignals(False)
        if color.isValid() and color != initial:
            self.values = list(color.getRgbF()[:len(self.values)])
            for field, value in zip(self.fields, self.values):
                field.setValue(value)
                field.original = field.value()
            self.update_swatch()
            self.committed.emit(list(self.values))


def numeric_editor(kind, value, settings, parent=None):
    if isinstance(value, bool):
        return None
    if kind in ('float', 'double'):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return NumericEditor(value, settings.decimals(kind), parent) if math.isfinite(value) else None
    match = re.fullmatch(r'(float|double|color|vector|normal|point|texCoord)([234])([fd]?)', kind)
    if not match:
        return None
    family, count, precision = match.groups()
    if family == 'color' and value is None:
        value = [0.] * int(count)
    try:
        values = list(value)
        if len(values) != int(count) or any(isinstance(v, bool) or not math.isfinite(float(v)) for v in values):
            return None
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    scalar = 'double' if family == 'double' or precision == 'd' else 'float'
    return VectorEditor(values, settings.decimals(scalar), family == 'color' and int(count) in (3, 4), parent)

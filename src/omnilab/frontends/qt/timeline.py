"""A bounded slider mapping USD's fractional frame range to timeline positions."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class Timeline(QSlider):
    timeChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.first = self.last = 0.
        self.frame = 0.
        self.decimals = 2
        self.setMinimumWidth(80)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setTickPosition(QSlider.TicksBelow)
        self.valueChanged.connect(self.scrub)
        self.setAccessibleName('Timeline')

    def set_range(self, first, last, frame, decimals=2):
        self.first, self.last, self.decimals = first, last, decimals
        span = max(0., last-first)
        with QSignalBlocker(self):
            steps = min(1_000_000, max(1, round(span * 10 ** decimals)))
            self.setRange(0, steps)
            self.setSingleStep(max(1, round(steps/span)) if span else 1)
            self.setPageStep(min(steps, 10*self.singleStep()))
            self.setTickInterval(max(1, steps//10))
            self.setEnabled(span > 0)
            self.set_time(frame)

    def set_time(self, frame):
        self.frame = frame
        with QSignalBlocker(self):
            span = self.last-self.first
            self.setValue(round((frame-self.first)/span*self.maximum()) if span > 0 else 0)
        self.setToolTip(f'Frame {frame:g} · Range {self.first:g} – {self.last:g}\nDrag to scrub; arrow keys step one frame.')

    def scrub(self, value):
        frame = self.first + value/self.maximum()*(self.last-self.first)
        self.timeChanged.emit(round(frame, self.decimals))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            step = 1 if event.key() == Qt.Key_Right else -1
            self.timeChanged.emit(max(self.first, min(self.last, self.frame+step)))
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
            position = round(event.position().x() - handle.width()/2)
            self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position,
                          max(1, self.width()-handle.width()), option.upsideDown))
        super().mousePressEvent(event)

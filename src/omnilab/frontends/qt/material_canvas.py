"""Qt node canvas; graph mutations stay in the shared material model."""
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QKeySequence
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsSimpleTextItem, QGraphicsItem, QMenu)


def curve(a, b):
    result = QPainterPath(a)
    distance = max(60, abs(b.x() - a.x()) / 2)
    result.cubicTo(a + QPointF(distance, 0), b - QPointF(distance, 0), b)
    return result


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node, name, output, y, parent):
        super().__init__(-6, -6, 12, 12, parent)
        self.node, self.name, self.output = node, name, output
        self.setPos(260 if output else 0, y)
        self.setBrush(QColor('#f2bc78' if output else '#79cbd2'))
        self.setToolTip(('Output ' if output else 'Input ') + name + '\nDrag to connect; right-click for actions.')


class NodeItem(QGraphicsRectItem):
    def __init__(self, node, canvas):
        names = list(node['inputs'])
        if not canvas.all_ports:
            important = {'base_color', 'base_metalness', 'specular_roughness', 'transmission_weight',
                         'coat_weight', 'emission_color', 'geometry_normal', 'file', 'texcoord', 'in', 'value'}
            names = [name for name in names if name in important or node['inputs'][name]['connection']] or names[:6]
        super().__init__(0, 0, 260, 70 + 23 * max(len(names), len(node['outputs']), 1))
        self.node, self.canvas, self.ports = node, canvas, {}
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QColor('#30383e'))
        self.setPen(QPen(QColor('#e5b97d' if node['known'] else '#e07171'), 2))
        self.setPos(*node['position'])
        def text(value, x, y, color):
            label = QGraphicsSimpleTextItem(value, self)
            label.setBrush(QColor(color))
            label.setPos(x, y)
            return label
        text(node['name'], 12, 8, '#ffffff')
        text(node['identifier'][:34], 12, 30, '#b7c6cf')
        for output, ports in ((False, names), (True, list(node['outputs']))):
            for index, name in enumerate(ports):
                y = 64 + index * 23
                port = PortItem(node['path'], name, output, y, self)
                self.ports[(name, output)] = port
                label = text(name, 12, y - 9, '#dce5e9')
                if output:
                    label.setPos(248 - label.boundingRect().width(), y - 9)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.canvas.update_edges()
        return result


class GraphCanvas(QGraphicsView):
    connected = Signal(str, str, str, str)
    disconnected = Signal(str, str)
    terminalRequested = Signal(str, str)
    positionsChanged = Signal(dict)
    selectionChanged = Signal(str)
    commandRequested = Signal(str)
    renamed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor('#20262b'))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.nodes, self.edges, self.data = {}, [], []
        self.all_ports = False
        self.connection_start = self.connection_line = None
        self.scene().selectionChanged.connect(self.selected)

    def load(self, data, selected=()):
        self.nodes, self.edges, self.data = {}, [], data
        self.scene().clear()
        for node in data:
            item = NodeItem(node, self)
            self.nodes[node['path']] = item
            self.scene().addItem(item)
            item.setSelected(node['path'] in selected)
        for node in data:
            for name, input_ in node['inputs'].items():
                connection = input_['connection']
                if not connection or '.outputs:' not in connection:
                    continue
                source, output = connection.rsplit('.outputs:', 1)
                src = self.nodes.get(source)
                dst = self.nodes[node['path']]
                a = src.ports.get((output, True)) if src else None
                b = dst.ports.get((name, False))
                if a and b:
                    line = self.scene().addPath(curve(a.scenePos(), b.scenePos()), QPen(QColor('#85cad5'), 2))
                    line.setZValue(-1)
                    self.edges.append((line, a, b))
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-500, -500, 500, 500))

    def update_edges(self):
        for line, a, b in self.edges:
            line.setPath(curve(a.scenePos(), b.scenePos()))

    def frame_nodes(self):
        bounds = self.scene().itemsBoundingRect().adjusted(-24, -24, 24, 24)
        self.fitInView(bounds, Qt.KeepAspectRatio)
        scale = self.transform().m11()
        if scale > 1:
            self.scale(1/scale, 1/scale)
        self.centerOn(bounds.center())

    def selected_paths(self):
        return [item.node['path'] for item in self.scene().selectedItems() if isinstance(item, NodeItem)]

    def selected(self):
        paths = self.selected_paths()
        self.selectionChanged.emit(paths[0] if paths else '')

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if .15 < self.transform().m11() * factor < 3:
            self.scale(factor, factor)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, PortItem) and event.button() == Qt.LeftButton:
            self.connection_start = item
            self.connection_line = self.scene().addPath(QPainterPath(), QPen(QColor('#f6c982'), 2))
            return
        if event.button() == Qt.MiddleButton:
            self.pan_position = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.connection_start:
            start, end = self.connection_start.scenePos(), self.mapToScene(event.position().toPoint())
            self.connection_line.setPath(curve(start, end) if self.connection_start.output else curve(end, start))
            return
        if event.buttons() & Qt.MiddleButton and hasattr(self, 'pan_position'):
            delta = event.position() - self.pan_position
            self.pan_position = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.connection_start:
            start, self.connection_start = self.connection_start, None
            self.scene().removeItem(self.connection_line)
            self.connection_line = None
            end = self.itemAt(event.position().toPoint())
            if isinstance(end, PortItem) and start.output != end.output:
                src, dst = (start, end) if start.output else (end, start)
                self.connected.emit(src.node, src.name, dst.node, dst.name)
            return
        super().mouseReleaseEvent(event)
        changed = {path: [item.pos().x(), item.pos().y()] for path, item in self.nodes.items()
                   if [item.pos().x(), item.pos().y()] != item.node['position']}
        if changed:
            self.positionsChanged.emit(changed)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        while item and not isinstance(item, NodeItem):
            item = item.parentItem()
        if item:
            self.renamed.emit(item.node['path'])
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        menu = QMenu(self)
        if isinstance(item, PortItem):
            if item.output:
                menu.addAction('Use as material output', lambda: self.terminalRequested.emit(item.node, item.name))
            else:
                menu.addAction('Disconnect', lambda: self.disconnected.emit(item.node, item.name))
        for title, command in [('Copy', 'copy'), ('Paste', 'paste'), ('Duplicate', 'duplicate'), ('Delete', 'delete'), ('Arrange', 'arrange')]:
            menu.addAction(title, lambda checked=False, command=command: self.commandRequested.emit(command))
        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        for key, command in [(QKeySequence.Copy, 'copy'), (QKeySequence.Paste, 'paste'),
                             (QKeySequence.Undo, 'undo'), (QKeySequence.Redo, 'redo')]:
            if event.matches(key):
                self.commandRequested.emit(command)
                return
        if event.key() == Qt.Key_Delete:
            self.commandRequested.emit('delete')
        elif event.key() == Qt.Key_F:
            self.frame_nodes()
        else:
            super().keyPressEvent(event)

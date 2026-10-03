"""Copy complete typed values, including fields inside a compound editor."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu
from omnilab.usd.property_actions import copy_text


def copy_value(value):
    QApplication.clipboard().setText(copy_text(value))


def install_value_menu(widget, value):
    widget._copy_value = value
    if getattr(widget, "_value_menu_installed", False):
        return
    widget._value_menu_installed = True
    widget.setContextMenuPolicy(Qt.CustomContextMenu)

    def show(position):
        menu = (
            widget.createStandardContextMenu()
            if hasattr(widget, "createStandardContextMenu")
            else QMenu(widget)
        )
        if menu.actions():
            menu.addSeparator()
        menu.addAction("Copy values", lambda: copy_value(widget._copy_value()))
        menu.exec(widget.mapToGlobal(position))

    widget.customContextMenuRequested.connect(show)


def install_editor_menu(editor, value):
    install_value_menu(editor, value)
    for field in getattr(editor, "fields", [editor]):
        install_value_menu(field, value)
        if hasattr(field, "lineEdit"):
            install_value_menu(field.lineEdit(), value)
    if getattr(editor, "swatch", None) is not None:
        install_value_menu(editor.swatch, value)

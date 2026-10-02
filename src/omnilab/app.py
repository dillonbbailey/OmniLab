"""Desktop entry point; imports no renderer into the application process."""


def main():
    import argparse
    import sys
    from PySide6.QtWidgets import QApplication
    from omnilab.frontends.qt.window import MainWindow

    parser = argparse.ArgumentParser(description="OmniLab USD editor")
    parser.add_argument("scene", nargs="?")
    parser.add_argument("--no-render", action="store_true", help="Open the editor without starting ovRTX")
    parser.add_argument("--demo", action="store_true", help="Create an editable example scene")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("OmniLab")
    app.setApplicationName("OmniLab")
    app.setStyle("Fusion")
    window = MainWindow(render_enabled=not args.no_render)
    window.show()
    if args.scene:
        window.safe(lambda: window.open_path(args.scene))
    elif args.demo:
        window.new_demo()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

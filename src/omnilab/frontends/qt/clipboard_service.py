"""Own the system clipboard for ovUI without loading Qt into its process."""

import json
import sys
from PySide6.QtCore import QSocketNotifier
from PySide6.QtGui import QGuiApplication


def main():
    app = QGuiApplication([])

    def receive(*_):
        line = sys.stdin.readline()
        if not line:
            app.quit()
            return
        app.clipboard().setText(json.loads(line))
        print("ok", flush=True)

    notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Read)
    notifier.activated.connect(receive)
    app.exec()


if __name__ == "__main__":
    main()

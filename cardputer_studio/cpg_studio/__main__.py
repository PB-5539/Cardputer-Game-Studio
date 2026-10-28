"""Entry point: python -m cpg_studio [project.cpg]"""
import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 isn't installed. Run `python launch.py` from the project folder; it sets up "
              "everything for you (or: pip install -r requirements.txt).", file=sys.stderr)
        return 1
    from . import APP_NAME
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("CardputerStudio")
    apply_theme(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".cpg"):
        window.open_project(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

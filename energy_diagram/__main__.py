"""Run the diagram window without MoleditPy: ``python -m energy_diagram [file.pmeedg]``."""

import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from PySide6.QtWidgets import QApplication

    import energy_diagram

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = energy_diagram.open_window()
    if argv:
        window.open_path(argv[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

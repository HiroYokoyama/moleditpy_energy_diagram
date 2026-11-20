import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MOLEDITPY_HEADLESS", "1")
os.environ.setdefault("MPLBACKEND", "Agg")
# MoleditPy runs on PySide6; keep pytest-qt and matplotlib off any other binding.
os.environ["QT_API"] = "pyside6"
os.environ["PYTEST_QT_API"] = "pyside6"


@pytest.fixture(scope="session")
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_plugin(tmp_path, monkeypatch):
    """A fresh session and settings file per test; never the real plugin folder."""
    import energy_diagram

    monkeypatch.setattr(energy_diagram, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(energy_diagram, "_session", None)
    monkeypatch.setattr(energy_diagram, "_window", None)
    monkeypatch.setattr(energy_diagram, "_context", None)
    yield
    window = energy_diagram._window
    if window is not None:
        window.close()

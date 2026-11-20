"""Metadata, the import footprint, and the session file; no Qt needed."""

import json
import subprocess
import sys
from pathlib import Path

import energy_diagram
from energy_diagram import model
from energy_diagram.session import Session


def test_metadata_the_registry_reads():
    assert energy_diagram.PLUGIN_NAME == "Reaction Energy Diagram"
    assert energy_diagram.PLUGIN_VERSION == "0.0.1"
    assert energy_diagram.PLUGIN_DEPENDENCIES == ["matplotlib"]
    assert energy_diagram.PLUGIN_SUPPORTED_MOLEDITPY_VERSION.startswith(">=5")
    assert not hasattr(energy_diagram, "run")


def test_importing_the_package_pulls_in_no_heavy_modules():
    root = Path(energy_diagram.__file__).resolve().parents[1]
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import energy_diagram;"
        "bad=[m for m in ('PySide6','rdkit','numpy','matplotlib') if m in sys.modules]; assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code, str(root)], check=True, timeout=60)


def test_session_save_open_and_autosave(tmp_path):
    settings = tmp_path / "settings.json"
    session = Session(str(settings))
    session.diagram.pathways[0].levels.append(model.Level("A", "1"))
    session.changed()
    assert json.loads(settings.read_text(encoding="utf-8"))["autosave"]["dirty"] is True
    session.save(str(tmp_path / "x"))
    assert session.path.endswith("x.pmeedg") and not session.dirty
    restored = Session(str(settings))
    assert restored.path == session.path
    assert restored.diagram.pathways[0].levels[0].label == "A"
    assert restored.last_dir == str(tmp_path)


def test_session_survives_a_broken_settings_file(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{broken", encoding="utf-8")
    session = Session(str(settings))
    assert session.diagram.is_empty()
    settings.write_text(json.dumps({"autosave": {"diagram": {"format": "x"}}}), encoding="utf-8")
    assert Session(str(settings)).diagram.is_empty()


def test_listeners_hear_changes(tmp_path):
    session = Session("")
    heard = []
    session.listeners.append(lambda: heard.append(session.dirty))
    session.changed()
    session.new()
    assert heard == [True, False]

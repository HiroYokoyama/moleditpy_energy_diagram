"""Reaction Energy Diagram: publication-quality energy profiles in their own window.

Energies are typed in, or read from ORCA / Gaussian / GAMESS output files, and
drawn as an energy-level diagram whose labels can be dragged into place,
hidden, and exported as PNG, TIFF, SVG, PDF or EPS. Diagrams are saved as
``.pmeedg`` files, and optionally inside the MoleditPy project.

The diagram is not part of the molecule document: File > New and opening
other files leave it alone, because the energies are collected by visiting
one calculation after another.
"""

import logging
import os

PLUGIN_NAME = "Reaction Energy Diagram"
PLUGIN_VERSION = "0.0.1"
PLUGIN_AUTHOR = "HiroYokoyama"
PLUGIN_DESCRIPTION = (
    "Draw publication-quality reaction energy diagrams in a separate window: energies typed "
    "in or read from ORCA/Gaussian/GAMESS outputs, draggable and hideable labels, several "
    "pathways, barrier arrows and structures; saved as .pmeedg or in the project."
)
PLUGIN_CATEGORY = "Visualization"
PLUGIN_TAGS = ["Visualization", "Analysis"]
PLUGIN_DEPENDENCIES = ["matplotlib"]
PLUGIN_OPTIONAL_DEPENDENCIES = []
PLUGIN_SUPPORTED_MOLEDITPY_VERSION = ">=5.0.0, <6.0.0"

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
WINDOW_ID = "energy_diagram_window"
FILE_EXTENSION = ".pmeedg"

logger = logging.getLogger(__name__)

_context = None
_session = None
_window = None


def get_session():
    """The one diagram, created (and restored from its autosave) on first use."""
    global _session
    if _session is None:
        from .session import Session

        _session = Session(SETTINGS_FILE)
    return _session


def open_window():
    """Show the diagram window, creating it if needed.

    Not named ``run``: the host adds a Plugins-menu entry for any module
    exposing ``run()``, which would duplicate the one registered below.
    """
    global _window
    window = _context.get_window(WINDOW_ID) if _context is not None else _window
    if window is not None:
        window.show()
        window.raise_()
        window.activateWindow()
        return window
    from .window import DiagramWindow

    parent = _context.get_main_window() if _context is not None else None
    window = DiagramWindow(get_session(), context=_context, parent=parent)
    # A separate top-level window beside the editor, not a child dialog.
    from PySide6.QtCore import Qt

    window.setWindowFlag(Qt.WindowType.Window, True)
    if _context is not None:
        _context.register_window(WINDOW_ID, window)
    else:
        _window = window
    window.show()
    return window


def open_file(path):
    """File opener for .pmeedg: open it in the diagram window."""
    window = open_window()
    if not window.confirm_discard():
        return True
    window.open_path(path)
    return True


def save_project_state():
    session = get_session()
    if not session.diagram.store_in_project or session.diagram.is_empty():
        return {}
    return {"diagram": session.diagram.to_dict()}


def load_project_state(data):
    """Take a diagram stored in a project, without silently replacing work."""
    if not isinstance(data, dict) or not isinstance(data.get("diagram"), dict):
        return
    from .model import Diagram

    try:
        incoming = Diagram.from_dict(data["diagram"])
    except ValueError as exc:
        logger.warning("%s: the project's diagram was not loaded: %s", PLUGIN_NAME, exc)
        return
    session = get_session()
    current = session.diagram
    if not current.is_empty() and current.to_dict() != incoming.to_dict() and not _ask_replace():
        return
    session.replace(incoming, path="", dirty=False)
    window = _context.get_window(WINDOW_ID) if _context is not None else _window
    if window is not None:
        window.refresh_all()


def _ask_replace() -> bool:
    from PySide6.QtWidgets import QMessageBox

    parent = _context.get_main_window() if _context is not None else None
    answer = QMessageBox.question(
        parent,
        PLUGIN_NAME,
        "This project contains an energy diagram. Replace the diagram that is open now?\n"
        "(Save the open one first if you want to keep it.)",
    )
    return answer == QMessageBox.StandardButton.Yes


def initialize(context):
    global _context
    _context = context
    context.add_menu_action("Extensions/Reaction Energy Diagram...", open_window)
    context.register_file_opener(FILE_EXTENSION, open_file)
    context.register_save_handler(save_project_state)
    context.register_load_handler(load_project_state)
    # No document-reset handler on purpose: File > New must not clear the
    # diagram (energies are gathered across several documents).

"""The window with a real Qt: tables, dragging, hiding, files, project hooks."""

import json

import pytest

pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("matplotlib")

from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

import energy_diagram
from energy_diagram import model

ORCA_G = "* O   R   C   A *\nFINAL SINGLE POINT ENERGY  -10.0\nFinal Gibbs free energy         ...   {g} Eh\n"


class FakeContext:
    def __init__(self):
        self.windows = {}
        self.menu = {}
        self.openers = {}
        self.save_handler = None
        self.load_handler = None
        self.reset_handlers = []
        self.current_molecule = None
        self.current_file = None

    def add_menu_action(self, path, callback):
        self.menu[path] = callback

    def register_file_opener(self, extension, callback, priority=0):
        self.openers[extension] = callback

    def register_save_handler(self, callback):
        self.save_handler = callback

    def register_load_handler(self, callback):
        self.load_handler = callback

    def register_document_reset_handler(self, callback):
        self.reset_handlers.append(callback)

    def get_main_window(self):
        return None

    def get_window(self, key):
        return self.windows.get(key)

    def register_window(self, key, window):
        self.windows[key] = window

    def get_current_file(self):
        return self.current_file


@pytest.fixture
def window(qapp):
    win = energy_diagram.open_window()
    yield win
    win.close()


@pytest.fixture
def plugin(qapp):
    context = FakeContext()
    energy_diagram.initialize(context)
    yield context
    win = context.windows.get(energy_diagram.WINDOW_ID)
    if win is not None:
        win.close()


@pytest.fixture
def answers(monkeypatch):
    """Answer every question box with the queued buttons; record warnings."""
    queue = []
    seen = []

    def question(*args, **kwargs):
        seen.append(args[2])
        return queue.pop(0) if queue else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: seen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: seen.append(a[2]))
    return queue, seen


def set_cell(win, row, col, text):
    win.levels.item(row, col).setText(text)


def add_levels(win, *energies):
    for energy in energies:
        win.add_level()
        row = win.selected_row()
        set_cell(win, row, 1, energy)


def drag(win, draggable, dx, dy):
    win.canvas.draw()
    box = draggable.artist.get_window_extent(win.canvas.get_renderer())
    x, y = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    win._on_press(MouseEvent("button_press_event", win.canvas, x, y, button=1))
    win._on_motion(MouseEvent("motion_notify_event", win.canvas, x + dx, y + dy))
    win._on_release(MouseEvent("button_release_event", win.canvas, x + dx, y + dy, button=1))


def test_typing_in_the_table_fills_the_diagram(window):
    add_levels(window, "0", "21.5", "-4")
    set_cell(window, 0, 0, "Reactants")
    levels = window.diagram.pathways[0].levels
    assert [lv.energy for lv in levels] == ["0", "21.5", "-4"]
    assert levels[0].label == "Reactants"
    assert levels[1].kind == model.KIND_TS  # a level after a minimum starts as a TS
    assert window.levels.item(1, 2).text() == "21.5"
    assert window.session.dirty
    assert window.windowTitle().endswith("Untitled*")


def test_a_bad_energy_shows_why(window):
    add_levels(window, "cat + sub")
    item = window.levels.item(0, 2)
    assert item.text() == "?"
    assert "No compound named 'cat'" in item.toolTip()


def test_compounds_feed_level_expressions(window, tmp_path, answers):
    a = tmp_path / "cat.out"
    a.write_text(ORCA_G.format(g="-100.000000"), encoding="utf-8")
    b = tmp_path / "TS-1.out"
    b.write_text(ORCA_G.format(g="-99.970000"), encoding="utf-8")
    assert window.add_output(str(a)).name == "cat"
    assert window.add_output(str(b)).name == "TS_1"
    window._fill_compounds()
    add_levels(window, "cat", "TS_1")
    assert window.diagram.values()[0][1] == pytest.approx(0.03 * model.PER_HARTREE["kcal/mol"])
    # Reading a re-run calculation updates the compound in place.
    b.write_text(ORCA_G.format(g="-99.980000"), encoding="utf-8")
    window.add_output(str(b))
    assert len(window.diagram.compounds) == 2
    assert window.diagram.values()[0][1] == pytest.approx(0.02 * model.PER_HARTREE["kcal/mol"])
    window.cmb_quantity.setCurrentIndex(window.cmb_quantity.findData("H"))
    assert window.add_output(str(a)) is None
    assert "has no enthalpy" in answers[1][-1]


def test_compound_table_edits_and_removal(window):
    window.add_compound()
    window.compounds.item(0, 0).setText("A")
    window.compounds.item(0, 1).setText("-1.5")
    assert (window.diagram.compounds[0].name, window.diagram.compounds[0].energy) == ("A", -1.5)
    window.compounds.item(0, 1).setText("not a number")
    assert window.diagram.compounds[0].energy == -1.5
    assert window.compounds.item(0, 1).text() == "-1.5000000000"
    window.compounds.selectRow(0)
    window.remove_compound()
    assert window.diagram.compounds == []


def test_from_open_document_reads_the_file_moleditpy_has_open(plugin, tmp_path, answers):
    window = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    window.compound_from_document()
    assert "no output file open" in answers[1][-1]
    out = tmp_path / "int2.out"
    out.write_text(ORCA_G.format(g="-5.5"), encoding="utf-8")
    plugin.current_file = str(out)
    window.compound_from_document()
    assert [(c.name, c.energy) for c in window.diagram.compounds] == [("int2", -5.5)]


def test_dragging_a_label_stores_its_offset(window):
    add_levels(window, "0", "10")
    set_cell(window, 0, 0, "R")
    window.redraw()
    label = next(d for d in window.rendered.draggables if d.item == "label")
    drag(window, label, 50, -20)
    scale = 72.0 / window.figure.dpi
    assert window.diagram.pathways[0].levels[0].label_offset == pytest.approx(
        [50 * scale, -20 * scale], abs=0.01
    )
    window.redraw()
    again = next(d for d in window.rendered.draggables if d.item == "label")
    assert again.offset()[0] == pytest.approx(50 * scale, abs=0.01)


def test_dragging_a_value_and_resetting_it(window):
    add_levels(window, "0")
    window.redraw()
    value = next(d for d in window.rendered.draggables if d.item == "energy")
    drag(window, value, 10, 10)
    assert window.diagram.pathways[0].levels[0].energy_offset != [0.0, 0.0]
    window.reset_offset(0, 0, "energy")
    assert window.diagram.pathways[0].levels[0].energy_offset == [0.0, 0.0]


def test_hiding_and_showing_again(window):
    add_levels(window, "0", "5")
    set_cell(window, 0, 0, "R")
    window.set_shown(0, 0, "label", False)
    assert window.levels.item(0, 5).checkState() == Qt.CheckState.Unchecked
    window.redraw()
    assert all(d.item != "label" for d in window.rendered.draggables)
    window.levels.item(1, 6).setCheckState(Qt.CheckState.Unchecked)
    assert not window.diagram.pathways[0].levels[1].show_energy
    window.show_everything()
    assert window.diagram.pathways[0].levels[0].show_label
    assert window.diagram.pathways[0].levels[1].show_energy


def test_clicking_a_level_selects_its_row(window):
    add_levels(window, "0", "8", "3")
    window.levels.selectRow(0)
    window.redraw()
    window.canvas.draw()
    bar = next(a for a, key in window.rendered.bars.items() if key == (0, 2))
    x, y = window.rendered.axes.transData.transform((2.0, bar.get_ydata()[0]))
    window._on_press(MouseEvent("button_press_event", window.canvas, x, y, button=1))
    assert window.selected_row() == 2


def test_pathways_add_copy_steps_and_remove(window, monkeypatch, answers):
    from PySide6.QtWidgets import QInputDialog

    add_levels(window, "0", "10")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Catalysed", True))
    window.add_pathway()
    second = window.diagram.pathways[1]
    assert second.name == "Catalysed" and len(second.levels) == 2
    assert second.color != window.diagram.pathways[0].color
    assert window.cmb_pathway.currentIndex() == 1
    queue, _ = answers
    queue.append(QMessageBox.StandardButton.Yes)
    window.remove_pathway()
    assert len(window.diagram.pathways) == 1
    window.remove_pathway()
    assert len(window.diagram.pathways) == 1


def test_level_order_and_removal(window):
    add_levels(window, "1", "2", "3")
    window.levels.selectRow(2)
    window.move_level(-1)
    assert [lv.energy for lv in window.diagram.pathways[0].levels] == ["1", "3", "2"]
    window.remove_level()
    assert [lv.energy for lv in window.diagram.pathways[0].levels] == ["1", "2"]


def test_style_widgets_write_the_style(window):
    window.style_widgets["connector"].setCurrentIndex(
        window.style_widgets["connector"].findData("curve")
    )
    window.style_widgets["fig_width"].setValue(3.3)
    window.style_widgets["show_barriers"].setChecked(True)
    window.style_widgets["quantity"].setText("ΔE")
    style = window.diagram.style
    assert (style.connector, style.fig_width, style.show_barriers, style.quantity) == (
        "curve",
        3.3,
        True,
        "ΔE",
    )
    window.redraw()
    assert window.canvas.width() == 330


def test_save_open_and_export(window, tmp_path, answers):
    add_levels(window, "0", "12.5")
    path = tmp_path / "profile"
    assert window._write(str(path))
    saved = tmp_path / "profile.pmeedg"
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["format"] == model.FILE_FORMAT
    assert not window.session.dirty and window.windowTitle().endswith("profile.pmeedg")
    window.new_diagram()
    assert window.diagram.is_empty()
    assert window.open_path(str(saved))
    assert [lv.energy for lv in window.diagram.pathways[0].levels] == ["0", "12.5"]
    assert window.export(str(tmp_path / "fig.svg"))
    assert (tmp_path / "fig.svg").exists()
    (tmp_path / "bad.pmeedg").write_text("{", encoding="utf-8")
    assert not window.open_path(str(tmp_path / "bad.pmeedg"))
    assert "damaged" in answers[1][-1]


def test_unsaved_changes_are_asked_about(window, answers):
    queue, _seen = answers
    add_levels(window, "1")
    queue.append(QMessageBox.StandardButton.Cancel)
    window.new_diagram()
    assert not window.diagram.is_empty()
    queue.append(QMessageBox.StandardButton.Discard)
    window.new_diagram()
    assert window.diagram.is_empty()


def test_copy_image(window, qapp):
    add_levels(window, "0", "3")
    window.copy_image()
    assert not qapp.clipboard().image().isNull()


# ----------------------------------------------------------------- plugin


def test_initialize_registers_menu_opener_and_project_hooks(plugin):
    assert list(plugin.menu) == ["Extensions/Reaction Energy Diagram..."]
    assert list(plugin.openers) == [".pmeedg"]
    assert plugin.save_handler is not None and plugin.load_handler is not None
    # File > New must not clear the diagram.
    assert plugin.reset_handlers == []
    first = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    assert plugin.menu["Extensions/Reaction Energy Diagram..."]() is first


def test_the_diagram_survives_closing_the_window(plugin):
    window = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    add_levels(window, "0", "7")
    window.close()
    plugin.windows.clear()
    again = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    assert [lv.energy for lv in again.diagram.pathways[0].levels] == ["0", "7"]


def test_the_autosave_brings_the_diagram_back_after_a_restart(plugin, monkeypatch):
    window = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    add_levels(window, "0", "9")
    window.close()
    monkeypatch.setattr(energy_diagram, "_session", None)
    session = energy_diagram.get_session()
    assert [lv.energy for lv in session.diagram.pathways[0].levels] == ["0", "9"]
    assert session.dirty


def test_project_storage_is_opt_in(plugin):
    window = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    add_levels(window, "0", "4")
    assert plugin.save_handler() == {}
    window.act_project.setChecked(True)
    stored = plugin.save_handler()
    assert stored["diagram"]["pathways"][0]["levels"][1]["energy"] == "4"


def test_project_load_fills_an_empty_diagram_and_asks_before_replacing(plugin, answers):
    queue, seen = answers
    incoming = model.Diagram()
    incoming.pathways[0].levels = [model.Level("X", "3")]
    plugin.load_handler({"diagram": incoming.to_dict()})
    assert energy_diagram.get_session().diagram.pathways[0].levels[0].label == "X"
    assert seen == []

    other = model.Diagram()
    other.pathways[0].levels = [model.Level("Y", "1")]
    plugin.load_handler({"diagram": other.to_dict()})  # answered No
    assert energy_diagram.get_session().diagram.pathways[0].levels[0].label == "X"
    queue.append(QMessageBox.StandardButton.Yes)
    plugin.load_handler({"diagram": other.to_dict()})
    assert energy_diagram.get_session().diagram.pathways[0].levels[0].label == "Y"
    # A project without a diagram, or a damaged one, changes nothing.
    plugin.load_handler({})
    plugin.load_handler({"diagram": {"format": "other"}})
    assert energy_diagram.get_session().diagram.pathways[0].levels[0].label == "Y"


def test_the_file_opener_opens_pmeedg_files(plugin, tmp_path):
    d = model.Diagram()
    d.pathways[0].levels = [model.Level("Z", "2")]
    path = tmp_path / "z.pmeedg"
    path.write_text(json.dumps(d.to_dict()), encoding="utf-8")
    assert plugin.openers[".pmeedg"](str(path)) is True
    window = plugin.windows[energy_diagram.WINDOW_ID]
    assert window.diagram.pathways[0].levels[0].label == "Z"
    assert window.session.path == str(path)


def test_structure_from_the_loaded_molecule(plugin, answers):
    pytest.importorskip("rdkit")
    from rdkit import Chem

    window = plugin.menu["Extensions/Reaction Energy Diagram..."]()
    add_levels(window, "0")
    window.structure_from_loaded()
    assert "No molecule" in answers[1][-1]
    plugin.current_molecule = Chem.AddHs(Chem.MolFromSmiles("OCC"))
    window.levels.selectRow(0)
    window.structure_from_loaded()
    assert window.diagram.pathways[0].levels[0].smiles == "CCO"


# ------------------------------------------------------- result analyzers


@pytest.fixture
def orca_analyzer(monkeypatch, qapp):
    """A loaded 'ORCA Result Analyzer' plugin with one window showing TS-1.out."""
    import types

    from PySide6.QtWidgets import QDialog

    module = types.ModuleType("fake_orca_analyzer")
    module.__package__ = "fake_orca_analyzer"
    module.PLUGIN_NAME = "ORCA Result Analyzer"
    monkeypatch.setitem(__import__("sys").modules, "fake_orca_analyzer", module)
    dialog_class = type(
        "OrcaResultAnalyzerDialog", (QDialog,), {"__module__": "fake_orca_analyzer.gui"}
    )
    analyzer = dialog_class()
    analyzer.parser = types.SimpleNamespace(
        data={
            "scf_energy": -100.0,
            "thermal": {
                "electronic_energy": -100.0,
                "zpe": 0.05,
                "gibbs": -99.97,
                "gibbs_corr": 0.03,
            },
        }
    )
    analyzer.file_path = "/calc/TS-1.out"
    yield analyzer
    analyzer.close()
    analyzer.deleteLater()


def test_the_analyzer_button_is_hidden_without_an_analyzer(window):
    assert window.btn_from_analyzer.isHidden()


def test_the_analyzer_button_shows_when_an_analyzer_is_loaded(orca_analyzer, window):
    assert not window.btn_from_analyzer.isHidden()


def test_no_open_analyzer_file_is_explained(orca_analyzer, window, answers):
    window.compounds_from_analyzers()  # the analyzer window is not shown
    assert "Open the calculation in the ORCA" in answers[1][-1]
    assert window.diagram.compounds == []


def test_picking_values_from_an_open_analyzer(orca_analyzer, window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from energy_diagram import window as window_module

    orca_analyzer.show()
    seen = {}

    def run(dialog):
        seen["rows"] = [(v.key, dialog.table.item(r, 4).text()) for r, v in enumerate(dialog.found)]
        seen["ticked"] = [name for name, _ in dialog.chosen()]
        dialog.set_checked(next(r for r, v in enumerate(dialog.found) if v.key == "Gcorr"), True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(window_module.AnalyzerValuesDialog, "exec", run)
    window.compounds_from_analyzers()
    assert seen["rows"] == [
        ("E", "TS_1_E"),
        ("EZPE", "TS_1_EZPE"),
        ("G", "TS_1"),
        ("ZPE", "TS_1_ZPE"),
        ("Gcorr", "TS_1_Gcorr"),
    ]
    assert seen["ticked"] == ["TS_1"]  # the quantity chosen under Take: is ticked
    assert [(c.name, c.energy, c.source) for c in window.diagram.compounds] == [
        ("TS_1", -99.97, "ORCA Result Analyzer G: TS-1.out"),
        ("TS_1_Gcorr", 0.03, "ORCA Result Analyzer Gcorr: TS-1.out"),
    ]
    # Picking again after a re-run updates the compounds instead of adding more.
    orca_analyzer.parser.data["thermal"]["gibbs"] = -99.98
    window.compounds_from_analyzers()
    assert len(window.diagram.compounds) == 2
    assert window.diagram.compounds[0].energy == -99.98


def test_the_picker_skips_rows_without_a_name_and_follows_take(orca_analyzer, qapp):
    from energy_diagram import analyzers
    from energy_diagram.window import AnalyzerValuesDialog

    orca_analyzer.show()
    (result,) = analyzers.open_results(qapp.topLevelWidgets())
    dialog = AnalyzerValuesDialog(analyzers.values(result), "E")
    assert [name for name, _ in dialog.chosen()] == ["TS_1"]
    assert dialog.chosen()[0][1].key == "E"
    dialog.table.item(0, dialog.COL_NAME).setText("  ")
    assert dialog.chosen() == []
    dialog.close()

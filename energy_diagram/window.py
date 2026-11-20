"""The diagram window: tables on the left, the live figure on the right.

The figure is drawn at its real size (inches at 100 dpi on screen), so what
is dragged into place is what is exported. Everything the user sets lives in
the session's Diagram; this window only edits it and redraws.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QImage, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# isort: split
# PySide6 must be imported first, so matplotlib's Qt backend uses it and not
# another binding named by QT_API.
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from . import model, parsers, render

logger = logging.getLogger(__name__)

TITLE = "Reaction Energy Diagram"
FILE_FILTER = f"Energy diagrams (*{model.FILE_EXTENSION});;All files (*)"
OUTPUT_FILTER = "Output files (*.out *.log *.txt);;All files (*)"
SCREEN_DPI = 100

# Level table columns.
COL_LABEL, COL_ENERGY, COL_VALUE, COL_KIND, COL_POS, COL_SHOW_LABEL, COL_SHOW_VALUE, COL_SMILES = (
    range(8)
)
LEVEL_HEADERS = [
    "Label",
    "Energy",
    "Value",
    "Type",
    "Position",
    "Label",
    "Value",
    "Structure (SMILES)",
]
ITEM_NAMES = {
    "label": "Label",
    "energy": "Value",
    "structure": "Structure",
    "barrier": "Barrier value",
}


class DiagramWindow(QMainWindow):
    def __init__(self, session, context=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.context = context
        self._filling = False
        self._drag = None
        self.rendered = None
        self.setWindowTitle(TITLE)
        self.resize(1280, 760)
        self.figure = Figure(dpi=SCREEN_DPI)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(120)
        self._redraw_timer.timeout.connect(self.redraw)
        self._build()
        self.session.listeners.append(self._session_changed)
        self.refresh_all()

    @property
    def diagram(self) -> model.Diagram:
        return self.session.diagram

    # ================================================================ build
    def _build(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_levels(), "Levels")
        self.tabs.addTab(self._build_compounds(), "Compounds")
        self.tabs.addTab(self._build_style(), "Style")
        splitter.addWidget(self.tabs)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            "Drag a label, value or structure to move it. Right-click it to hide it or put it "
            "back. Click a level to find it in the table."
        )
        hint.setWordWrap(True)
        right_layout.addWidget(hint)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.canvas)
        self.scroll.setStyleSheet("QScrollArea { background: #808080; }")
        right_layout.addWidget(self.scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([560, 720])
        self.setCentralWidget(splitter)

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self._build_menu()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        self.act_new = self._action(
            menu, "&New Diagram", self.new_diagram, QKeySequence.StandardKey.New
        )
        self.act_open = self._action(
            menu, "&Open...", self.open_dialog, QKeySequence.StandardKey.Open
        )
        self.act_save = self._action(menu, "&Save", self.save, QKeySequence.StandardKey.Save)
        self.act_save_as = self._action(
            menu, "Save &As...", self.save_as, QKeySequence.StandardKey.SaveAs
        )
        menu.addSeparator()
        self.act_export = self._action(menu, "&Export Image...", self.export_dialog, "Ctrl+E")
        self.act_copy = self._action(menu, "&Copy Image", self.copy_image, "Ctrl+Shift+C")
        menu.addSeparator()
        self.act_project = QAction("Store in the MoleditPy &Project File", self)
        self.act_project.setCheckable(True)
        self.act_project.setToolTip(
            "Also save this diagram inside the .pmeprj when the project is saved."
        )
        self.act_project.toggled.connect(self._project_toggled)
        self.act_project.setEnabled(self.context is not None)
        menu.addAction(self.act_project)
        menu.addSeparator()
        self._action(menu, "&Close", self.close, QKeySequence.StandardKey.Close)

    def _action(self, menu, text, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # -------------------------------------------------------------- levels
    def _build_levels(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("Pathway:"))
        self.cmb_pathway = QComboBox()
        self.cmb_pathway.currentIndexChanged.connect(self._pathway_selected)
        row.addWidget(self.cmb_pathway, 1)
        for text, slot in (
            ("Add", self.add_pathway),
            ("Rename", self.rename_pathway),
            ("Color...", self.pathway_color),
            ("Remove", self.remove_pathway),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self.chk_pathway_visible = QCheckBox("Show this pathway")
        self.chk_pathway_visible.toggled.connect(self._pathway_visible)
        layout.addWidget(self.chk_pathway_visible)

        self.levels = QTableWidget(0, len(LEVEL_HEADERS))
        self.levels.setHorizontalHeaderLabels(LEVEL_HEADERS)
        self.levels.verticalHeader().setVisible(True)
        self.levels.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.levels.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.levels.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for col, width in (
            (COL_LABEL, 90),
            (COL_ENERGY, 120),
            (COL_VALUE, 64),
            (COL_KIND, 72),
            (COL_POS, 58),
            (COL_SHOW_LABEL, 44),
            (COL_SHOW_VALUE, 44),
        ):
            self.levels.setColumnWidth(col, width)
        tips = {
            COL_LABEL: "Text above the level.",
            COL_ENERGY: "A number in the input unit, a compound name, or a sum: "
            "cat + sub, 2*H2O + X - 1.5, {name with spaces}.",
            COL_VALUE: "The value on the axis, in the display unit.",
            COL_POS: "Horizontal position; blank places the level by its row.",
            COL_SHOW_LABEL: "Show the label.",
            COL_SHOW_VALUE: "Show the value.",
            COL_SMILES: "Drawn above the level when Style > Show structures is on.",
        }
        for col, tip in tips.items():
            self.levels.horizontalHeaderItem(col).setToolTip(tip)
        self.levels.itemChanged.connect(self._level_item_changed)
        self.levels.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.levels.customContextMenuRequested.connect(self._level_table_menu)
        layout.addWidget(self.levels, 1)

        buttons = QHBoxLayout()
        for text, slot in (
            ("Add Level", self.add_level),
            ("Remove", self.remove_level),
            ("Up", lambda: self.move_level(-1)),
            ("Down", lambda: self.move_level(1)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        more = QHBoxLayout()
        self.btn_structure = QPushButton("Structure from Loaded Molecule")
        self.btn_structure.setToolTip("Put the molecule open in MoleditPy into the selected level.")
        self.btn_structure.clicked.connect(self.structure_from_loaded)
        self.btn_structure.setEnabled(self.context is not None)
        more.addWidget(self.btn_structure)
        reset = QPushButton("Reset Positions")
        reset.setToolTip("Put every dragged label of this pathway back in its default place.")
        reset.clicked.connect(self.reset_positions)
        more.addWidget(reset)
        layout.addLayout(more)
        return page

    # ----------------------------------------------------------- compounds
    def _build_compounds(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Energies of single calculations, in Hartree. A level's energy can name them, "
            "e.g. “cat + sub”. Use {braces} for names with other characters."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.compounds = QTableWidget(0, 3)
        self.compounds.setHorizontalHeaderLabels(["Name", "Energy (Eh)", "Source"])
        self.compounds.horizontalHeader().setStretchLastSection(True)
        self.compounds.setColumnWidth(0, 120)
        self.compounds.setColumnWidth(1, 150)
        self.compounds.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.compounds.itemChanged.connect(self._compound_item_changed)
        layout.addWidget(self.compounds, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Take:"))
        self.cmb_quantity = QComboBox()
        for key, text in parsers.QUANTITIES.items():
            self.cmb_quantity.addItem(text, key)
        self.cmb_quantity.setCurrentIndex(self.cmb_quantity.findData(parsers.QUANTITY_G))
        row.addWidget(self.cmb_quantity, 1)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        for text, slot, tip in (
            ("Add", self.add_compound, "Add an empty row."),
            ("From Output Files...", self.compounds_from_files, "ORCA, Gaussian or GAMESS output."),
            (
                "From Open Document",
                self.compound_from_document,
                "The output file open in MoleditPy, named after it.",
            ),
            ("Remove", self.remove_compound, "Remove the selected rows."),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
            if text == "From Open Document":
                button.setEnabled(self.context is not None)
                self.btn_from_document = button
        layout.addLayout(buttons)
        return page

    # --------------------------------------------------------------- style
    def _build_style(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.style_widgets = {}

        def combo(name, choices, label):
            widget = QComboBox()
            for key, text in choices:
                widget.addItem(text, key)
            widget.currentIndexChanged.connect(
                lambda _=0, n=name, w=widget: self._style_set(n, w.currentData())
            )
            self.style_widgets[name] = widget
            form.addRow(label, widget)

        def text(name, label, placeholder=""):
            widget = QLineEdit()
            widget.setPlaceholderText(placeholder)
            widget.textChanged.connect(lambda value, n=name: self._style_set(n, value))
            self.style_widgets[name] = widget
            form.addRow(label, widget)

        def number(name, label, low, high, step, decimals=1, suffix=""):
            widget = QDoubleSpinBox()
            widget.setRange(low, high)
            widget.setSingleStep(step)
            widget.setDecimals(decimals)
            widget.setSuffix(suffix)
            widget.valueChanged.connect(lambda value, n=name: self._style_set(n, float(value)))
            self.style_widgets[name] = widget
            form.addRow(label, widget)

        def check(name, label):
            widget = QCheckBox(label)
            widget.toggled.connect(lambda value, n=name: self._style_set(n, bool(value)))
            self.style_widgets[name] = widget
            form.addRow(widget)

        units = [(u, u) for u in model.UNITS]
        combo("input_unit", units, "Numbers typed in:")
        combo(
            "display_unit",
            [(u, u) for u in model.UNITS if u != "Hartree"] + [("Hartree", "Hartree")],
            "Axis unit:",
        )
        combo(
            "zero",
            [
                (model.ZERO_FIRST, "First level of the first pathway"),
                (model.ZERO_NONE, "None (values are relative already)"),
            ],
            "Zero:",
        )
        text("quantity", "Quantity:", "ΔG")
        text("y_label", "Axis title:", "automatic: quantity (unit)")
        text("x_label", "Bottom title:")
        text("title", "Figure title:")
        combo(
            "connector",
            [
                ("dashed", "Dashed lines"),
                ("dotted", "Dotted lines"),
                ("solid", "Solid lines"),
                ("curve", "Smooth curve"),
                ("none", "None"),
            ],
            "Connectors:",
        )
        number("level_width", "Level width:", 0.1, 0.95, 0.05, 2)
        number("level_linewidth", "Level thickness:", 0.5, 8, 0.25, 2, " pt")
        number("connector_linewidth", "Connector thickness:", 0.25, 5, 0.25, 2, " pt")
        widget = QSpinBox()
        widget.setRange(0, 6)
        widget.valueChanged.connect(lambda value: self._style_set("decimals", int(value)))
        self.style_widgets["decimals"] = widget
        form.addRow("Decimals:", widget)
        check("energy_parentheses", "Values in parentheses")
        check("energy_sign", "Plus sign on positive values")
        check("energy_unit_suffix", "Unit after each value")
        check("show_barriers", "Show barriers (‡ arrows)")
        check("show_structures", "Show structures")
        number("structure_size", "Structure size:", 0.2, 3, 0.05, 2, " in")
        check("show_legend", "Legend (several pathways)")
        check("show_y_axis", "Energy axis")
        text("font_family", "Font:", "Arial")
        number("font_size", "Axis font size:", 4, 30, 0.5, 1, " pt")
        number("label_size", "Label size:", 4, 30, 0.5, 1, " pt")
        number("energy_size", "Value size:", 4, 30, 0.5, 1, " pt")
        check("label_bold", "Bold labels")
        number("fig_width", "Width:", 1, 20, 0.1, 2, " in")
        number("fig_height", "Height:", 1, 20, 0.1, 2, " in")
        check("transparent", "Transparent background")
        return page

    # ============================================================ refreshing
    def _session_changed(self) -> None:
        self._update_title()

    def refresh_all(self) -> None:
        """Every widget from the diagram, then the figure."""
        self._filling = True
        try:
            self._fill_pathways()
            self._fill_levels()
            self._fill_compounds()
            self._fill_style()
            self.act_project.setChecked(self.diagram.store_in_project)
        finally:
            self._filling = False
        self._update_title()
        self.redraw()

    def _update_title(self) -> None:
        name = os.path.basename(self.session.path) if self.session.path else "Untitled"
        self.setWindowTitle(f"{TITLE} - {name}{'*' if self.session.dirty else ''}")

    def _changed(self, redraw: bool = True) -> None:
        self.session.changed()
        if redraw:
            self._redraw_timer.start()

    def current_pathway(self) -> model.Pathway:
        index = max(0, min(self.cmb_pathway.currentIndex(), len(self.diagram.pathways) - 1))
        return self.diagram.pathways[index]

    def _fill_pathways(self, select: int | None = None) -> None:
        keep = self.cmb_pathway.currentIndex() if select is None else select
        was = self._filling
        self._filling = True
        self.cmb_pathway.clear()
        for pathway in self.diagram.pathways:
            self.cmb_pathway.addItem(pathway.name)
            self.cmb_pathway.setItemData(
                self.cmb_pathway.count() - 1, QColor(pathway.color), Qt.ItemDataRole.DecorationRole
            )
        self.cmb_pathway.setCurrentIndex(max(0, min(keep, len(self.diagram.pathways) - 1)))
        self.chk_pathway_visible.setChecked(self.current_pathway().visible)
        self._filling = was

    def _fill_levels(self) -> None:
        was = self._filling
        self._filling = True
        pathway = self.current_pathway()
        p_index = self.diagram.pathways.index(pathway)
        values = self.diagram.values()[p_index]
        self.levels.setRowCount(len(pathway.levels))
        for row, level in enumerate(pathway.levels):
            self.levels.setItem(row, COL_LABEL, QTableWidgetItem(level.label))
            self.levels.setItem(row, COL_ENERGY, QTableWidgetItem(level.energy))
            self.levels.setItem(
                row,
                COL_POS,
                QTableWidgetItem("" if level.position is None else f"{level.position:g}"),
            )
            self.levels.setItem(row, COL_SMILES, QTableWidgetItem(level.smiles))
            for col, value in (
                (COL_SHOW_LABEL, level.show_label),
                (COL_SHOW_VALUE, level.show_energy),
            ):
                item = QTableWidgetItem()
                item.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                item.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
                self.levels.setItem(row, col, item)
            kind = QComboBox()
            kind.addItem("Min", model.KIND_MIN)
            kind.addItem("TS", model.KIND_TS)
            kind.setCurrentIndex(1 if level.kind == model.KIND_TS else 0)
            kind.currentIndexChanged.connect(
                lambda _=0, r=row, w=kind: self._kind_changed(r, w.currentData())
            )
            self.levels.setCellWidget(row, COL_KIND, kind)
            self._set_value_cell(row, level, values[row])
        self._filling = was

    def _set_value_cell(self, row: int, level: model.Level, value) -> None:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if value is None:
            try:
                self.diagram.absolute(level)
                message = ""
            except model.ExpressionError as exc:
                message = str(exc)
            item.setText("?")
            item.setForeground(QColor("#c0392b"))
            item.setToolTip(message)
        else:
            item.setText(f"{value:.{self.diagram.style.decimals}f}")
        self.levels.setItem(row, COL_VALUE, item)

    def _refresh_values(self) -> None:
        was = self._filling
        self._filling = True
        pathway = self.current_pathway()
        values = self.diagram.values()[self.diagram.pathways.index(pathway)]
        for row, level in enumerate(pathway.levels):
            self._set_value_cell(row, level, values[row])
        self._filling = was

    def _fill_compounds(self) -> None:
        was = self._filling
        self._filling = True
        self.compounds.setRowCount(len(self.diagram.compounds))
        for row, compound in enumerate(self.diagram.compounds):
            self.compounds.setItem(row, 0, QTableWidgetItem(compound.name))
            energy = "" if compound.energy is None else f"{compound.energy:.10f}"
            self.compounds.setItem(row, 1, QTableWidgetItem(energy))
            source = QTableWidgetItem(compound.source)
            source.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            source.setToolTip(compound.source)
            self.compounds.setItem(row, 2, source)
        self._filling = was

    def _fill_style(self) -> None:
        style = self.diagram.style
        for name, widget in self.style_widgets.items():
            value = getattr(style, name)
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif isinstance(widget, QLineEdit):
                widget.setText(value)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            else:
                widget.setValue(value)
            widget.blockSignals(False)

    # ================================================================= edits
    def _style_set(self, name: str, value) -> None:
        if self._filling:
            return
        setattr(self.diagram.style, name, value)
        if name in ("input_unit", "display_unit", "zero", "decimals"):
            self._refresh_values()
        self._changed()

    def _project_toggled(self, checked: bool) -> None:
        if self._filling:
            return
        self.diagram.store_in_project = checked
        self._changed(redraw=False)

    def _pathway_selected(self) -> None:
        if self._filling:
            return
        self._filling = True
        self.chk_pathway_visible.setChecked(self.current_pathway().visible)
        self._filling = False
        self._fill_levels()

    def _pathway_visible(self, checked: bool) -> None:
        if self._filling:
            return
        self.current_pathway().visible = checked
        self._refresh_values()
        self._changed()

    def add_pathway(self) -> None:
        name, ok = QInputDialog.getText(
            self, TITLE, "Pathway name:", text=f"Pathway {len(self.diagram.pathways) + 1}"
        )
        if not ok:
            return
        current = self.current_pathway()
        # The new pathway starts with the same steps, which is how two routes
        # are usually compared; their energies are then typed over.
        levels = [
            model.Level(label=lv.label, kind=lv.kind, position=lv.position, show_label=False)
            for lv in current.levels
        ]
        self.diagram.pathways.append(
            model.Pathway(
                name=name.strip() or "Pathway", color=self.diagram.next_color(), levels=levels
            )
        )
        self._fill_pathways(select=len(self.diagram.pathways) - 1)
        self._fill_levels()
        self._changed()

    def rename_pathway(self) -> None:
        pathway = self.current_pathway()
        name, ok = QInputDialog.getText(self, TITLE, "Pathway name:", text=pathway.name)
        if ok and name.strip():
            pathway.name = name.strip()
            self._fill_pathways()
            self._changed()

    def pathway_color(self) -> None:
        pathway = self.current_pathway()
        color = QColorDialog.getColor(QColor(pathway.color), self, "Pathway Color")
        if color.isValid():
            pathway.color = color.name()
            self._fill_pathways()
            self._changed()

    def remove_pathway(self) -> None:
        if len(self.diagram.pathways) == 1:
            QMessageBox.information(self, TITLE, "A diagram keeps at least one pathway.")
            return
        pathway = self.current_pathway()
        answer = QMessageBox.question(
            self, TITLE, f"Remove the pathway “{pathway.name}” and its levels?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.diagram.pathways.remove(pathway)
        self._fill_pathways(select=0)
        self._fill_levels()
        self._changed()

    def selected_row(self) -> int:
        rows = self.levels.selectionModel().selectedRows() if self.levels.selectionModel() else []
        if rows:
            return rows[0].row()
        return self.levels.currentRow()

    def add_level(self) -> None:
        pathway = self.current_pathway()
        row = self.selected_row()
        at = row + 1 if 0 <= row < len(pathway.levels) else len(pathway.levels)
        kind = (
            model.KIND_TS
            if pathway.levels and at > 0 and pathway.levels[at - 1].kind == model.KIND_MIN
            else model.KIND_MIN
        )
        pathway.levels.insert(at, model.Level(kind=kind))
        self._fill_levels()
        self.levels.selectRow(at)
        self._changed()

    def remove_level(self) -> None:
        pathway = self.current_pathway()
        row = self.selected_row()
        if 0 <= row < len(pathway.levels):
            del pathway.levels[row]
            self._fill_levels()
            self._changed()

    def move_level(self, step: int) -> None:
        pathway = self.current_pathway()
        row = self.selected_row()
        target = row + step
        if 0 <= row < len(pathway.levels) and 0 <= target < len(pathway.levels):
            levels = pathway.levels
            levels[row], levels[target] = levels[target], levels[row]
            self._fill_levels()
            self.levels.selectRow(target)
            self._changed()

    def _kind_changed(self, row: int, kind: str) -> None:
        if self._filling:
            return
        self.current_pathway().levels[row].kind = kind
        self._changed()

    def _level_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        pathway = self.current_pathway()
        row, col = item.row(), item.column()
        if row >= len(pathway.levels):
            return
        level = pathway.levels[row]
        if col == COL_LABEL:
            level.label = item.text()
        elif col == COL_ENERGY:
            level.energy = item.text().strip()
            self._refresh_values()
        elif col == COL_POS:
            text = item.text().strip()
            try:
                level.position = float(text) if text else None
            except ValueError:
                self._filling = True
                item.setText("" if level.position is None else f"{level.position:g}")
                self._filling = False
                return
        elif col == COL_SMILES:
            level.smiles = item.text().strip()
        elif col == COL_SHOW_LABEL:
            level.show_label = item.checkState() == Qt.CheckState.Checked
        elif col == COL_SHOW_VALUE:
            level.show_energy = item.checkState() == Qt.CheckState.Checked
        else:
            return
        self._changed()

    def _level_table_menu(self, pos) -> None:
        row = self.levels.rowAt(pos.y())
        if row < 0:
            return
        self.levels.selectRow(row)
        self._level_menu(self.diagram.pathways.index(self.current_pathway()), row)

    def structure_from_loaded(self) -> None:
        row = self.selected_row()
        pathway = self.current_pathway()
        if not 0 <= row < len(pathway.levels):
            QMessageBox.information(self, TITLE, "Select the level to put the structure on.")
            return
        smiles = loaded_smiles(self.context)
        if not smiles:
            QMessageBox.information(self, TITLE, "No molecule is open in MoleditPy.")
            return
        pathway.levels[row].smiles = smiles
        self._fill_levels()
        self.levels.selectRow(row)
        self._changed()

    def reset_positions(self) -> None:
        for level in self.current_pathway().levels:
            for name in model.OFFSETS.values():
                setattr(level, name, [0.0, 0.0])
        self._changed()

    # ------------------------------------------------------------ compounds
    def _compound_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        row = item.row()
        if row >= len(self.diagram.compounds):
            return
        compound = self.diagram.compounds[row]
        if item.column() == 0:
            compound.name = item.text().strip()
        elif item.column() == 1:
            text = item.text().strip()
            try:
                compound.energy = float(text) if text else None
            except ValueError:
                self._filling = True
                item.setText("" if compound.energy is None else f"{compound.energy:.10f}")
                self._filling = False
                return
        else:
            return
        self._refresh_values()
        self._changed()

    def _unique_name(self, name: str) -> str:
        taken = {c.name for c in self.diagram.compounds}
        if name not in taken:
            return name
        n = 2
        while f"{name}_{n}" in taken:
            n += 1
        return f"{name}_{n}"

    def add_compound(self) -> None:
        self.diagram.compounds.append(model.Compound(name=self._unique_name("compound")))
        self._fill_compounds()
        self._changed(redraw=False)

    def remove_compound(self) -> None:
        rows = sorted({i.row() for i in self.compounds.selectedIndexes()}, reverse=True)
        for row in rows:
            if row < len(self.diagram.compounds):
                del self.diagram.compounds[row]
        if rows:
            self._fill_compounds()
            self._refresh_values()
            self._changed()

    def add_output(self, path: str) -> model.Compound | None:
        """One compound from an output file, with the quantity chosen."""
        quantity = self.cmb_quantity.currentData()
        try:
            energy, source = parsers.read_energy(path, quantity)
        except (parsers.OutputError, OSError) as exc:
            QMessageBox.warning(self, TITLE, str(exc))
            return None
        name = parsers.compound_name(path)
        existing = next((c for c in self.diagram.compounds if c.name == name), None)
        if existing is not None:
            # Reading the same file again updates its value in place, so the
            # levels that name it follow a re-run calculation.
            existing.energy, existing.source = energy, source
            compound = existing
        else:
            compound = model.Compound(name=name, energy=energy, source=source)
            self.diagram.compounds.append(compound)
        self.session.last_dir = os.path.dirname(path)
        return compound

    def compounds_from_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Output Files", self.session.last_dir, OUTPUT_FILTER
        )
        added = [c for c in (self.add_output(p) for p in paths) if c is not None]
        if added:
            self._fill_compounds()
            self._refresh_values()
            self._changed()

    def compound_from_document(self) -> None:
        path = ""
        if self.context is not None:
            try:
                path = self.context.get_current_file() or ""
            except Exception:  # pragma: no cover - older hosts
                logger.debug("get_current_file failed", exc_info=True)
        if not path or not os.path.isfile(path):
            QMessageBox.information(
                self,
                TITLE,
                "MoleditPy has no output file open. Open the calculation's output first, or use "
                "From Output Files.",
            )
            return
        if self.add_output(path) is not None:
            self._fill_compounds()
            self._refresh_values()
            self._changed()

    # ================================================================ figure
    def redraw(self) -> None:
        self._redraw_timer.stop()
        try:
            self.rendered = render.render(self.diagram, self.figure)
        except Exception:
            logger.exception("Drawing the energy diagram failed")
            return
        style = self.diagram.style
        self.canvas.setFixedSize(
            int(style.fig_width * SCREEN_DPI), int(style.fig_height * SCREEN_DPI)
        )
        self.canvas.draw_idle()

    def _hit(self, event):
        if self.rendered is None:
            return None
        for draggable in reversed(self.rendered.draggables):
            if draggable.contains(event):
                return draggable
        return None

    def _bar(self, event):
        if self.rendered is None:
            return None
        for artist, key in self.rendered.bars.items():
            if artist.contains(event)[0]:
                return key
        return None

    def _on_press(self, event) -> None:
        hit = self._hit(event)
        if event.button == 3:
            if hit is not None:
                self._item_menu(hit)
            else:
                bar = self._bar(event)
                if bar is not None:
                    self._level_menu(*bar)
                else:
                    self._figure_menu()
            return
        if event.button != 1:
            return
        if hit is not None:
            self._drag = (hit, event.x, event.y, hit.offset())
            return
        bar = self._bar(event)
        if bar is not None:
            self.show_level(*bar)

    def _on_motion(self, event) -> None:
        if self._drag is None or event.x is None:
            return
        hit, x0, y0, start = self._drag
        scale = 72.0 / self.figure.dpi
        hit.set_offset(start[0] + (event.x - x0) * scale, start[1] + (event.y - y0) * scale)
        self.canvas.draw_idle()

    def _on_release(self, event) -> None:
        if self._drag is None:
            return
        hit = self._drag[0]
        self._drag = None
        x, y = hit.offset()
        level = self.diagram.pathways[hit.pathway].levels[hit.index]
        setattr(
            level, model.OFFSETS[hit.item], [round(x - hit.base[0], 2), round(y - hit.base[1], 2)]
        )
        self._changed(redraw=False)

    def show_level(self, p_index: int, index: int) -> None:
        if self.cmb_pathway.currentIndex() != p_index:
            self.cmb_pathway.setCurrentIndex(p_index)
        self.tabs.setCurrentIndex(0)
        self.levels.selectRow(index)

    def _item_menu(self, hit) -> None:
        level = self.diagram.pathways[hit.pathway].levels[hit.index]
        menu = QMenu(self)
        menu.addAction(
            f"Hide {ITEM_NAMES[hit.item]}",
            lambda: self.set_shown(hit.pathway, hit.index, hit.item, False),
        )
        menu.addAction(
            "Reset Position", lambda: self.reset_offset(hit.pathway, hit.index, hit.item)
        )
        if hit.item == "label":
            menu.addAction("Edit Label...", lambda: self.edit_label(hit.pathway, hit.index))
        menu.addSeparator()
        menu.addAction(
            f"Find “{level.label or 'level'}” in the Table",
            lambda: self.show_level(hit.pathway, hit.index),
        )
        menu.exec(QCursor.pos())

    def _level_menu(self, p_index: int, index: int) -> None:
        level = self.diagram.pathways[p_index].levels[index]
        menu = QMenu(self)
        for item, name in ITEM_NAMES.items():
            shown = getattr(level, model.SHOWN[item])
            action = menu.addAction(f"Show {name}")
            action.setCheckable(True)
            action.setChecked(shown)
            action.toggled.connect(lambda on, it=item: self.set_shown(p_index, index, it, on))
        menu.addSeparator()
        menu.addAction("Level Color...", lambda: self.level_color(p_index, index))
        if level.color:
            menu.addAction(
                "Use the Pathway Color", lambda: self.set_level_color(p_index, index, "")
            )
        menu.addAction("Reset Positions", lambda: self.reset_offset(p_index, index, None))
        menu.exec(QCursor.pos())

    def _figure_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Show Every Hidden Label and Value", self.show_everything)
        menu.addAction("Reset Every Position", self.reset_every_position)
        menu.addSeparator()
        menu.addAction("Copy Image", self.copy_image)
        menu.addAction("Export Image...", self.export_dialog)
        menu.exec(QCursor.pos())

    def set_shown(self, p_index: int, index: int, item: str, shown: bool) -> None:
        setattr(self.diagram.pathways[p_index].levels[index], model.SHOWN[item], shown)
        if p_index == self.cmb_pathway.currentIndex():
            self._fill_levels()
        self._changed()

    def reset_offset(self, p_index: int, index: int, item: str | None) -> None:
        level = self.diagram.pathways[p_index].levels[index]
        for key, name in model.OFFSETS.items():
            if item is None or key == item:
                setattr(level, name, [0.0, 0.0])
        self._changed()

    def edit_label(self, p_index: int, index: int) -> None:
        level = self.diagram.pathways[p_index].levels[index]
        text, ok = QInputDialog.getText(self, TITLE, "Label:", text=level.label)
        if ok:
            level.label = text
            if p_index == self.cmb_pathway.currentIndex():
                self._fill_levels()
            self._changed()

    def level_color(self, p_index: int, index: int) -> None:
        level = self.diagram.pathways[p_index].levels[index]
        color = QColorDialog.getColor(
            QColor(level.color or self.diagram.pathways[p_index].color), self, "Level Color"
        )
        if color.isValid():
            self.set_level_color(p_index, index, color.name())

    def set_level_color(self, p_index: int, index: int, color: str) -> None:
        self.diagram.pathways[p_index].levels[index].color = color
        self._changed()

    def show_everything(self) -> None:
        for pathway in self.diagram.pathways:
            for level in pathway.levels:
                for name in model.SHOWN.values():
                    setattr(level, name, True)
        self._fill_levels()
        self._changed()

    def reset_every_position(self) -> None:
        for pathway in self.diagram.pathways:
            for level in pathway.levels:
                for name in model.OFFSETS.values():
                    setattr(level, name, [0.0, 0.0])
        self._changed()

    # ================================================================= files
    def confirm_discard(self) -> bool:
        if not self.session.dirty or self.diagram.is_empty():
            return True
        answer = QMessageBox.question(
            self,
            TITLE,
            "The diagram has unsaved changes. Save them first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_diagram(self) -> None:
        if self.confirm_discard():
            self.session.new()
            self.refresh_all()

    def open_dialog(self) -> None:
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Energy Diagram", self.session.last_dir, FILE_FILTER
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        try:
            self.session.open(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, TITLE, f"Could not open {os.path.basename(path)}:\n{exc}")
            return False
        self.refresh_all()
        return True

    def save(self) -> bool:
        if not self.session.path:
            return self.save_as()
        return self._write(self.session.path)

    def save_as(self) -> bool:
        start = self.session.path or os.path.join(
            self.session.last_dir, "diagram" + model.FILE_EXTENSION
        )
        path, _ = QFileDialog.getSaveFileName(self, "Save Energy Diagram", start, FILE_FILTER)
        if not path:
            return False
        return self._write(path)

    def _write(self, path: str) -> bool:
        try:
            self.session.save(path)
        except OSError as exc:
            QMessageBox.warning(self, TITLE, f"Could not save {os.path.basename(path)}:\n{exc}")
            return False
        self._update_title()
        return True

    def export_dialog(self) -> None:
        base = (
            os.path.splitext(self.session.path)[0]
            if self.session.path
            else os.path.join(self.session.last_dir, "diagram")
        )
        filters = ";;".join(
            f"{name} (*{ext})" for ext, name in render.EXPORT_FORMATS.items() if ext != ".tiff"
        )
        path, chosen = QFileDialog.getSaveFileName(self, "Export Image", base + ".png", filters)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += chosen.split("*")[-1].rstrip(")") if "*" in chosen else ".png"
        dpi = 300
        if os.path.splitext(path)[1].lower() not in render.VECTOR_FORMATS:
            dpi, ok = QInputDialog.getInt(
                self, "Export Image", "Resolution (dpi):", 600, 72, 2400, 50
            )
            if not ok:
                return
        self.export(path, dpi)

    def export(self, path: str, dpi: int = 600) -> bool:
        try:
            render.export(self.diagram, path, dpi=dpi)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, TITLE, f"Could not export:\n{exc}")
            return False
        self.statusBar().showMessage(f"Exported {os.path.basename(path)}", 5000)
        return True

    def copy_image(self) -> None:
        image = QImage.fromData(render.png_bytes(self.diagram, dpi=300), "PNG")
        QApplication.clipboard().setImage(image)
        self.statusBar().showMessage("Copied the diagram at 300 dpi.", 4000)

    # ================================================================ close
    def closeEvent(self, event) -> None:
        # The diagram stays in the session (and its autosave); closing the
        # window loses nothing, so nothing is asked here.
        if self._session_changed in self.session.listeners:
            self.session.listeners.remove(self._session_changed)
        super().closeEvent(event)


def loaded_smiles(context) -> str:
    if context is None:
        return ""
    try:
        mol = context.current_molecule
        if mol is None or mol.GetNumAtoms() == 0:
            return ""
        from rdkit import Chem

        copy = Chem.Mol(mol)
        try:
            copy = Chem.RemoveHs(copy)
        except Exception:
            logger.debug("RemoveHs failed; keeping hydrogens", exc_info=True)
        return Chem.MolToSmiles(copy)
    except Exception:
        logger.debug("reading the loaded molecule failed", exc_info=True)
        return ""

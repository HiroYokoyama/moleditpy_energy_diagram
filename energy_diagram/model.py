"""The diagram as data: compounds, pathways of levels, style, and layout.

Pure Python - no Qt, no matplotlib - so every number on the figure can be
tested without drawing it.

Energies are kept in Hartree for compounds (that is what output files give).
A level's energy is an expression: a number in the diagram's input unit, a
compound name, or a sum such as ``cat + sub - 0.5`` or ``2*H2O + {Pd(PPh3)2}``.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any

FILE_FORMAT = "moleditpy-energy-diagram"
FILE_VERSION = 1
FILE_EXTENSION = ".pmeedg"

#: How many of each unit one Hartree is (CODATA 2018).
PER_HARTREE = {
    "Hartree": 1.0,
    "kcal/mol": 627.5094740631,
    "kJ/mol": 2625.4996394799,
    "eV": 27.211386245988,
}
UNITS = list(PER_HARTREE)

#: Draggable item -> the Level field holding its offset.
OFFSETS = {
    "label": "label_offset",
    "energy": "energy_offset",
    "structure": "structure_offset",
    "barrier": "barrier_offset",
}
#: Draggable item -> the Level field that shows or hides it.
SHOWN = {
    "label": "show_label",
    "energy": "show_energy",
    "structure": "show_structure",
    "barrier": "show_barrier",
}

KIND_MIN = "min"
KIND_TS = "ts"

CONNECTORS = ["dashed", "dotted", "solid", "curve", "none"]
ZERO_FIRST = "first"
ZERO_NONE = "none"

DEFAULT_COLORS = ["#1f3a93", "#c0392b", "#1e8449", "#7d3c98", "#b9770e", "#2e4053"]


def convert(value: float, unit_from: str, unit_to: str) -> float:
    return value / PER_HARTREE[unit_from] * PER_HARTREE[unit_to]


class ExpressionError(ValueError):
    """A level's energy cannot be worked out."""


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _from_dict(cls, data: Any):
    """Build a dataclass from a dict, ignoring unknown keys and bad types."""
    if not isinstance(data, dict):
        return cls()
    defaults = cls()
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        default = getattr(defaults, f.name)
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, float) and isinstance(value, (int, float)):
            value = float(value)
        elif isinstance(default, list) and isinstance(value, (list, tuple)):
            value = list(value)
        elif default is not None and not isinstance(value, type(default)):
            continue
        kwargs[f.name] = value
    return cls(**kwargs)


@dataclass
class Compound:
    name: str = ""
    energy: float | None = None  # Hartree
    source: str = ""

    @classmethod
    def from_dict(cls, data):
        out = _from_dict(cls, data)
        energy = data.get("energy") if isinstance(data, dict) else None
        out.energy = float(energy) if isinstance(energy, (int, float)) else None
        return out


@dataclass
class Level:
    label: str = ""
    energy: str = ""
    kind: str = KIND_MIN
    position: float | None = None
    show_label: bool = True
    show_energy: bool = True
    show_structure: bool = True
    show_barrier: bool = True
    color: str = ""
    smiles: str = ""
    # Extra offsets, in points, from where the label/value/structure would
    # sit by default; set by dragging on the figure.
    label_offset: list = field(default_factory=lambda: [0.0, 0.0])
    energy_offset: list = field(default_factory=lambda: [0.0, 0.0])
    structure_offset: list = field(default_factory=lambda: [0.0, 0.0])
    barrier_offset: list = field(default_factory=lambda: [0.0, 0.0])

    @classmethod
    def from_dict(cls, data):
        out = _from_dict(cls, data)
        position = data.get("position") if isinstance(data, dict) else None
        out.position = float(position) if isinstance(position, (int, float)) else None
        if out.kind not in (KIND_MIN, KIND_TS):
            out.kind = KIND_MIN
        for name in OFFSETS.values():
            setattr(out, name, _pair(getattr(out, name)))
        return out


def _pair(value) -> list:
    try:
        x, y = (float(v) for v in value)
    except (TypeError, ValueError):
        return [0.0, 0.0]
    return [x, y]


@dataclass
class Pathway:
    name: str = "Pathway 1"
    color: str = DEFAULT_COLORS[0]
    visible: bool = True
    levels: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        out = _from_dict(cls, data)
        raw = data.get("levels", []) if isinstance(data, dict) else []
        out.levels = [Level.from_dict(item) for item in raw if isinstance(item, dict)]
        return out


@dataclass
class Style:
    input_unit: str = "kcal/mol"
    display_unit: str = "kcal/mol"
    zero: str = ZERO_FIRST
    quantity: str = "ΔG"
    y_label: str = ""  # empty: "<quantity> (<unit>)"
    x_label: str = "Reaction coordinate"
    title: str = ""
    connector: str = "dashed"
    level_width: float = 0.6
    level_linewidth: float = 2.5
    connector_linewidth: float = 1.0
    font_family: str = "Arial"
    font_size: float = 10.0
    label_size: float = 10.0
    energy_size: float = 9.0
    decimals: int = 1
    energy_parentheses: bool = False
    energy_sign: bool = False
    energy_unit_suffix: bool = False
    label_bold: bool = False
    show_barriers: bool = False
    show_structures: bool = False
    structure_size: float = 0.6  # inches
    show_legend: bool = True
    show_y_axis: bool = True
    fig_width: float = 6.0
    fig_height: float = 4.0
    transparent: bool = False

    @classmethod
    def from_dict(cls, data):
        out = _from_dict(cls, data)
        if out.input_unit not in PER_HARTREE:
            out.input_unit = "kcal/mol"
        if out.display_unit not in PER_HARTREE:
            out.display_unit = "kcal/mol"
        if out.zero not in (ZERO_FIRST, ZERO_NONE):
            out.zero = ZERO_FIRST
        if out.connector not in CONNECTORS:
            out.connector = "dashed"
        out.decimals = max(0, min(6, int(out.decimals)))
        return out

    def axis_label(self) -> str:
        return self.y_label or f"{self.quantity} ({self.display_unit})"


@dataclass
class Diagram:
    compounds: list = field(default_factory=list)
    pathways: list = field(default_factory=lambda: [Pathway()])
    style: Style = field(default_factory=Style)
    store_in_project: bool = False

    # ------------------------------------------------------------- files
    def to_dict(self) -> dict:
        return {
            "format": FILE_FORMAT,
            "version": FILE_VERSION,
            "compounds": [asdict(c) for c in self.compounds],
            "pathways": [asdict(p) for p in self.pathways],
            "style": asdict(self.style),
            "store_in_project": self.store_in_project,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Diagram:
        if not isinstance(data, dict) or data.get("format") != FILE_FORMAT:
            raise ValueError("This is not an energy diagram file.")
        version = data.get("version", 1)
        if not isinstance(version, int) or version > FILE_VERSION:
            raise ValueError(
                f"The diagram was written by a newer version of the plugin (format {version})."
            )
        pathways = [Pathway.from_dict(p) for p in data.get("pathways", []) if isinstance(p, dict)]
        return cls(
            compounds=[
                Compound.from_dict(c) for c in data.get("compounds", []) if isinstance(c, dict)
            ],
            pathways=pathways or [Pathway()],
            style=Style.from_dict(data.get("style", {})),
            store_in_project=bool(data.get("store_in_project", False)),
        )

    def is_empty(self) -> bool:
        return not self.compounds and not any(p.levels for p in self.pathways)

    # ---------------------------------------------------------- energies
    def compound_energies(self) -> dict[str, float]:
        return {c.name: c.energy for c in self.compounds if c.name and c.energy is not None}

    def absolute(self, level: Level) -> float:
        """The level's energy in Hartree."""
        return evaluate(level.energy, self.compound_energies(), self.style.input_unit)

    def zero_hartree(self) -> float:
        if self.style.zero == ZERO_NONE:
            return 0.0
        for pathway in self.pathways:
            if not pathway.visible:
                continue
            for level in pathway.levels:
                try:
                    return self.absolute(level)
                except ExpressionError:
                    continue
        return 0.0

    def relative(self, level: Level, zero: float | None = None) -> float:
        """The level's energy on the axis, in the display unit."""
        zero = self.zero_hartree() if zero is None else zero
        return convert(self.absolute(level) - zero, "Hartree", self.style.display_unit)

    def values(self) -> list[list[float | None]]:
        """Every level's axis value (None where it cannot be worked out)."""
        zero = self.zero_hartree()
        out = []
        for pathway in self.pathways:
            row = []
            for level in pathway.levels:
                try:
                    row.append(self.relative(level, zero))
                except ExpressionError:
                    row.append(None)
            out.append(row)
        return out

    def format_energy(self, value: float) -> str:
        style = self.style
        text = (
            f"{value:+.{style.decimals}f}" if style.energy_sign else f"{value:.{style.decimals}f}"
        )
        if text.lstrip("+-").strip("0.") == "" and text.startswith("-"):
            text = text[1:]  # no "-0.0"
        text = text.replace("-", "−")
        if style.energy_unit_suffix:
            text = f"{text} {style.display_unit}"
        if style.energy_parentheses:
            text = f"({text})"
        return text

    def next_color(self) -> str:
        used = {p.color.lower() for p in self.pathways}
        for color in DEFAULT_COLORS:
            if color.lower() not in used:
                return color
        return DEFAULT_COLORS[len(self.pathways) % len(DEFAULT_COLORS)]


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:(?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|\{(?P<braced>[^{}]+)\}"
    r"|(?P<op>[-+*()]))"
)


def _tokens(text: str) -> list[tuple[str, str]]:
    out = []
    pos = 0
    text = text.replace("−", "-")
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise ExpressionError(f"Cannot read {text[pos:].strip()!r}.")
        kind = match.lastgroup
        value = match.group(kind)
        out.append(
            ("name" if kind == "braced" else kind, value.strip() if kind == "braced" else value)
        )
        pos = match.end()
    return out


def evaluate(text: str, compounds: dict[str, float], unit: str) -> float:
    """``text`` in Hartree: numbers are in ``unit``, names are compounds (Hartree)."""
    tokens = _tokens(text or "")
    if not tokens:
        raise ExpressionError("No energy.")
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def expr():
        value = term()
        while peek()[1] in ("+", "-"):
            op = take()[1]
            value = value + term() if op == "+" else value - term()
        return value

    def term():
        value = factor()
        while peek()[1] == "*":
            take()
            value = value * factor()
        return value

    def factor():
        kind, value = peek()
        if kind is None:
            raise ExpressionError("The energy ends too early.")
        if value == "-":
            take()
            return -factor()
        if value == "+":
            take()
            return factor()
        if value == "(":
            take()
            inner = expr()
            if peek()[1] != ")":
                raise ExpressionError("A ')' is missing.")
            take()
            return inner
        if kind == "number":
            take()
            return _Value(number=float(value))
        if kind == "name":
            take()
            if value not in compounds:
                raise ExpressionError(f"No compound named {value!r} with an energy.")
            return _Value(hartree=compounds[value], bare=False)
        raise ExpressionError(f"Unexpected {value!r}.")

    result = expr()
    if pos != len(tokens):
        raise ExpressionError(f"Unexpected {tokens[pos][1]!r}.")
    return result.hartree + convert(result.number, unit, "Hartree")


class _Value:
    """``hartree`` from compounds plus ``number`` in the input unit.

    ``bare`` marks a value built from numbers only, which may scale another
    (``2*H2O``); two compound energies cannot multiply each other.
    """

    def __init__(self, hartree: float = 0.0, number: float = 0.0, bare: bool = True):
        self.hartree = hartree
        self.number = number
        self.bare = bare

    def __add__(self, other):
        return _Value(
            self.hartree + other.hartree, self.number + other.number, self.bare and other.bare
        )

    def __sub__(self, other):
        return self + (-other)

    def __neg__(self):
        return _Value(-self.hartree, -self.number, self.bare)

    def __mul__(self, other):
        if self.bare:
            k, value = self.number, other
        elif other.bare:
            k, value = other.number, self
        else:
            raise ExpressionError("Two energies cannot be multiplied.")
        return _Value(k * value.hartree, k * value.number, value.bare)


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------


@dataclass
class LevelGeometry:
    pathway: int
    index: int
    x: float
    x0: float
    x1: float
    y: float
    kind: str
    color: str


BARRIER_GAP = 0.08  # data units right of the TS bar
BARRIER_LANE = 0.12  # further right for each later pathway


@dataclass
class Layout:
    levels: list
    connectors: list  # (pathway index, [(x, y), ...])
    barriers: list  # (pathway index, level index, arrow x, y_from, y_to, guide start x)
    x_range: tuple
    y_range: tuple


def layout(diagram: Diagram, curve_points: int = 40) -> Layout:
    """Where every bar, connector and barrier arrow goes, in data coordinates."""
    style = diagram.style
    values = diagram.values()
    half = max(0.05, style.level_width) / 2
    levels: list[LevelGeometry] = []
    connectors = []
    barriers = []
    lane = 0
    for p_index, pathway in enumerate(diagram.pathways):
        if not pathway.visible:
            continue
        placed: list[LevelGeometry] = []
        for i, level in enumerate(pathway.levels):
            y = values[p_index][i]
            if y is None:
                continue
            x = level.position if level.position is not None else float(i)
            width = 0.0 if (style.connector == "curve" and level.kind == KIND_TS) else half
            geometry = LevelGeometry(
                p_index, i, x, x - width, x + width, y, level.kind, level.color or pathway.color
            )
            placed.append(geometry)
        levels.extend(placed)
        for a, b in zip(placed, placed[1:]):
            if style.connector == "none":
                continue
            if style.connector == "curve":
                points = []
                for k in range(curve_points + 1):
                    t = k / curve_points
                    s = (1 - math.cos(math.pi * t)) / 2
                    points.append((a.x1 + (b.x0 - a.x1) * t, a.y + (b.y - a.y) * s))
            else:
                points = [(a.x1, a.y), (b.x0, b.y)]
            connectors.append((p_index, points))
        if style.show_barriers:
            # Beside the TS bar rather than through it, so the arrow never
            # crosses the TS value; each pathway gets its own lane.
            arrow_dx = BARRIER_GAP + BARRIER_LANE * lane
            for a, b in zip(placed, placed[1:]):
                if b.kind == KIND_TS and a.kind != KIND_TS:
                    barriers.append((p_index, b.index, b.x1 + arrow_dx, a.y, b.y, a.x1))
        lane += 1
    if levels:
        xs = [g.x0 for g in levels] + [g.x1 for g in levels]
        ys = [g.y for g in levels]
        x_range = (min(xs) - 0.5, max(xs) + 0.5)
        span = (max(ys) - min(ys)) or 10.0
        y_range = (min(ys) - 0.22 * span, max(ys) + 0.22 * span)
    else:
        x_range, y_range = (-0.5, 0.5), (-1.0, 1.0)
    return Layout(levels, connectors, barriers, x_range, y_range)

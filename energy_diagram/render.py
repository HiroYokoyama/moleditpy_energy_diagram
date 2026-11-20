"""Draw a Diagram onto a matplotlib Figure, and export it.

Labels, energies, structures and barrier values are annotations placed at an
offset (in points) from their level, so dragging one changes only that
offset and the figure looks the same at any export size or resolution.

The quantity symbol is written with matplotlib's math text so its letters
can be italic (Δ*G*, Δ*G*‡) while Δ stays upright. Math text takes its fonts
from rcParams at drawing time, so everything that draws a diagram does it
inside ``rc_context(math_rc(style))``.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import matplotlib
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.ticker import AutoLocator, MultipleLocator

from . import model

logger = logging.getLogger(__name__)

EXPORT_FORMATS = {
    ".png": "PNG image",
    ".svg": "SVG vector image",
    ".pdf": "PDF document",
    ".tif": "TIFF image",
    ".tiff": "TIFF image",
    ".eps": "EPS vector image",
}
VECTOR_FORMATS = {".svg", ".pdf", ".eps"}
CONNECTOR_STYLES = {"dashed": (0, (4, 3)), "dotted": (0, (1, 2)), "solid": "-", "curve": "-"}
FALLBACK_FONT = "DejaVu Sans"
# Kept for callers that read the default gap.
GAP = model.Style().text_gap
MAX_TICKS = 40


@dataclass
class Draggable:
    artist: object
    item: str  # a key of model.OFFSETS
    pathway: int
    index: int
    base: tuple  # default offset in points, before the user's own

    def offset(self) -> tuple:
        if isinstance(self.artist, AnnotationBbox):
            return tuple(self.artist.xybox)
        return tuple(self.artist.xyann)

    def set_offset(self, x: float, y: float) -> None:
        if isinstance(self.artist, AnnotationBbox):
            self.artist.xybox = (x, y)
        else:
            self.artist.xyann = (x, y)

    def contains(self, event) -> bool:
        return bool(self.artist.contains(event)[0])


@dataclass
class Rendered:
    axes: object
    draggables: list
    bars: dict  # artist -> (pathway, index)


_structure_cache: dict = {}


def structure_image(smiles: str):
    """An RGBA array of the 2D structure, or None if it cannot be drawn."""
    if smiles in _structure_cache:
        return _structure_cache[smiles]
    image = None
    try:
        from matplotlib import image as mpimg
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D

        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            drawer = rdMolDraw2D.MolDraw2DCairo(300, 300)
            options = drawer.drawOptions()
            options.clearBackground = False
            options.padding = 0.05
            drawer.DrawMolecule(mol)
            drawer.FinishDrawing()
            image = mpimg.imread(io.BytesIO(drawer.GetDrawingText()), format="png")
    except Exception:  # rdkit without Cairo, or an odd SMILES
        logger.debug("structure image for %r failed", smiles, exc_info=True)
        image = None
    _structure_cache[smiles] = image
    return image


# ------------------------------------------------------------------- text


def _pattern(family: str) -> str:
    """A font name as a fontconfig pattern, which gives '-' and ':' a meaning."""
    return re.sub(r"([-:\\])", r"\\\1", family)


def math_rc(style: model.Style) -> dict:
    """rcParams that make math text use the main font, with true italics."""
    family = _pattern(style.font_family or FALLBACK_FONT)
    return {
        "mathtext.fontset": "custom",
        "mathtext.rm": family,
        "mathtext.it": f"{family}:italic",
        "mathtext.bf": f"{family}:bold",
        "mathtext.sf": family,
        "mathtext.fallback": "stixsans",
    }


def symbol(quantity: str, italic: bool, dagger: bool = False) -> str:
    """The quantity as math text: Latin letters italic, Δ and the rest upright."""
    if "$" in quantity:
        # The user wrote their own math text; take it as it is.
        return quantity + (r"$^{\ddag}$" if dagger else "")
    parts = re.split(r"([A-Za-z]+)", quantity) if italic else [quantity]
    out = []
    for i, part in enumerate(parts):
        if not part:
            continue
        out.append(f"$\\mathit{{{part}}}$" if italic and i % 2 == 1 else part)
    text = "".join(out)
    if dagger:
        if text.endswith("}$"):
            text = text[:-1] + r"^{\ddag}$"
        else:
            text += r"$^{\ddag}$"
    return text


def axis_title(style: model.Style) -> str:
    if style.y_label:
        return style.y_label
    return f"{symbol(style.quantity, style.quantity_italic)} ({style.display_unit})"


def _family(style: model.Style, role: str) -> list:
    """The role's font, then the main font, then one that always exists.

    The main font is always in the list: math text inside this text uses it,
    and matplotlib caches laid-out math text by these properties.
    """
    families = [getattr(style, f"{role}_font"), style.font_family, FALLBACK_FONT]
    out = []
    for family in families:
        if family and family not in out:
            out.append(family)
    return out


def _color(style: model.Style, name: str, pathway_color: str) -> str:
    value = getattr(style, name)
    return pathway_color if value == model.PATHWAY_COLOR else value


def text_style(style: model.Style, role: str, pathway_color: str = "#000000") -> dict:
    """Keyword arguments for a matplotlib Text in the role's style."""
    return {
        "fontsize": getattr(style, f"{role}_size"),
        "fontfamily": _family(style, role),
        "fontweight": "bold" if getattr(style, f"{role}_bold") else "normal",
        "fontstyle": "italic" if getattr(style, f"{role}_italic") else "normal",
        "color": _color(style, f"{role}_color", pathway_color),
    }


def font_properties(style: model.Style, role: str) -> FontProperties:
    kw = text_style(style, role)
    return FontProperties(
        family=kw["fontfamily"], size=kw["fontsize"], weight=kw["fontweight"], style=kw["fontstyle"]
    )


# ----------------------------------------------------------------- drawing


def render(diagram: model.Diagram, figure) -> Rendered:
    """Clear ``figure`` and draw the diagram on it."""
    with matplotlib.rc_context(math_rc(diagram.style)):
        return _render(diagram, figure)


def _render(diagram: model.Diagram, figure) -> Rendered:
    style = diagram.style
    geometry = model.layout(diagram)
    gap = style.text_gap
    figure.clear()
    figure.set_size_inches(style.fig_width, style.fig_height)
    figure.patch.set_facecolor(style.background)
    figure.patch.set_alpha(0.0 if style.transparent else 1.0)
    ax = figure.add_subplot(111)
    ax.patch.set_facecolor(style.background)
    ax.patch.set_alpha(0.0 if style.transparent else 1.0)
    draggables: list[Draggable] = []
    bars: dict = {}

    for p_index, points in geometry.connectors:
        pathway = diagram.pathways[p_index]
        xs, ys = zip(*points)
        ax.plot(
            xs,
            ys,
            color=_color(style, "connector_color", pathway.color),
            linewidth=style.connector_linewidth,
            linestyle=CONNECTOR_STYLES.get(style.connector, "-"),
            zorder=1,
        )

    structure_points = style.structure_size * 72.0
    for g in geometry.levels:
        level = diagram.pathways[g.pathway].levels[g.index]
        if g.x1 > g.x0:
            (bar,) = ax.plot(
                [g.x0, g.x1],
                [g.y, g.y],
                color=g.color,
                linewidth=style.level_linewidth,
                solid_capstyle="butt",
                zorder=3,
                picker=6,
            )
        else:
            # A transition state drawn as the top of a curve has no bar; a
            # marker of zero size still lets a click find it.
            (bar,) = ax.plot([g.x], [g.y], marker="o", markersize=0, zorder=3, picker=6)
        bars[bar] = (g.pathway, g.index)

        peak = g.x1 <= g.x0  # a curve's transition state: nothing below it
        energy_base = (0.0, gap) if peak else (0.0, -gap)
        label_lift = gap + (style.energy_size * 1.35 if peak and level.show_energy else 0.0)
        if level.show_label and level.label:
            base = (0.0, label_lift)
            text = ax.annotate(
                level.label,
                xy=(g.x, g.y),
                xytext=_plus(base, level.label_offset),
                textcoords="offset points",
                ha="center",
                va="bottom",
                zorder=5,
                **text_style(style, "label", g.color),
            )
            draggables.append(Draggable(text, "label", g.pathway, g.index, base))
        if level.show_energy:
            base = energy_base
            text = ax.annotate(
                diagram.format_energy(g.y),
                xy=(g.x, g.y),
                xytext=_plus(base, level.energy_offset),
                textcoords="offset points",
                ha="center",
                va="bottom" if peak else "top",
                zorder=5,
                **text_style(style, "energy", g.color),
            )
            draggables.append(Draggable(text, "energy", g.pathway, g.index, base))
        if style.show_structures and level.show_structure and level.smiles:
            image = structure_image(level.smiles)
            if image is not None:
                zoom = structure_points / 72.0 * figure.dpi / image.shape[1]
                lift = label_lift + style.label_size * 1.6 + structure_points / 2
                base = (0.0, lift)
                box = AnnotationBbox(
                    OffsetImage(image, zoom=zoom),
                    (g.x, g.y),
                    xybox=_plus(base, level.structure_offset),
                    boxcoords="offset points",
                    frameon=False,
                    pad=0.0,
                    zorder=4,
                )
                ax.add_artist(box)
                draggables.append(Draggable(box, "structure", g.pathway, g.index, base))

    for p_index, index, x, y_from, y_to, x_from in geometry.barriers:
        level = diagram.pathways[p_index].levels[index]
        if not level.show_barrier:
            continue
        color = level.color or diagram.pathways[p_index].color
        if style.barrier_guide:
            # A dotted guide carries the reference minimum across to the arrow.
            ax.plot(
                [x_from, x],
                [y_from, y_from],
                linestyle=":",
                linewidth=0.7,
                color=color,
                solid_capstyle="butt",
                zorder=1,
            )
        ax.annotate(
            "",
            xy=(x, y_to),
            xytext=(x, y_from),
            arrowprops={
                "arrowstyle": style.barrier_arrow,
                "color": color,
                "linewidth": style.barrier_linewidth,
                "shrinkA": 0,
                "shrinkB": 0,
            },
            zorder=2,
        )
        value = diagram.format_energy(y_to - y_from)
        if style.barrier_symbol:
            value = f"{symbol(style.quantity, style.quantity_italic, dagger=True)} = {value}"
        base = (6.0, 0.0)
        text = ax.annotate(
            value,
            xy=(x, (y_from + y_to) / 2),
            xytext=_plus(base, level.barrier_offset),
            textcoords="offset points",
            ha="left",
            va="center",
            zorder=5,
            **text_style(style, "barrier", color),
        )
        draggables.append(Draggable(text, "barrier", p_index, index, base))

    ax.set_xlim(*geometry.x_range)
    if style.y_fixed and style.y_max > style.y_min:
        low, high = style.y_min, style.y_max
    else:
        low, high = geometry.y_range
        if style.show_structures and any(d.item == "structure" for d in draggables):
            # Room above the highest level for its drawing.
            high += (high - low) * 0.25
    ax.set_ylim(low, high)
    _axes(ax, style, low, high)
    _legend(ax, diagram)
    figure.tight_layout()
    return Rendered(ax, draggables, bars)


def _axes(ax, style: model.Style, low: float, high: float) -> None:
    ax.set_xticks([])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side, shown in (("left", style.show_y_axis), ("bottom", style.show_x_axis)):
        spine = ax.spines[side]
        spine.set_visible(shown)
        spine.set_linewidth(style.axis_linewidth)
        spine.set_color(style.axis_line_color)
    title = text_style(style, "axis")
    if style.show_y_axis:
        ax.set_ylabel(axis_title(style), **title)
        ax.set_yticks(ticks(style, low, high))
        tick = text_style(style, "tick")
        labels = [f"{v:g}".replace("-", "−") for v in ax.get_yticks()]
        ax.set_yticklabels(labels, **tick)
        ax.tick_params(
            axis="y",
            direction=style.tick_direction,
            width=style.axis_linewidth,
            color=style.axis_line_color,
        )
    else:
        ax.set_yticks([])
    if style.x_label:
        ax.set_xlabel(style.x_label, **title)
    if style.title:
        ax.set_title(style.title, **text_style(style, "title"))


def ticks(style: model.Style, low: float, high: float) -> list:
    """Tick positions inside the axis range, every ``y_step`` if one is set."""
    step = style.y_step
    if step > 0 and (high - low) / step <= MAX_TICKS:
        values = MultipleLocator(step).tick_values(low, high)
    else:
        values = AutoLocator().tick_values(low, high)
    span = high - low
    return [float(v) for v in values if low - 1e-9 * span <= v <= high + 1e-9 * span]


def _legend(ax, diagram: model.Diagram) -> None:
    style = diagram.style
    visible = [p for p in diagram.pathways if p.visible and p.levels]
    if not (style.show_legend and len(visible) > 1):
        return
    handles = [Line2D([], [], color=p.color, linewidth=style.level_linewidth) for p in visible]
    ax.legend(
        handles,
        [p.name for p in visible],
        loc=style.legend_location,
        frameon=style.legend_frame,
        prop=font_properties(style, "legend"),
        labelcolor=style.legend_color,
    )


def _plus(base, extra) -> tuple:
    return (base[0] + float(extra[0]), base[1] + float(extra[1]))


def _save(diagram: model.Diagram, target, dpi: int, **kwargs) -> None:
    from matplotlib.figure import Figure

    style = diagram.style
    # Text stays text in vector files, so it can still be edited afterwards.
    rc = {"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42, **math_rc(style)}
    with matplotlib.rc_context(rc):
        figure = Figure()
        _render(diagram, figure)
        figure.savefig(
            target,
            dpi=dpi,
            transparent=style.transparent,
            facecolor="none" if style.transparent else style.background,
            **kwargs,
        )


def export(diagram: model.Diagram, path: str, dpi: int = 300) -> None:
    """Write the diagram to ``path``; the extension picks the format."""
    import os

    ext = os.path.splitext(path)[1].lower()
    if ext not in EXPORT_FORMATS:
        raise ValueError(f"Cannot export to {ext or 'a file without an extension'}.")
    _save(diagram, path, dpi)


def png_bytes(diagram: model.Diagram, dpi: int = 300) -> bytes:
    buffer = io.BytesIO()
    _save(diagram, buffer, dpi, format="png")
    return buffer.getvalue()

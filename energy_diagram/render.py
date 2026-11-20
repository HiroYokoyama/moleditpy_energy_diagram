"""Draw a Diagram onto a matplotlib Figure, and export it.

Labels, energies, structures and barrier values are annotations placed at an
offset (in points) from their level, so dragging one changes only that
offset and the figure looks the same at any export size or resolution.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import matplotlib
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

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
# Gap, in points, between a bar and its label/value.
GAP = 3.0
CONNECTOR_STYLES = {"dashed": (0, (4, 3)), "dotted": (0, (1, 2)), "solid": "-", "curve": "-"}


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


def _font(style: model.Style) -> list:
    return [style.font_family, "DejaVu Sans"] if style.font_family else ["DejaVu Sans"]


def render(diagram: model.Diagram, figure) -> Rendered:
    """Clear ``figure`` and draw the diagram on it."""
    style = diagram.style
    geometry = model.layout(diagram)
    family = _font(style)
    figure.clear()
    figure.set_size_inches(style.fig_width, style.fig_height)
    figure.patch.set_alpha(0.0 if style.transparent else 1.0)
    ax = figure.add_subplot(111)
    ax.patch.set_alpha(0.0 if style.transparent else 1.0)
    draggables: list[Draggable] = []
    bars: dict = {}

    for p_index, points in geometry.connectors:
        pathway = diagram.pathways[p_index]
        xs, ys = zip(*points)
        ax.plot(
            xs,
            ys,
            color=pathway.color,
            linewidth=style.connector_linewidth,
            linestyle=CONNECTOR_STYLES.get(style.connector, "-"),
            zorder=1,
        )

    weight = "bold" if style.label_bold else "normal"
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
        energy_base = (0.0, GAP) if peak else (0.0, -GAP)
        label_lift = GAP + (style.energy_size * 1.35 if peak and level.show_energy else 0.0)
        if level.show_label and level.label:
            base = (0.0, label_lift)
            text = ax.annotate(
                level.label,
                xy=(g.x, g.y),
                xytext=_plus(base, level.label_offset),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=style.label_size,
                fontfamily=family,
                fontweight=weight,
                color=level.color or "black",
                zorder=5,
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
                fontsize=style.energy_size,
                fontfamily=family,
                color=g.color,
                zorder=5,
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
                "arrowstyle": "<->",
                "color": color,
                "linewidth": 0.9,
                "shrinkA": 0,
                "shrinkB": 0,
            },
            zorder=2,
        )
        value = diagram.format_energy(y_to - y_from)
        base = (6.0, 0.0)
        text = ax.annotate(
            f"{style.quantity}‡ = {value}",
            xy=(x, (y_from + y_to) / 2),
            xytext=_plus(base, level.barrier_offset),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=style.energy_size,
            fontfamily=family,
            color=color,
            zorder=5,
        )
        draggables.append(Draggable(text, "barrier", p_index, index, base))

    ax.set_xlim(*geometry.x_range)
    low, high = geometry.y_range
    if style.show_structures and any(d.item == "structure" for d in draggables):
        # Room above the highest level for its drawing.
        high += (high - low) * 0.25
    ax.set_ylim(low, high)
    ax.set_xticks([])
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    if style.show_y_axis:
        ax.set_ylabel(style.axis_label(), fontsize=style.font_size, fontfamily=family)
        ax.tick_params(axis="y", labelsize=style.font_size)
        for tick in ax.get_yticklabels():
            tick.set_fontfamily(family)
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}".replace("-", "−"))
        )
    else:
        ax.spines["left"].set_visible(False)
        ax.set_yticks([])
    if style.x_label:
        ax.set_xlabel(style.x_label, fontsize=style.font_size, fontfamily=family)
    if style.title:
        ax.set_title(style.title, fontsize=style.font_size + 1, fontfamily=family)
    visible = [p for p in diagram.pathways if p.visible and p.levels]
    if style.show_legend and len(visible) > 1:
        handles = [Line2D([], [], color=p.color, linewidth=style.level_linewidth) for p in visible]
        ax.legend(
            handles,
            [p.name for p in visible],
            frameon=False,
            prop={"family": family, "size": style.font_size},
        )
    figure.tight_layout()
    return Rendered(ax, draggables, bars)


def _plus(base, extra) -> tuple:
    return (base[0] + float(extra[0]), base[1] + float(extra[1]))


def export(diagram: model.Diagram, path: str, dpi: int = 300) -> None:
    """Write the diagram to ``path``; the extension picks the format."""
    import os

    from matplotlib.figure import Figure

    ext = os.path.splitext(path)[1].lower()
    if ext not in EXPORT_FORMATS:
        raise ValueError(f"Cannot export to {ext or 'a file without an extension'}.")
    # Text stays text in vector files, so it can still be edited afterwards.
    with matplotlib.rc_context({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42}):
        figure = Figure()
        render(diagram, figure)
        figure.savefig(
            path,
            dpi=dpi,
            transparent=diagram.style.transparent,
            facecolor="none" if diagram.style.transparent else "white",
        )


def png_bytes(diagram: model.Diagram, dpi: int = 300) -> bytes:
    from matplotlib.figure import Figure

    figure = Figure()
    render(diagram, figure)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi, transparent=diagram.style.transparent)
    return buffer.getvalue()

"""Drawing with matplotlib's Agg backend, and every export format."""

import pytest

pytest.importorskip("matplotlib")

from matplotlib.figure import Figure

from energy_diagram import model, render


def sample(**style):
    d = model.Diagram()
    d.pathways[0].levels = [
        model.Level("R", "0"),
        model.Level("TS", "20", kind=model.KIND_TS),
        model.Level("P", "-10"),
    ]
    for key, value in style.items():
        setattr(d.style, key, value)
    return d


def texts(rendered, item):
    return [d.artist.get_text() for d in rendered.draggables if d.item == item]


def test_every_level_gets_a_bar_label_and_value():
    rendered = render.render(sample(), Figure())
    assert len(rendered.bars) == 3
    assert texts(rendered, "label") == ["R", "TS", "P"]
    assert texts(rendered, "energy") == ["0.0", "20.0", "−10.0"]


def test_hidden_items_are_not_drawn():
    d = sample()
    d.pathways[0].levels[1].show_label = False
    d.pathways[0].levels[2].show_energy = False
    rendered = render.render(d, Figure())
    assert texts(rendered, "label") == ["R", "P"]
    assert texts(rendered, "energy") == ["0.0", "20.0"]


def test_offsets_move_items_from_their_default_place():
    d = sample()
    d.pathways[0].levels[0].label_offset = [10.0, 5.0]
    rendered = render.render(d, Figure())
    label = next(x for x in rendered.draggables if x.item == "label" and x.index == 0)
    assert label.offset() == (10.0, render.GAP + 5.0)
    label.set_offset(1.0, 2.0)
    assert label.artist.xyann == (1.0, 2.0)


def test_curve_ts_puts_the_value_above_the_peak():
    rendered = render.render(sample(connector="curve"), Figure())
    ts_value = next(x for x in rendered.draggables if x.item == "energy" and x.index == 1)
    ts_label = next(x for x in rendered.draggables if x.item == "label" and x.index == 1)
    assert ts_value.base[1] > 0 and ts_label.base[1] > ts_value.base[1]


def test_barriers_are_labelled_with_the_quantity():
    rendered = render.render(sample(show_barriers=True), Figure())
    assert texts(rendered, "barrier") == [r"Δ$\mathit{G}^{\ddag}$ = 20.0"]
    rendered = render.render(sample(show_barriers=True, barrier_symbol=False), Figure())
    assert texts(rendered, "barrier") == ["20.0"]


@pytest.mark.parametrize(
    ("quantity", "italic", "dagger", "expected"),
    [
        ("ΔG", True, False, r"Δ$\mathit{G}$"),
        ("ΔG", True, True, r"Δ$\mathit{G}^{\ddag}$"),
        ("ΔG", False, True, r"ΔG$^{\ddag}$"),
        ("ΔE (ZPE)", True, False, r"Δ$\mathit{E}$ ($\mathit{ZPE}$)"),
        ("ΔG°", True, True, r"Δ$\mathit{G}$°$^{\ddag}$"),
        ("Δ$G_{solv}$", True, True, r"Δ$G_{solv}$$^{\ddag}$"),  # the user's own math text
    ],
)
def test_the_quantity_symbol(quantity, italic, dagger, expected):
    assert render.symbol(quantity, italic, dagger) == expected


def test_the_axis_title_uses_the_italic_symbol_unless_written_out():
    style = model.Style()
    assert render.axis_title(style) == r"Δ$\mathit{G}$ (kcal/mol)"
    style.quantity_italic = False
    assert render.axis_title(style) == "ΔG (kcal/mol)"
    style.y_label = "Relative energy"
    assert render.axis_title(style) == "Relative energy"


def test_each_text_takes_its_own_style():
    d = sample(
        show_barriers=True, label_italic=True, label_font="Times New Roman", energy_bold=True
    )
    d.style.label_color = model.PATHWAY_COLOR
    d.style.energy_color = "#123456"
    d.style.barrier_size = 14.0
    rendered = render.render(d, Figure())
    label = next(x.artist for x in rendered.draggables if x.item == "label")
    value = next(x.artist for x in rendered.draggables if x.item == "energy")
    barrier = next(x.artist for x in rendered.draggables if x.item == "barrier")
    assert label.get_fontstyle() == "italic"
    assert label.get_fontfamily()[:2] == ["Times New Roman", "Arial"]
    assert label.get_color() == d.pathways[0].color
    assert value.get_fontweight() == "bold" and value.get_color() == "#123456"
    assert barrier.get_fontsize() == 14.0 and barrier.get_color() == d.pathways[0].color


def test_axes_range_ticks_and_lines():
    d = sample(y_fixed=True, y_min=-40.0, y_max=40.0, y_step=20.0, show_x_axis=True)
    d.style.axis_line_color = "#ff0000"
    d.style.tick_italic = True
    d.style.tick_direction = "in"
    rendered = render.render(d, Figure())
    ax = rendered.axes
    assert ax.get_ylim() == (-40.0, 40.0)
    assert list(ax.get_yticks()) == [-40.0, -20.0, 0.0, 20.0, 40.0]
    assert [t.get_text() for t in ax.get_yticklabels()] == ["−40", "−20", "0", "20", "40"]
    assert all(t.get_fontstyle() == "italic" for t in ax.get_yticklabels())
    assert ax.spines["bottom"].get_visible()
    assert ax.spines["left"].get_edgecolor()[:3] == (1.0, 0.0, 0.0)
    assert ax.yaxis.get_major_ticks()[0]._tickdir == "in"


def test_a_tick_step_too_fine_falls_back_to_automatic():
    assert len(render.ticks(model.Style(y_step=0.001), -30, 30)) < render.MAX_TICKS


def test_titles_legend_and_background():
    from matplotlib.colors import to_hex

    d = sample(title="Profile", title_bold=True, legend_location="lower left", legend_frame=True)
    d.style.background = "#eeeeee"
    d.style.legend_color = "#00ff00"
    d.pathways.append(model.Pathway(name="B", color="#ff0000", levels=[model.Level("", "5")]))
    figure = Figure()
    rendered = render.render(d, figure)
    assert rendered.axes.title.get_fontweight() == "bold"
    legend = rendered.axes.get_legend()
    assert legend._loc == 3 and legend.get_frame_on()
    assert to_hex(legend.get_texts()[0].get_color()) == "#00ff00"
    assert figure.patch.get_facecolor()[:3] == pytest.approx((0.933, 0.933, 0.933), abs=1e-3)


def test_barrier_arrow_and_guide_settings():
    from matplotlib.text import Annotation

    def arrows(**style):
        rendered = render.render(sample(show_barriers=True, **style), Figure())
        ax = rendered.axes
        found = [a for a in ax.texts if isinstance(a, Annotation) and a.arrow_patch is not None]
        guides = [line for line in ax.lines if line.get_linestyle() == ":"]
        return found, guides

    found, guides = arrows()
    assert len(found) == 1 and len(guides) == 1
    found, guides = arrows(barrier_arrow="->", barrier_guide=False, barrier_linewidth=2.0)
    assert guides == [] and found[0].arrow_patch.get_linewidth() == pytest.approx(2.0)


def test_math_text_is_drawn_in_the_main_font(tmp_path):
    """The italic G comes from the main font, not matplotlib's own math font."""
    import matplotlib

    path = tmp_path / "d.svg"
    render.export(sample(show_barriers=True, font_family="DejaVu Serif"), str(path))
    svg = path.read_text(encoding="utf-8")
    assert "DejaVu Serif" in svg and "italic" in svg
    # Rendering leaves the global settings alone.
    assert matplotlib.rcParams["mathtext.fontset"] != "custom"


def test_structures_need_rdkit_and_a_smiles():
    pytest.importorskip("rdkit")
    d = sample(show_structures=True)
    d.pathways[0].levels[0].smiles = "C=CC=C"
    d.pathways[0].levels[2].smiles = "not a smiles"
    rendered = render.render(d, Figure())
    assert [(x.item, x.index) for x in rendered.draggables if x.item == "structure"] == [
        ("structure", 0)
    ]


def test_figure_size_title_legend_and_axis():
    d = sample(fig_width=3.5, fig_height=2.5, title="Profile", show_y_axis=False)
    assert d.style.legend_location == "best"
    d.pathways.append(model.Pathway(name="B", color="#ff0000", levels=[model.Level("", "5")]))
    figure = Figure()
    rendered = render.render(d, figure)
    assert tuple(figure.get_size_inches()) == (3.5, 2.5)
    assert rendered.axes.get_title() == "Profile"
    assert [t.get_text() for t in rendered.axes.get_legend().get_texts()] == ["Pathway 1", "B"]
    assert not rendered.axes.spines["left"].get_visible()


def test_an_empty_diagram_still_draws():
    rendered = render.render(model.Diagram(), Figure())
    assert rendered.bars == {}


@pytest.mark.parametrize("ext", [".png", ".svg", ".pdf", ".tif", ".eps"])
def test_export_formats(tmp_path, ext):
    path = tmp_path / f"diagram{ext}"
    render.export(sample(show_barriers=True), str(path), dpi=120)
    data = path.read_bytes()
    assert len(data) > 500
    if ext == ".svg":
        # Text stays text, so it can be edited in a drawing program.
        assert b"<text" in data or b">TS<" in data


def test_export_size_follows_the_figure_and_dpi(tmp_path):
    from matplotlib import image

    path = tmp_path / "d.png"
    render.export(sample(fig_width=4.0, fig_height=3.0), str(path), dpi=150)
    assert image.imread(str(path)).shape[:2] == (450, 600)


def test_unknown_export_format_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Cannot export to .doc"):
        render.export(sample(), str(tmp_path / "d.doc"))


def test_png_bytes_and_transparency():
    data = render.png_bytes(sample(transparent=True), dpi=72)
    assert data.startswith(b"\x89PNG")

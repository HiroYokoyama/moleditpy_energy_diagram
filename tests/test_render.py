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
    assert texts(rendered, "barrier") == ["ΔG‡ = 20.0"]


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

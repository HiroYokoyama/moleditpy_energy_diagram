"""Energies, units, expressions, layout and the file format; no Qt, no drawing."""

import json
import math

import pytest

from energy_diagram import model

KCAL = model.PER_HARTREE["kcal/mol"]


def diagram(*energies, unit="kcal/mol", kinds=None):
    d = model.Diagram()
    d.style.input_unit = unit
    kinds = kinds or [model.KIND_MIN] * len(energies)
    d.pathways[0].levels = [
        model.Level(label=f"L{i}", energy=str(e), kind=k)
        for i, (e, k) in enumerate(zip(energies, kinds))
    ]
    return d


@pytest.mark.parametrize(
    ("text", "hartree"),
    [
        ("A + B", -150.0),
        ("2*B", -100.0),
        ("B*2", -100.0),
        ("-(A)", 100.0),
        ("{A} - B", -50.0),
        ("A + B + 1.5", -150.0 + 1.5 / KCAL),
        ("-3.2", -3.2 / KCAL),
        ("1e1", 10.0 / KCAL),
        ("A − B", -50.0),
    ],
)
def test_expressions(text, hartree):
    assert model.evaluate(text, {"A": -100.0, "B": -50.0}, "kcal/mol") == pytest.approx(hartree)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("A*B", "cannot be multiplied"),
        ("(A", "is missing"),
        ("Q", "No compound named 'Q'"),
        ("1 2", "Unexpected '2'"),
        ("", "No energy"),
        ("A +", "ends too early"),
        ("A $ B", "Cannot read"),
    ],
)
def test_expression_errors(text, message):
    with pytest.raises(model.ExpressionError, match=message):
        model.evaluate(text, {"A": -100.0, "B": -50.0}, "Hartree")


def test_braces_name_anything():
    assert model.evaluate("{Pd(PPh3)2 + L}", {"Pd(PPh3)2 + L": -5.0}, "Hartree") == -5.0


def test_units_round_trip():
    for unit in model.UNITS:
        assert model.convert(
            model.convert(1.234, unit, "Hartree"), "Hartree", unit
        ) == pytest.approx(1.234)
    assert model.convert(1.0, "Hartree", "kJ/mol") == pytest.approx(2625.4996394799)
    assert model.convert(1.0, "eV", "kcal/mol") == pytest.approx(23.0605, abs=1e-4)


def test_values_are_relative_to_the_first_level():
    d = diagram(10, 34.6, 2)
    assert d.values() == [[0.0, pytest.approx(24.6), pytest.approx(-8.0)]]
    d.style.zero = model.ZERO_NONE
    assert d.values() == [[10.0, pytest.approx(34.6), 2.0]]
    d.style.display_unit = "kJ/mol"
    assert d.values()[0][0] == pytest.approx(41.84, abs=1e-3)


def test_compounds_in_hartree_and_bad_levels_are_none():
    d = model.Diagram(
        compounds=[model.Compound("A", -100.0), model.Compound("B", -100.01), model.Compound("x")]
    )
    d.pathways[0].levels = [
        model.Level(energy="A"),
        model.Level(energy="B"),
        model.Level(energy="x"),
        model.Level(energy=""),
    ]
    values = d.values()[0]
    assert values[0] == 0.0
    assert values[1] == pytest.approx(-0.01 * KCAL)
    assert values[2] is None and values[3] is None


def test_the_zero_skips_hidden_pathways_and_bad_first_levels():
    d = diagram(5, 10)
    d.pathways[0].levels.insert(0, model.Level(energy="nope"))
    other = model.Pathway(name="b", levels=[model.Level(energy="100")], visible=False)
    d.pathways.insert(0, other)
    assert d.values()[1][1:] == [0.0, 5.0]


def test_format_energy_options():
    d = diagram(0)
    assert d.format_energy(-3.456) == "−3.5"
    assert d.format_energy(-0.04) == "0.0"
    d.style.decimals = 2
    d.style.energy_sign = True
    d.style.energy_parentheses = True
    d.style.energy_unit_suffix = True
    assert d.format_energy(3.456) == "(+3.46 kcal/mol)"


def test_layout_positions_bars_and_connectors():
    d = diagram(0, 20, -5, kinds=[model.KIND_MIN, model.KIND_TS, model.KIND_MIN])
    d.pathways[0].levels[2].position = 3.0
    geometry = model.layout(d)
    assert [(g.x, g.x0, g.x1) for g in geometry.levels] == [
        (0.0, -0.3, 0.3),
        (1.0, 0.7, 1.3),
        (3.0, 2.7, 3.3),
    ]
    assert [points for _, points in geometry.connectors] == [
        [(0.3, 0.0), (0.7, 20.0)],
        [(1.3, 20.0), (2.7, -5.0)],
    ]
    assert geometry.x_range == (-0.8, 3.8)
    assert geometry.y_range[0] < -5 and geometry.y_range[1] > 20


def test_curve_layout_makes_a_smooth_hill_through_the_ts():
    d = diagram(0, 20, -5, kinds=[model.KIND_MIN, model.KIND_TS, model.KIND_MIN])
    d.style.connector = "curve"
    geometry = model.layout(d, curve_points=10)
    ts = geometry.levels[1]
    assert ts.x0 == ts.x1 == 1.0
    up = geometry.connectors[0][1]
    assert up[0] == (0.3, 0.0) and up[-1] == (1.0, 20.0)
    # Flat at both ends: a cosine ease, not a straight line.
    assert up[1][1] < 20 * 0.1 and up[-2][1] > 20 * 0.9


def test_barriers_from_the_minimum_before_each_ts():
    d = diagram(0, 20, -5, 12, kinds=[model.KIND_MIN, model.KIND_TS, model.KIND_MIN, model.KIND_TS])
    d.style.show_barriers = True
    barriers = model.layout(d).barriers
    assert [(i, y0, y1) for _, i, _, y0, y1, _ in barriers] == [(1, 0.0, 20.0), (3, -5.0, 12.0)]
    # The arrow stands just right of the TS bar; the guide starts at the minimum.
    _, _, x, _, _, x_from = barriers[0]
    assert x == pytest.approx(1.3 + model.BARRIER_GAP) and x_from == pytest.approx(0.3)


def test_each_pathway_gets_its_own_barrier_lane():
    d = diagram(0, 20, kinds=[model.KIND_MIN, model.KIND_TS])
    d.style.show_barriers = True
    d.pathways.append(
        model.Pathway(levels=[model.Level(energy="0"), model.Level(energy="8", kind=model.KIND_TS)])
    )
    first, second = model.layout(d).barriers
    assert second[2] - first[2] == pytest.approx(model.BARRIER_LANE)
    d.pathways[0].visible = False
    (only,) = model.layout(d).barriers
    assert only[2] == pytest.approx(first[2])


def test_hidden_pathways_and_none_connectors_are_left_out():
    d = diagram(0, 1)
    d.style.connector = "none"
    assert model.layout(d).connectors == []
    d.pathways[0].visible = False
    assert model.layout(d).levels == []


def test_file_round_trip_keeps_everything():
    d = diagram(0, 20, kinds=[model.KIND_MIN, model.KIND_TS])
    d.compounds.append(model.Compound("A", -1.5, "ORCA G: a.out"))
    level = d.pathways[0].levels[1]
    level.label_offset = [12.5, -3.0]
    level.show_energy = False
    level.color = "#123456"
    d.style.connector = "curve"
    d.store_in_project = True
    text = json.dumps(d.to_dict())
    again = model.Diagram.from_dict(json.loads(text))
    assert again.to_dict() == d.to_dict()


def test_reading_tolerates_damage_and_refuses_strangers():
    data = model.Diagram().to_dict()
    data["style"]["connector"] = "zigzag"
    data["style"]["decimals"] = 99
    data["style"]["label_size"] = "big"
    data["style"]["font_size"] = "big"  # a 0.0.1 key, broken
    data["pathways"] = [
        {"name": "p", "levels": [{"kind": "??", "label_offset": "x", "position": "a"}, 5]}
    ]
    d = model.Diagram.from_dict(data)
    assert d.style.connector == "dashed" and d.style.decimals == 6 and d.style.label_size == 10.0
    level = d.pathways[0].levels[0]
    assert (
        level.kind == model.KIND_MIN and level.label_offset == [0.0, 0.0] and level.position is None
    )
    with pytest.raises(ValueError, match="not an energy diagram"):
        model.Diagram.from_dict({"format": "other"})
    with pytest.raises(ValueError, match="newer version"):
        model.Diagram.from_dict({"format": model.FILE_FORMAT, "version": 99})
    assert model.Diagram.from_dict({"format": model.FILE_FORMAT}).pathways


def test_empty_and_next_color():
    d = model.Diagram()
    assert d.is_empty()
    d.pathways.append(model.Pathway(color=d.next_color()))
    assert d.pathways[1].color == model.DEFAULT_COLORS[1]
    d.compounds.append(model.Compound("a"))
    assert not d.is_empty()


def test_axis_label():
    style = model.Style()
    assert style.axis_label() == "ΔG (kcal/mol)"
    style.y_label = "Relative energy"
    assert style.axis_label() == "Relative energy"
    assert not math.isnan(style.fig_width)


def test_files_from_0_0_1_keep_their_text_sizes():
    old = {"font_size": 12, "label_size": 11, "label_bold": True, "connector": "solid"}
    style = model.Style.from_dict(old)
    assert (style.axis_size, style.tick_size, style.legend_size, style.title_size) == (
        12,
        12,
        12,
        13,
    )
    assert style.label_size == 11 and style.label_bold and style.connector == "solid"
    assert style.quantity_italic  # new settings take their defaults


def test_style_values_are_checked():
    bad = {
        "label_color": "pathway",
        "tick_color": model.PATHWAY_COLOR,
        "energy_color": "red",
        "connector_color": model.PATHWAY_COLOR,
        "background": "#12345",
        "barrier_arrow": "<=>",
        "tick_direction": "up",
        "legend_location": "moon",
        "title_size": 500.0,
        "y_fixed": True,
        "y_min": 5.0,
        "y_max": -5.0,
        "y_step": -1.0,
    }
    style = model.Style.from_dict(bad)
    assert style.label_color == model.PATHWAY_COLOR  # labels may follow the pathway
    assert style.tick_color == "#000000"  # axis numbers may not
    assert style.energy_color == model.PATHWAY_COLOR  # not a #rrggbb colour
    assert style.connector_color == model.PATHWAY_COLOR
    assert style.background == "#ffffff"
    assert (style.barrier_arrow, style.tick_direction, style.legend_location) == (
        "<->",
        "out",
        "best",
    )
    assert style.title_size == 11.0
    assert not style.y_fixed and style.y_step == 0.0


def test_side_margin():
    d = diagram(0, 1)
    d.style.x_margin = 1.25
    assert model.layout(d).x_range == (-0.3 - 1.25, 1.3 + 1.25)

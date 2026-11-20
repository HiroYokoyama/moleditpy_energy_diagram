"""Energies from output files: synthetic excerpts here, real outputs when the
sibling result-analyzer checkouts are present."""

import os
from pathlib import Path

import pytest

from energy_diagram import parsers

ORCA = """
                                 *****************
                                 * O   R   C   A *
                                 *****************
FINAL SINGLE POINT ENERGY      -192.895871005924
FINAL SINGLE POINT ENERGY      -192.895872364447
THERMOCHEMISTRY AT 298.15K
Total Enthalpy                    ...   -192.80653710 Eh
Final Gibbs free energy         ...   -192.84077533 Eh
"""

GAUSSIAN = """
 Entering Gaussian System, Link 0=g16
 SCF Done:  E(RB3LYP) =  -232.248600000     A.U. after   10 cycles
 SCF Done:  E(RB3LYP) =  -232.248651275     A.U. after    1 cycles
 Sum of electronic and thermal Enthalpies=            -232.142600
 Sum of electronic and thermal Free Energies=         -232.175391
"""

GAMESS = """
          *         GAMESS VERSION = 30 SEP 2023 (R2)          *
 FINAL RHF ENERGY IS     -230.7031369095 AFTER   6 ITERATIONS
 FINAL RHF ENERGY IS     -230.7031370128 AFTER   4 ITERATIONS
     THERMOCHEMISTRY AT T=  298.15 K
              E         H         G         CV        CP        S
           KJ/MOL    KJ/MOL    KJ/MOL   J/MOL-K   J/MOL-K   J/MOL-K
 TOTAL    293.450   295.929   210.965    64.543    72.857   284.971
              E         H         G         CV        CP        S
         KCAL/MOL  KCAL/MOL  KCAL/MOL CAL/MOL-K CAL/MOL-K CAL/MOL-K
 ELEC.      0.000     0.000     0.000     0.000     0.000     0.000
 TOTAL     70.136    70.729    50.422    15.426    17.413    68.110
"""


def lines(text):
    return text.splitlines()


def test_orca_takes_the_last_energy_and_the_thermochemistry():
    program, values = parsers.energies(lines(ORCA))
    assert program == "ORCA"
    assert values == {"E": -192.895872364447, "H": -192.8065371, "G": -192.84077533}


def test_gaussian():
    program, values = parsers.energies(lines(GAUSSIAN))
    assert program == "Gaussian"
    assert values == {"E": -232.248651275, "H": -232.1426, "G": -232.175391}


def test_gamess_adds_the_kcal_table_to_the_last_energy():
    program, values = parsers.energies(lines(GAMESS))
    assert program == "GAMESS"
    e = -230.7031370128
    assert values["E"] == e
    assert values["H"] == pytest.approx(e + 70.729 / parsers.KCAL_PER_HARTREE)
    assert values["G"] == pytest.approx(e + 50.422 / parsers.KCAL_PER_HARTREE)


def test_a_single_point_has_no_free_energy(tmp_path):
    path = tmp_path / "sp.out"
    path.write_text("* O   R   C   A *\nFINAL SINGLE POINT ENERGY   -1.5\n", encoding="utf-8")
    assert parsers.read_energy(str(path), "E") == (-1.5, "ORCA E: sp.out")
    with pytest.raises(
        parsers.OutputError, match=r"has no gibbs free energy \(g\); it has Electronic energy"
    ):
        parsers.read_energy(str(path), "G")


def test_other_files_are_refused(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("nothing here\n", encoding="utf-8")
    with pytest.raises(parsers.OutputError, match="Not an ORCA"):
        parsers.read_energy(str(path))


def test_program_found_from_its_energy_line_alone():
    assert parsers.detect_program([" SCF Done:  E(UHF) =  -1.0  A.U."]) == "Gaussian"
    assert parsers.detect_program([" FINAL ROHF ENERGY IS  -1.0"]) == "GAMESS"


def test_fortran_exponents():
    _, values = parsers.energies(["* O   R   C   A *", "FINAL SINGLE POINT ENERGY   -1.5D+00"])
    assert values["E"] == -1.5


@pytest.mark.parametrize(
    ("path", "name"),
    [("/x/TS-1 (opt).out", "TS_1__opt_"), ("2-butene.log", "c_2_butene"), ("cat.out", "cat")],
)
def test_compound_names_fit_expressions(path, name):
    assert parsers.compound_name(path) == name


SIBLINGS = Path(__file__).resolve().parents[2]
REAL = [
    (
        "moleditpy_orca_result_analyzer_plugin/tests/sample_outputs/acetone-opt.out",
        "ORCA",
        {"E", "H", "G"},
    ),
    (
        "moleditpy_gaussian_result_analyzer/tests/sample_outputs/benzene_opt_freq.out",
        "Gaussian",
        {"E", "H", "G"},
    ),
    (
        "moleditpy_gamess_result_analyzer/tests/sample_outputs/benzene_opt_hess.out",
        "GAMESS",
        {"E", "H", "G"},
    ),
    ("moleditpy_gamess_result_analyzer/tests/sample_outputs/hcn_irc.out", "GAMESS", {"E"}),
]


@pytest.mark.parametrize(("relative", "program", "kinds"), REAL)
def test_real_outputs_when_the_analyzers_are_checked_out(relative, program, kinds):
    path = SIBLINGS / relative
    if not path.exists():
        pytest.skip(f"{relative} is not checked out beside this repository")
    with open(path, encoding="utf-8", errors="replace") as handle:
        found, values = parsers.energies(handle.read().splitlines())
    assert found == program
    assert set(values) == kinds
    assert all(v < 0 for v in values.values())
    if "G" in values:
        assert values["G"] < values["H"] and values["E"] < values["H"]
    assert os.path.basename(relative)

"""Final energies from ORCA, Gaussian and GAMESS output files, in Hartree.

Only the last value of each kind is taken: an optimisation prints one per
step, and the converged structure's comes last. The patterns follow the ones
the MoleditPy result analyzers use for the same programs.
"""

from __future__ import annotations

import os
import re

KCAL_PER_HARTREE = 627.5094740631

QUANTITY_E = "E"
QUANTITY_H = "H"
QUANTITY_G = "G"
QUANTITIES = {
    QUANTITY_E: "Electronic energy (E)",
    QUANTITY_H: "Enthalpy (H)",
    QUANTITY_G: "Gibbs free energy (G)",
}

_FLOAT = r"(-?\d+\.\d+(?:[eEdD][-+]?\d+)?)"

_ORCA_E = re.compile(r"^\s*FINAL SINGLE POINT ENERGY\s+" + _FLOAT)
_ORCA_H = re.compile(r"^\s*Total Enthalpy\s+\.\.\.\s+" + _FLOAT + r"\s+Eh")
_ORCA_G = re.compile(r"^\s*Final Gibbs free energy\s+\.\.\.\s+" + _FLOAT + r"\s+Eh")

_GAUSSIAN_E = re.compile(r"^\s*SCF Done:\s+E\(\S+\)\s+=\s+" + _FLOAT)
_GAUSSIAN_H = re.compile(r"^\s*Sum of electronic and thermal Enthalpies=\s+" + _FLOAT)
_GAUSSIAN_G = re.compile(r"^\s*Sum of electronic and thermal Free Energies=\s+" + _FLOAT)

_GAMESS_E = re.compile(r"^\s*FINAL\s+\S+\s+ENERGY IS\s+" + _FLOAT)
_GAMESS_THERMO = re.compile(r"THERMOCHEMISTRY AT T=")
_GAMESS_ROW = re.compile(r"^\s*TOTAL\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)")


class OutputError(ValueError):
    """The file holds no energy of the kind asked for."""


def _number(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def detect_program(lines: list[str]) -> str:
    head = "\n".join(lines[:400])
    if "O   R   C   A" in head:
        return "ORCA"
    if "Gaussian, Inc." in head or "Entering Gaussian System" in head:
        return "Gaussian"
    if "GAMESS" in head:
        return "GAMESS"
    for line in lines:
        if _ORCA_E.match(line):
            return "ORCA"
        if _GAUSSIAN_E.match(line):
            return "Gaussian"
        if _GAMESS_E.match(line):
            return "GAMESS"
    raise OutputError("Not an ORCA, Gaussian or GAMESS output file.")


def _last(pattern: re.Pattern, lines: list[str]) -> float | None:
    value = None
    for line in lines:
        match = pattern.match(line)
        if match:
            value = _number(match.group(1))
    return value


def _gamess_thermal(lines: list[str], column: int) -> float | None:
    """GAMESS prints corrections, not totals: E + the kcal/mol TOTAL row."""
    energy = _last(_GAMESS_E, lines)
    start = None
    for i, line in enumerate(lines):
        if _GAMESS_THERMO.search(line):
            start = i
    if energy is None or start is None:
        return None
    in_kcal = False
    for line in lines[start:]:
        if "KCAL/MOL" in line and "CAL/MOL-K" in line:
            in_kcal = True
            continue
        if in_kcal:
            match = _GAMESS_ROW.match(line)
            if match:
                return energy + float(match.group(column)) / KCAL_PER_HARTREE
    return None


def energies(lines: list[str]) -> tuple[str, dict[str, float]]:
    """(program, {quantity: Hartree}) with whatever the file has."""
    program = detect_program(lines)
    found: dict[str, float | None] = {}
    if program == "ORCA":
        found = {
            QUANTITY_E: _last(_ORCA_E, lines),
            QUANTITY_H: _last(_ORCA_H, lines),
            QUANTITY_G: _last(_ORCA_G, lines),
        }
    elif program == "Gaussian":
        found = {
            QUANTITY_E: _last(_GAUSSIAN_E, lines),
            QUANTITY_H: _last(_GAUSSIAN_H, lines),
            QUANTITY_G: _last(_GAUSSIAN_G, lines),
        }
    else:
        found = {
            QUANTITY_E: _last(_GAMESS_E, lines),
            QUANTITY_H: _gamess_thermal(lines, 2),
            QUANTITY_G: _gamess_thermal(lines, 3),
        }
    return program, {k: v for k, v in found.items() if v is not None}


def read_energy(path: str, quantity: str = QUANTITY_E) -> tuple[float, str]:
    """(Hartree, description) of one quantity from an output file."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()
    program, values = energies(lines)
    if quantity not in values:
        have = ", ".join(QUANTITIES[k] for k in values) or "no energy"
        raise OutputError(
            f"{os.path.basename(path)} ({program}) has no {QUANTITIES[quantity].lower()}; it has {have}."
        )
    return values[quantity], f"{program} {quantity}: {os.path.basename(path)}"


def compound_name(path: str) -> str:
    """A name usable in level expressions without braces where possible."""
    stem = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    if not name or name[0].isdigit():
        name = "c_" + name
    return name

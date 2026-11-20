"""Energies from the ORCA, Gaussian and GAMESS Result Analyzer plugins.

Nothing here imports those plugins. An analyzer counts as installed when
MoleditPy has loaded a module with its PLUGIN_NAME, and its results are read
from the analyzer windows that are open: each keeps the parsed output in
``window.parser.data`` (``scf_energy`` and the ``thermal`` block, in Hartree)
and the file in ``window.file_path``.
"""

from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass

from . import parsers

# Printed copies of one energy can differ in the last digits (ORCA: 8 vs 12).
SAME_ENERGY = 1e-6  # Hartree

ANALYZERS = ("ORCA Result Analyzer", "Gaussian Result Analyzer", "GAMESS Result Analyzer")

# (key, description, how to read it from the parsed data). The key is the
# suffix of the suggested compound name, so E, H and G match parsers.QUANTITIES.
_E = "E"
VALUES = (
    (_E, "Final SCF energy (E)", lambda data, th: data.get("scf_energy")),
    (
        "Eel",
        "Electronic energy of the thermochemistry",
        lambda data, th: th.get("electronic_energy"),
    ),
    ("EZPE", "E + ZPE", lambda data, th: _sum(th.get("electronic_energy"), th.get("zpe"))),
    ("U", "Internal energy (U)", lambda data, th: th.get("thermal_energy")),
    (parsers.QUANTITY_H, "Enthalpy (H)", lambda data, th: th.get("enthalpy")),
    (parsers.QUANTITY_G, "Gibbs free energy (G)", lambda data, th: th.get("gibbs")),
    ("ZPE", "Zero-point energy", lambda data, th: th.get("zpe")),
    ("Hcorr", "Enthalpy correction (H − E)", lambda data, th: th.get("enthalpy_corr")),
    ("Gcorr", "Gibbs correction (G − E)", lambda data, th: th.get("gibbs_corr")),
)


@dataclass
class Result:
    """The output file one analyzer window has open."""

    analyzer: str  # the plugin's name
    path: str
    data: dict

    @property
    def program(self) -> str:
        return self.analyzer.split()[0]


@dataclass
class Value:
    result: Result
    key: str
    description: str
    energy: float

    def suggested_name(self, quantity: str) -> str:
        """The file's name for the quantity chosen in the window, with a suffix otherwise."""
        base = parsers.compound_name(self.result.path)
        return base if self.key == quantity else f"{base}_{self.key}"

    def source(self) -> str:
        return f"{self.result.analyzer} {self.key}: {os.path.basename(self.result.path)}"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sum(a, b):
    return a + b if _number(a) and _number(b) else None


def installed(modules=None) -> dict:
    """{module name: plugin name} for every analyzer MoleditPy has loaded."""
    modules = sys.modules if modules is None else modules
    found = {}
    for name, module in list(modules.items()):
        if not isinstance(module, types.ModuleType):
            continue
        plugin = module.__dict__.get("PLUGIN_NAME")
        if plugin in ANALYZERS and module.__dict__.get("__package__") == name:
            found[name] = plugin
    return found


def open_results(widgets, modules=None) -> list:
    """The files open in visible analyzer windows, one Result per window."""
    packages = installed(modules)
    results = []
    for widget in widgets:
        owner = type(widget).__module__
        plugin = next((p for name, p in packages.items() if owner.startswith(name + ".")), None)
        if plugin is None:
            continue
        try:
            if not widget.isVisible():
                continue
        except RuntimeError:  # a window Qt has already deleted
            continue
        data = getattr(getattr(widget, "parser", None), "data", None)
        path = getattr(widget, "file_path", None)
        if isinstance(data, dict) and isinstance(path, str) and path:
            results.append(Result(plugin, path, data))
    return results


def values(result: Result) -> list:
    """Every energy the analyzer found in the file, in Hartree."""
    thermal = result.data.get("thermal")
    thermal = thermal if isinstance(thermal, dict) else {}
    found = []
    for key, description, read in VALUES:
        energy = read(result.data, thermal)
        if _number(energy):
            found.append(Value(result, key, description, float(energy)))
    # The thermochemistry's electronic energy is usually the final SCF energy;
    # list it separately only when it is not.
    final = next((v.energy for v in found if v.key == _E), None)
    return [
        v
        for v in found
        if not (v.key == "Eel" and final is not None and abs(v.energy - final) < SAME_ENERGY)
    ]

"""Finding the Result Analyzer plugins and reading the energies they hold."""

import sys
import types
from pathlib import Path

import pytest

from energy_diagram import analyzers

THERMAL = {
    "electronic_energy": -100.0,
    "zpe": 0.05,
    "thermal_energy": -99.94,
    "enthalpy": -99.939,
    "gibbs": -99.97,
    "enthalpy_corr": 0.061,
    "gibbs_corr": 0.03,
    "temperature": 298.15,
}


def plugin_module(name, plugin):
    module = types.ModuleType(name)
    module.__package__ = name
    module.PLUGIN_NAME = plugin
    return module


class FakeWindow:
    def __init__(self, module, path, data, visible=True):
        self.__class__ = type("AnalyzerDialog", (FakeWindow,), {"__module__": f"{module}.gui"})
        self.parser = types.SimpleNamespace(data=data)
        self.file_path = path
        self.visible = visible

    def isVisible(self):
        return self.visible


def test_installed_analyzers_are_found_by_plugin_name():
    modules = {
        "plugins.orca_result_analyzer": plugin_module(
            "plugins.orca_result_analyzer", "ORCA Result Analyzer"
        ),
        "plugins.orca_result_analyzer.gui": types.ModuleType("plugins.orca_result_analyzer.gui"),
        "gamess": plugin_module("gamess", "GAMESS Result Analyzer"),
        "other": plugin_module("other", "Job Manager"),
        "not_a_module": object(),
    }
    # A submodule that re-exports PLUGIN_NAME is not the plugin itself.
    modules["plugins.orca_result_analyzer.gui"].PLUGIN_NAME = "ORCA Result Analyzer"
    assert analyzers.installed(modules) == {
        "plugins.orca_result_analyzer": "ORCA Result Analyzer",
        "gamess": "GAMESS Result Analyzer",
    }
    assert analyzers.installed({}) == {}


def test_open_results_come_from_visible_analyzer_windows():
    modules = {"orca": plugin_module("orca", "ORCA Result Analyzer")}
    windows = [
        FakeWindow("orca", "/calc/TS-1.out", {"scf_energy": -1.0}),
        FakeWindow("orca", "/calc/hidden.out", {"scf_energy": -2.0}, visible=False),
        FakeWindow("orca", "", {"scf_energy": -3.0}),  # an empty analyzer
        FakeWindow("someone_else", "/calc/x.out", {"scf_energy": -4.0}),
    ]
    (result,) = analyzers.open_results(windows, modules)
    assert (result.analyzer, result.path, result.program) == (
        "ORCA Result Analyzer",
        "/calc/TS-1.out",
        "ORCA",
    )


def test_values_list_every_energy_in_hartree():
    result = analyzers.Result(
        "ORCA Result Analyzer", "/calc/TS-1.out", {"scf_energy": -100.0, "thermal": THERMAL}
    )
    found = {v.key: v.energy for v in analyzers.values(result)}
    assert found == {
        "E": -100.0,
        "EZPE": pytest.approx(-99.95),
        "U": -99.94,
        "H": -99.939,
        "G": -99.97,
        "ZPE": 0.05,
        "Hcorr": 0.061,
        "Gcorr": 0.03,
    }  # the thermochemistry's own E equals the final one, so it is not repeated
    # ORCA prints the thermochemistry's copy with fewer digits; still the same energy.
    result.data["scf_energy"] = -100.000000004
    assert "Eel" not in {v.key for v in analyzers.values(result)}


def test_a_different_thermochemistry_energy_is_listed_and_odd_values_skipped():
    data = {"scf_energy": -101.0, "thermal": dict(THERMAL, gibbs=None, enthalpy="x", zpe=True)}
    found = {
        v.key: v.energy
        for v in analyzers.values(analyzers.Result("GAMESS Result Analyzer", "a.log", data))
    }
    assert found["Eel"] == -100.0
    assert "G" not in found and "H" not in found and "ZPE" not in found and "EZPE" not in found
    assert analyzers.values(analyzers.Result("x", "a.log", {"thermal": "broken"})) == []


def test_names_and_sources():
    result = analyzers.Result("Gaussian Result Analyzer", "/calc/TS-1 (opt).log", {})
    g = analyzers.Value(result, "G", "Gibbs free energy (G)", -1.0)
    corr = analyzers.Value(result, "Gcorr", "Gibbs correction", 0.01)
    assert g.suggested_name("G") == "TS_1__opt_"
    assert g.suggested_name("E") == "TS_1__opt__G"
    assert corr.suggested_name("G") == "TS_1__opt__Gcorr"
    assert g.source() == "Gaussian Result Analyzer G: TS-1 (opt).log"


SIBLINGS = Path(__file__).resolve().parents[2]
REAL = [
    (
        "moleditpy_orca_result_analyzer_plugin",
        "orca_result_analyzer.parser",
        "OrcaParser",
        "tests/sample_outputs/acetone-opt.out",
    ),
    (
        "moleditpy_gaussian_result_analyzer",
        "gaussian_result_analyzer.parser",
        "GaussianParser",
        "tests/sample_outputs/benzene_opt_freq.out",
    ),
    (
        "moleditpy_gamess_result_analyzer",
        "gamess_result_analyzer.parser",
        "GAMESSParser",
        "tests/sample_outputs/benzene_opt_hess.out",
    ),
]


@pytest.fixture
def clean_modules():
    """Drop whatever a test imports, so the analyzers do not count as installed later."""
    before = set(sys.modules)
    path = list(sys.path)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]
    sys.path[:] = path


@pytest.mark.parametrize(("repo", "module", "cls", "sample"), REAL)
def test_real_analyzer_parsers_when_checked_out(repo, module, cls, sample, clean_modules):
    """The keys read here are the ones the analyzers really fill."""
    root = SIBLINGS / repo
    if not (root / sample).exists():
        pytest.skip(f"{repo} is not checked out beside this repository")
    pytest.importorskip("PySide6.QtWidgets")
    from energy_diagram import parsers

    sys.path.insert(0, str(root))
    parser_cls = getattr(__import__(module, fromlist=[cls]), cls)
    parser = parser_cls()
    content = (root / sample).read_text(encoding="utf-8", errors="replace")
    parser.load_from_memory(content, str(root / sample))
    found = {
        v.key: v.energy
        for v in analyzers.values(analyzers.Result(repo, str(root / sample), parser.data))
    }
    assert {"E", "H", "G", "ZPE", "Gcorr"} <= set(found)
    # The same file through this plugin's own reader gives the same numbers.
    lines = content.splitlines()
    _, own = parsers.energies(lines)
    assert found["G"] == pytest.approx(own["G"], abs=2e-6)
    assert found["H"] == pytest.approx(own["H"], abs=2e-6)
    assert found["G"] - found["Gcorr"] == pytest.approx(found.get("Eel", found["E"]), abs=2e-6)

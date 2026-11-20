# Reaction Energy Diagram Plugin

[![CI](https://github.com/HiroYokoyama/moleditpy_energy_diagram/actions/workflows/ci.yml/badge.svg)](https://github.com/HiroYokoyama/moleditpy_energy_diagram/actions/workflows/ci.yml)
[![GitHub tag](https://img.shields.io/github/v/tag/HiroYokoyama/moleditpy_energy_diagram?label=version)](https://github.com/HiroYokoyama/moleditpy_energy_diagram/tags)
[![GitHub Downloads](https://img.shields.io/github/downloads/HiroYokoyama/moleditpy_energy_diagram/total)](https://github.com/HiroYokoyama/moleditpy_energy_diagram/releases)

![Reaction Energy Diagram](img/main.png)

## Overview

A separate MoleditPy window for drawing reaction energy profiles at publication
quality. Collect the energies of the compounds as you open their calculations one after
another, write each level as a sum of compounds, and export the figure as SVG, PDF, EPS,
PNG or TIFF.

The diagram is kept apart from the molecule: opening another file or **File > New** in
MoleditPy never clears it, so values can be gathered across many output files.

## Features

- **Compounds**: energies in Hartree, read from ORCA, Gaussian and GAMESS output files
  (electronic energy *E*, enthalpy *H* or Gibbs free energy *G*; the last value in the
  file is used). **From Open Document** reads the output file MoleditPy has open. Reading
  a file again updates the compound with the same name. Energies can also be typed.
- **Levels**: each level's energy is a number in the input unit or an expression of
  compounds, for example `cat + sub`, `TS1 - cat`, `2*monomer` or `{Pd(PPh3)2} + L`.
  Values are shown relative to the first level of the first visible pathway, in
  kcal/mol, kJ/mol, eV or Hartree.
- **Pathways**: several pathways in their own colours, each shown or hidden. A new
  pathway copies the steps of the current one, ready for the other energies. Levels are
  minima or transition states, placed in order or at a chosen position so pathways can
  share or skip steps.
- **Mouse placement**: drag any label, value, structure or barrier value to move it.
  Right-click it to hide it, edit it or put it back; right-click a level for its
  colour and visibility. Click a level to find it in the table.
- **Style**: dashed, dotted, solid, smooth-curve or no connectors; bar width and line
  widths; font, sizes and bold labels; number of decimals, sign, parentheses and unit
  on values; axis and figure titles; barrier arrows (ΔG‡) from the minimum before each
  transition state; 2D structures drawn from SMILES (**Structure from Loaded
  Molecule** takes the molecule in MoleditPy); legend, energy axis, figure size and a
  transparent background.
- The figure on screen has the exported size, so what is placed is what is exported.
  SVG keeps text as text for later editing; PDF and EPS embed the fonts.
- **Files**: diagrams are saved as `.pmeedg` files, which MoleditPy opens directly.
  With **File > Store in the MoleditPy Project File** ticked, the diagram is also saved
  inside the `.pmeprj` project and comes back when the project is opened. The current
  diagram is kept between sessions even when it was never saved.

## Usage

1. Open **Extensions > Reaction Energy Diagram...**.
2. On the **Compounds** tab, choose *G*, *H* or *E* and add the output files with
   **From Output Files...**, or use **From Open Document** while you go through the
   calculations in MoleditPy.
3. On the **Levels** tab, add a level per step and write its energy, for example
   `cat + sub` for the starting point and `TS1` for the transition state.
4. Set the look on the **Style** tab, drag labels into place, and use
   **File > Export Image...** or **Copy Image**.
5. **File > Save** writes a `.pmeedg` file.

The window also runs on its own: `python -m energy_diagram [file.pmeedg]`.

## Requirements

matplotlib, besides what MoleditPy already provides (PySide6; RDKit for structures).

## Development and testing

```bash
python -m pytest tests/ -v
ruff format energy_diagram tests && ruff check energy_diagram tests
```

The energy model, expression parser and layout in `energy_diagram/model.py` have no Qt or
matplotlib dependency. The output parsers are checked against real ORCA, Gaussian and
GAMESS outputs when the sibling result-analyzer repositories are checked out. The window
is tested with a real Qt and a fake host context, including dragging with mouse events,
and `tests/test_api.py` checks every host API call against the MoleditPy source when it
is checked out beside this repository.

## Licensing scope

First-party code is LGPL-3.0-or-later. See [LICENSE](LICENSE), [COPYING](COPYING) and
[dependency/provenance terms](LICENSING.md). Third-party components retain their own
terms.

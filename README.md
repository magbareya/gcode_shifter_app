# G-code Shifter

A desktop app that moves and resizes GRBL G-code jobs, so you don't have to go
back to your CAM or laser software for that. Made for the **TwoTrees TTC450
Pro**. It works with any GRBL 1.1 machine, as a CNC router or with a laser
module.

- **Preview:** a zoomable toolpath view (cutting/burning, travel moves, the
  original file) with work zero, the 460 × 460 mm bed outline, a grid with
  rulers, and live cursor coordinates.
- **Position:** put the lower-left corner or the center at 0,0 in one click,
  place any of 9 points of the job at given coordinates, or move it by a
  distance.
- **Scale:** shrink or enlarge with the aspect ratio kept, by percent or by a
  target width or height, around a fixed point you choose.
- **Result preview:** a green dashed box shows where the job will end up
  before you click.
- **Z (CNC only):** set the deepest cut, or move Z by an amount. Asks you to
  confirm first.
- **Undo / Redo / Reset,** a history list, a warning about unsaved changes,
  drag & drop, and light/dark theme following Windows.

## Requirements

| Package | Version | Notes |
|---|---|---|
| Python | **3.10 or newer** (tested 3.12.6) | must be on the PATH as `python` |
| PySide6 | **6.6 or newer, below 7** (tested 6.12.0) | the only third-party package |
| pytest | any (optional) | only to run the tests |

Everything else (`hashlib`, `math`, `re`, …) is part of the Python standard
library. Install the packages into your normal (global) Python:

```powershell
python -m pip install -r requirements.txt
```

## How to run

**Windows:** double-click **`run.bat`**, or run it from a terminal:

```powershell
.\run.bat
```

It uses your global Python and installs PySide6 automatically if it's
missing. It starts the app without a console window.

**Directly (any OS):**

```powershell
python gcode_shifter.py
python gcode_shifter.py "C:\path\to\job.nc"   # open a file straight away
```

**VS Code:** press F5 and choose **G-code Shifter**.

## Using it

1. **Open:** drag a `.nc` / `.gcode` / `.ngc` / `.tap` file onto the window,
   or press **Ctrl+O**.
2. **Adjust:** use the *Position*, *Scale* or *Z* tab. The green dashed box
   and ◆ show the result before you click. The figures, preview and history
   update after every change.
3. **Save:** press **Ctrl+S**. The first save asks for a name and suggests
   `<name>_edited.nc` next to the original. The original is never overwritten
   unless you choose it and confirm.

> Always load the edited file in your sender (LightBurn, Candle, UGS…) and run
> a frame or dry run before cutting or burning.

### Keyboard and mouse

| Action | Shortcut |
|---|---|
| Open / Save / Save as | Ctrl+O / Ctrl+S / Ctrl+Shift+S |
| Undo / Redo | Ctrl+Z / Ctrl+Y |
| Fit preview to window | F, or double-click the preview |
| Show travel / original / bed | T / C / B |
| Zoom / pan | mouse wheel / drag |

## What the editor changes (and what it doesn't)

Only the numbers that need to change are rewritten. Comments, spacing, `%`
lines, `$` commands, line endings and word order stay exactly as they were.

| Item | Shift | Scale |
|---|---|---|
| Absolute X/Y targets (G90) | shifted | scaled around the fixed point |
| Relative moves (G91) | unchanged (correct: they are distances) | scaled |
| Arc `I` `J` (always relative in GRBL) and `R` | unchanged | scaled |
| Z | only from the Z tab | unchanged |
| Feed `F`, spindle speed / laser power `S` | unchanged | unchanged |
| `G53`, `G28`/`G30`, `G92`, `G10`, `G43.1` lines | unchanged | unchanged |

What counts as the **cut area** (used for positioning and scaling):
feed moves (`G1`/`G2`/`G3`) with the spindle or laser on and `S` not 0.
Rapids, laser-off travel and raster overscan are excluded.

### Limitations

- **CNC scaling:** the bit doesn't scale. Paths offset by the bit radius come
  out slightly off size, and pocket step-over changes. For exact parts,
  re-export from CAM.
- **Laser raster images:** the spacing between scan lines scales too.
  Enlarging leaves gaps; shrinking overlaps lines and burns darker. Vector
  outlines scale fine.
- **Park / return moves:** a final "go to `X0 Y0`" travel move is
  transformed like every other move. After moving or scaling, the head parks
  at the transformed position, not at 0,0.
- **Machine size:** the 460 × 460 × 80 mm figure in `utils.py`
  (`MACHINE_TRAVEL_MM`) is only used for warnings and the bed outline. Adjust
  it if your machine differs.

## Project layout

| File | Purpose |
|---|---|
| `gcode_shifter.py` | Desktop app (PySide6 / Qt) |
| `utils.py` | G-code parsing, shift/scale, extents, toolpath for the preview (no GUI code) |
| `tests/test_utils.py` | Tests for `utils.py` |
| `run.bat` | Windows launcher |
| `requirements.txt` | Package versions |

## Tests

```powershell
python -m pip install pytest
python -m pytest -q
```

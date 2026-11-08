# G-code Shifter

A small web app that moves and resizes GRBL G-code jobs, so you don't have to
go back to your CAM or laser software for that. Made for the **TwoTrees TTC450
Pro**. It works with any GRBL 1.1 machine, as a CNC router or with a laser
module.

- **Preview:** an interactive XY plot of the toolpath (cutting/burning, travel
  moves and the original file), with your work zero (X0 Y0) marked.
- **Position:** put the lower-left corner or the center at 0,0 in one click,
  place any point of the job at given coordinates, or move it by a distance.
- **Scale:** shrink or enlarge with the aspect ratio kept, by percent or by a
  target width or height, around a fixed point you choose.
- **Z (CNC only):** set the deepest cut, or move Z by an amount. Asks you to
  confirm first.
- **Undo, Reset and History,** plus a download of the edited file.
- **Warnings:** shown when the job is larger than the machine (460 × 460 × 80
  mm), when the file is in inches, and for similar problems.

## How to run

**Requirement:** Python 3.10 or newer, available as `python` on the PATH.

### Windows (easiest)

Double-click **`run.bat`**, or run it from a terminal in the project folder:

```powershell
.\run.bat
```

- **First run:** it creates a virtual environment in `.venv` and installs the
  dependencies. This takes about a minute.
- **Later runs:** it starts the app straight away.

Your browser opens **http://localhost:8501**. Keep the terminal window open
while you use the app, and press **Ctrl+C** in it (or close it) to stop.

### Manual / other platforms

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit run gcode_processor.py
```

### VS Code

1. Press Ctrl+Shift+P, choose **Python: Select Interpreter**, and pick `.venv`.
   `.vscode/settings.json` already points there.
2. Press F5 and choose **Streamlit Debug**.

### Troubleshooting

- **"This app was started with the wrong Python":** the app was started with
  the global Python instead of `.venv`. The global install has an old
  Streamlit and protobuf 5.28.0, which crashes. Close it and use `run.bat`.
- **The page still shows the old app or the error above:** an old server may
  still be running on port 8501. Close its terminal, or find it with
  `Get-NetTCPConnection -LocalPort 8501` and end that process, then start
  `run.bat` again.

## Using it

1. **Load:** upload a `.nc` / `.gcode` / `.ngc` / `.tap` file in the sidebar.
2. **Adjust:** use the *Position*, *Scale* or *Z* section. The preview, the
   figures at the top and the history update after every change.
3. **Save:** click **Download G-code** in the sidebar.

> Always load the edited file in your sender (LightBurn, Candle, UGS…) and run
> a frame or dry run before cutting or burning.

## What the editor changes (and what it doesn't)

Only the numbers that need to change are rewritten. Comments, spacing, `%`
lines, `$` commands and word order stay exactly as they were.

| Item | Shift | Scale |
|---|---|---|
| Absolute X/Y targets (G90) | shifted | scaled around the fixed point |
| Relative moves (G91) | unchanged (correct: they are distances) | scaled |
| Arc `I` `J` (always relative in GRBL) and `R` | unchanged | scaled |
| Z | only from the Z section | unchanged |
| Feed `F`, spindle speed / laser power `S` | unchanged | unchanged |
| `G53`, `G28`/`G30`, `G92`, `G10`, `G43.1` lines | unchanged | unchanged |

What counts as the **cut area** (used for positioning and scaling):
feed moves (`G1`/`G2`/`G3`) with the spindle or laser on and `S` not 0.
Rapids, laser-off travel and raster overscan are excluded.

**Limits of scaling finished G-code**

- **CNC:** the bit doesn't scale. Paths offset by the bit radius come out
  slightly off size, and pocket step-over changes. For exact parts, re-export
  from CAM.
- **Laser raster images:** the spacing between scan lines scales too.
  Enlarging leaves gaps; shrinking overlaps lines and burns darker. Vector
  outlines scale fine.

## Project layout

| File | Purpose |
|---|---|
| `gcode_processor.py` | Streamlit user interface |
| `utils.py` | G-code parsing, shift/scale, extents, toolpath for the preview |
| `tests/test_utils.py` | Tests for `utils.py` |
| `run.bat` | Windows launcher (creates `.venv` on first run) |
| `requirements.txt` | Dependencies |

## Tests

```powershell
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest -q
```

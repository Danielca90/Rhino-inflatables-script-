# Rhino inflatables script

Python tools for **Rhino 7 and 8** (Mac + Windows). Scripts are IronPython 2.7-compatible (no f-strings, numpy or pip).

## Parametric furniture (live sliders)
`scripts/furniture_parametric.py` - table, chair, bookshelf. Run it from
**Tools > PythonScript > Run...** (Rhino 7) or **Tools > Script > Run Python Script...** (Rhino 8); a floating panel opens and the model
**redraws as you move sliders** (leg style, taper, aprons, back tilt, slats,
shelf count...). Buttons: *Keep piece* (leave it in the model, grouped, and start
another), *Cut list...* (prints + saves CSV).

Handy: Rhino > Preferences > Aliases > add alias `furn` =
`! _-RunPythonScript "/full/path/to/scripts/furniture_parametric.py"`, or drag the
script onto a toolbar button.

Not run from a script? `import furniture_parametric as fp; fp.build_in_rhino("table", width=2000, leg_style="round")`

## NURBS from points / images
| | |
|---|---|
| `scripts/rhino_inside.py` | In Rhino: interpolated/control-point curves, exact arcs via weights, grid/image -> surface, loft, revolve |
| `scripts/nurbs_offline.py` | Standalone: image / depth map / XYZ grid -> geomdl fit -> `.3dm` (`pip install -r scripts/requirements.txt`) |
| `.claude/skills/` | `rhino-nurbs`, `rhino-furniture` notes for Claude |

## Tests
`pytest tests`. The offline NURBS pipeline and the furniture geometry/cut-list logic are tested.
The RhinoCommon/Eto code is only smoke-tested against stand-in modules, **not yet run inside Rhino** -
please try it on Mac and report anything that errors.

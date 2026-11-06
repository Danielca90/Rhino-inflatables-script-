# Rhino inflatables script

Python tools for building **NURBS curves, splines and surfaces for Rhino** - inside Rhino, or offline.

| | |
|---|---|
| `scripts/rhino_inside.py` | Run in Rhino (RunPythonScript / Script Editor). RhinoCommon only, no installs. Interpolated + control-point curves, weighted (exact) arcs, grid/image -> surface, loft, revolve. |
| `scripts/nurbs_offline.py` | Standalone CLI: image / depth map / XYZ grid -> geomdl fit -> `.3dm`. `pip install -r scripts/requirements.txt` |
| `.claude/skills/rhino-nurbs/SKILL.md` | Claude skill: NURBS concepts, recipes, gotchas, image->AI->NURBS pipeline |
| `tests/` | `pytest tests` - verifies geomdl -> rhino3dm conversion (knots, weights, grid order) |

```
python scripts/nurbs_offline.py demo demo.3dm
python scripts/nurbs_offline.py heightmap depth.png relief.3dm --width 400 --height 300 --z-scale 25 --ctrl 16
```

Status: offline pipeline tested (4 tests). `rhino_inside.py` is syntax-checked only - not yet run inside Rhino.

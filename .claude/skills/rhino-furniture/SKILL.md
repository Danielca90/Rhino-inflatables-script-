---
name: rhino-furniture
description: Parametric furniture (table, chair, bookshelf) for Rhino on Mac/Windows with a live-redraw Eto slider panel and cut list. Use when the user wants to add/modify furniture types, parameters, joinery or the Rhino UI in scripts/furniture_parametric.py.
---

# Parametric furniture in Rhino

`scripts/furniture_parametric.py` (Rhino 8, `#! python 3`, mm, Z up).

## Architecture - keep it split
1. **Spec layer (pure Python)**: `PARAMS[kind]` (slider definitions) -> `build_<kind>(values)` -> list of part dicts (`box` / `cyl` / `taper`). Also `bbox`, `cut_list`, `clean` (clamps everything). Fully unit-tested without Rhino (`pytest tests/test_furniture.py`).
2. **Rhino layer**: `realize(part)` -> Brep; `Session.rebuild()` deletes its previous objects, adds new ones on layers `Parametric Furniture::<group>`, redraws. `show_ui()` builds the Eto panel; changes are debounced 120 ms with `UITimer`.

## Add a new furniture type
1. Add `PARAMS["desk"] = [P(...), ...]` (limits matter: `clean()` enforces them).
2. Write `build_desk(v)` returning parts via `_box(...)`, `_leg(...)`.
3. Register in `BUILDERS` and add it to the kind dropdown in `show_ui`.
4. Add property tests: overall bbox follows params, extremes never crash, no zero/negative dims.

## Rules learned
- Always make geometry from `clean()`ed values; slider extremes must not produce inverted boxes (clamp insets, cap shelf count).
- Tilted parts: rotate about +X through the pivot by `-tilt` (leans toward +Y); `corners()` and `realize()` share this convention - change both together.
- Pass `.NET List[T]` into RhinoCommon, not bare Python lists.
- Wrap drawing in `Views.RedrawEnabled = False/True` and try/finally; swallow-and-print exceptions in Eto event handlers (they otherwise vanish).
- The Rhino/Eto layer is only smoke-tested with mocks in CI; real behaviour must be checked in Rhino.

---
name: rhino-nurbs
description: Build NURBS curves, splines and surfaces for Rhino with Python - either inside Rhino (RhinoCommon) or offline (geomdl + rhino3dm -> .3dm). Use when the user wants to create/fit/loft/revolve NURBS, convert points, meshes, depth maps or images into NURBS surfaces, or write Rhino scripts.
---

# Rhino NURBS with Python

Two runtimes, same ideas. Pick by where the user wants to run:

| Mode | File | Needs | Use when |
|---|---|---|---|
| Inside Rhino | `scripts/rhino_inside.py` | Rhino 7/8 only (RhinoCommon) | Interactive; geometry lands in the open doc |
| Offline | `scripts/nurbs_offline.py` | `pip install geomdl rhino3dm pillow numpy` | Batch / AI pipelines / CI; writes `.3dm` |

## NURBS vocabulary (what the parameters mean)

- **degree** p (order = p+1): 1 polyline, 2 conic-friendly, **3 default** (smooth, curvature-continuous).
- **control points** n must be > p. More points = more local control.
- **knot vector**: parameterization. Clamped uniform is the default everywhere here.
- **weights**: make it *rational* - needed for exact circles/arcs/spheres. All-1 = plain B-spline.
- **interpolate** = curve/surface passes through the data; **approximate / control-point** = data is a guide (smoother, lighter). For noisy data (images, AI output) always approximate.

## Recipes

| Goal | RhinoCommon | geomdl |
|---|---|---|
| Curve through points | `Curve.CreateInterpolatedCurve(pts, 3)` | `fitting.interpolate_curve(pts, 3)` |
| Curve from control pts | `Curve.CreateControlPointCurve(pts, 3)` | `BSpline.Curve` + `ctrlpts` |
| Smooth/simplify curve | `crv.Rebuild(n, 3, False)` | `fitting.approximate_curve(pts, 3, ctrlpts_size=n)` |
| Surface through grid | `NurbsSurface.CreateThroughPoints(...)` | `fitting.interpolate_surface` |
| Surface, grid as control net | `NurbsSurface.CreateFromPoints(...)` | - |
| Surface approximation | `srf.Rebuild(3,3,nu,nv)` | `fitting.approximate_surface(..., ctrlpts_size_u/v)` |
| Loft / revolve | `Brep.CreateFromLoft`, `RevSurface.Create` | - (do in Rhino) |
| Exact arc | weighted degree-2 curve, mid weight `cos(angle/2)` | `NURBS.Curve` + `weights` |

## Image -> AI -> NURBS pipeline

AI image-to-3D models output **meshes / point clouds / depth maps, never NURBS**. So:

1. Get geometry: a depth map (MiDaS, Depth Anything, ...) saved as PNG is the easiest - brightness = height. Meshes/point clouds must first be resampled to a regular grid (e.g. ray-cast along an axis, or in Rhino use `Mesh` -> `_QuadRemesh` -> `_ToNURBS`).
2. Downsample to a **regular grid** (<= ~64 per side).
3. Fit with a **small number of control points** (12-24 per direction) - approximation, not interpolation.
4. Write/add the surface. Inspect with `describe()` / `IsValid`.

```
python scripts/nurbs_offline.py heightmap depth.png out.3dm --width 400 --height 300 --z-scale 25 --ctrl 16
```

## Gotchas (all bit real implementations)

- **Knot vectors differ**: geomdl has `n+p+1` knots; Rhino/openNURBS/rhino3dm has `n+p-1` (drops first & last). `knots_to_rhino()` handles it. Wrong length = invalid curve, silently.
- **Homogeneous points**: rhino3dm / openNURBS store rational points as `(wx, wy, wz, w)`, not `(x, y, z, w)`. Multiply before writing.
- **Grid order**: geomdl `ctrlpts` are u-major (`i*size_v + j`); input to `fit_surface` is row-major with `rows`=u, `cols`=v. Swapping rows/cols gives a scrambled surface.
- `interpolate_surface` on a 64x64 grid is slow; approximate instead.
- Rhino 7 scripting = IronPython 2.7: no f-strings, no numpy, no pip. `rhino_inside.py` respects that. Rhino 8 `#! python 3` gets CPython but still use RhinoCommon for geometry.
- rhino3dm `Interval` uses `.T0/.T1`, not indexing. Write `.3dm` with version 8 (`f.Write(path, 8)`).
- rhino3dm cannot loft/revolve/boolean (those are Rhino-engine features) - only construct/evaluate/transform NURBS. Do those ops inside Rhino or via `compute.rhino3d.com`.

## Verifying

`pytest tests` round-trips geomdl -> rhino3dm and checks evaluated points match (catches knot/weight bugs). The in-Rhino script cannot be run in a Linux sandbox; test it in Rhino and report errors.

## Ideas for next steps

Mesh/point cloud ingest (Open3D/trimesh -> grid), cylindrical/spherical parameterization for round objects, trimmed surfaces, and the repo's inflatable focus (panels as developable NURBS, seam curves, inflated-shape relaxation).

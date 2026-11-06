# -*- coding: utf-8 -*-
"""NURBS curves / surfaces from points and images, INSIDE Rhino.

Run:  Rhino  >  Tools > Script > Run (RunPythonScript)  >  pick this file
      (Rhino 8: also works from the Script Editor; add `#! python 3` on line 1
       if you want CPython 3 instead of IronPython 2.7 - nothing here needs it.)

Uses only RhinoCommon + System.Drawing, so no pip installs are needed.
Every function returns geometry; `add_*` helpers put it in the document.

Quick tour (call from the Script Editor or edit main()):
    crv = curve_through_points(pts, degree=3)          # passes through points
    crv = curve_from_control_points(pts, degree=3)     # points are the hull
    crv = rebuild_curve(crv, point_count=8)            # smooth / simplify
    srf = surface_from_grid(pts, rows, cols, mode="control")
    grid, rows, cols = image_to_grid(path, width=100, height=100, z_scale=10)
    brep = loft_curves([c1, c2, c3])
    brep = revolve_profile(profile_curve, axis_line)
"""
import math

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import rhinoscriptsyntax as rs
from System.Collections.Generic import List


def _net(items, T):
    """Python list -> .NET List[T] (Rhino 8 Python 3 is picky about bare lists)."""
    out = List[T]()
    for i in items:
        out.Add(i)
    return out


# ---------------------------------------------------------------- curves
def curve_through_points(points, degree=3, closed=False):
    """INTERPOLATED curve: passes exactly through every point."""
    pts = _net(points, rg.Point3d)
    if closed:
        return rg.Curve.CreateInterpolatedCurve(pts, degree, rg.CurveKnotStyle.ChordPeriodic)
    return rg.Curve.CreateInterpolatedCurve(pts, degree)


def curve_from_control_points(points, degree=3, closed=False):
    """CONTROL-POINT curve: points form the control polygon (curve doesn't touch them)."""
    pts = _net(points, rg.Point3d)
    if closed:
        return rg.NurbsCurve.Create(True, degree, pts)   # periodic
    return rg.Curve.CreateControlPointCurve(pts, degree)


def rebuild_curve(curve, point_count=8, degree=3, keep_tangents=False):
    """Re-approximate a curve with `point_count` control points (like _Rebuild)."""
    return curve.Rebuild(point_count, degree, keep_tangents)


def weighted_curve(points, weights, degree=2):
    """True NURBS (rational): per-control-point weights. weight>1 pulls curve closer.

    With degree 2 and weights [1, 0.7071, 1] on a 90 degree corner you get an
    exact circular arc - the classic reason NURBS exist.
    """
    n = len(points)
    c = rg.NurbsCurve(3, True, degree + 1, n)
    for i, p in enumerate(points):
        c.Points.SetPoint(i, p, weights[i])         # SetPoint(i, Point3d, weight)
    # clamped uniform knot vector (RhinoCommon: n + degree - 1 values)
    k = [0.0] * degree + [float(i) for i in range(1, n - degree)] + [float(n - degree)] * degree
    for i, v in enumerate(k):
        c.Knots[i] = v
    return c if c.IsValid else None


# -------------------------------------------------------------- surfaces
def surface_from_grid(points, rows, cols, degree=3, mode="control"):
    """Build a NURBS surface from a rows x cols grid of Point3d (row-major).

    mode:
      "control"     grid = control net. Fast & smooth, surface does NOT touch the
                    points. Best for dense image samples (like 20x20).
      "interpolate" surface passes through every point. Wiggly if noisy, slow
                    if big.
      "rebuild"     interpolate, then rebuild to a lighter control net (~ least
                    squares feel). Use `rebuild_to` below.
    RhinoCommon wants points ordered u-major: index = i*vCount + j; we map
    rows->u, cols->v.
    """
    pts = _net(points, rg.Point3d)
    du, dv = min(degree, rows - 1), min(degree, cols - 1)
    if mode == "control":
        return rg.NurbsSurface.CreateFromPoints(pts, rows, cols, du, dv)
    srf = rg.NurbsSurface.CreateThroughPoints(pts, rows, cols, du, dv, False, False)
    return srf


def rebuild_surface(srf, u_count=12, v_count=12, degree=3):
    """Approximate with a lighter control net (like _RebuildSrf)."""
    return srf.Rebuild(degree, degree, u_count, v_count)


def loft_curves(curves, closed=False, loft_type=rg.LoftType.Normal):
    """Loft through curves -> list of Breps (usually one). Curves should be
    ordered, same direction, similar seam positions."""
    res = rg.Brep.CreateFromLoft(_net(curves, rg.Curve), rg.Point3d.Unset, rg.Point3d.Unset,
                                 loft_type, closed)
    return list(res) if res else []


def revolve_profile(profile, axis_line, start=0.0, end=2 * math.pi, cap=True):
    """Revolve a profile curve around a Line -> Brep (e.g. balloons, columns)."""
    rev = rg.RevSurface.Create(profile, axis_line, start, end)
    return rg.Brep.CreateFromRevSurface(rev, cap, cap) if rev else None


# ------------------------------------------------------- image -> NURBS
def image_to_grid(path, width=100.0, height=100.0, z_scale=10.0,
                  max_samples=24, invert=False):
    """Read an image as a height field (brightness -> Z) with System.Drawing.

    Works on any depth map, e.g. a monocular-depth AI output saved as PNG.
    Returns (points, rows, cols); points are row-major, image top = max Y.
    """
    import System.Drawing as sd
    src = sd.Bitmap(path)
    w, h = src.Width, src.Height
    s = float(max_samples) / max(w, h)
    cols, rows = max(2, int(round(w * s))), max(2, int(round(h * s)))
    small = sd.Bitmap(src, sd.Size(cols, rows))        # GDI+ downsample
    pts = []
    for r in range(rows):
        y = height * (1.0 - r / float(rows - 1))
        for c in range(cols):
            b = small.GetPixel(c, r).GetBrightness()   # 0..1
            if invert:
                b = 1.0 - b
            pts.append(rg.Point3d(width * c / float(cols - 1), y, b * z_scale))
    small.Dispose()
    src.Dispose()
    return pts, rows, cols


# --------------------------------------------------------- doc helpers
def add_curve(c, name=None):
    gid = sc.doc.Objects.AddCurve(c)
    if name and gid:
        rs.ObjectName(gid, name)
    return gid


def add_surface(s, name=None):
    gid = sc.doc.Objects.AddSurface(s)
    if name and gid:
        rs.ObjectName(gid, name)
    return gid


def add_brep(b, name=None):
    gid = sc.doc.Objects.AddBrep(b)
    if name and gid:
        rs.ObjectName(gid, name)
    return gid


def describe(geom):
    """Print degree / control point counts so you can SEE what you built."""
    if isinstance(geom, rg.NurbsCurve):
        print("NurbsCurve  degree=%d  cvs=%d  rational=%s  valid=%s" % (
            geom.Degree, geom.Points.Count, geom.IsRational, geom.IsValid))
    elif isinstance(geom, rg.NurbsSurface):
        print("NurbsSurface degree=(%d,%d)  cvs=%dx%d  rational=%s  valid=%s" % (
            geom.Degree(0), geom.Degree(1), geom.Points.CountU, geom.Points.CountV,
            geom.IsRational, geom.IsValid))


# ------------------------------------------------------------------ main
def main():
    # 1) Curves: same 6 points, interpolated vs control-point
    pts = [rg.Point3d(i * 10, 8 * math.sin(i), 0) for i in range(6)]
    a = curve_through_points(pts)
    b = curve_from_control_points(pts)
    describe(a.ToNurbsCurve()); describe(b.ToNurbsCurve())
    add_curve(a, "interp_curve"); add_curve(b, "controlpt_curve")

    # 2) Exact quarter circle via weights
    s2 = math.sqrt(0.5)
    arc = weighted_curve([rg.Point3d(30, 0, 0), rg.Point3d(30, 30, 0),
                          rg.Point3d(0, 30, 0)], [1, s2, 1], degree=2)
    describe(arc); add_curve(arc, "weighted_arc")

    # 3) Image -> NURBS relief surface
    path = rs.OpenFileName("Pick an image / depth map (Cancel = demo bump)",
                           "Images|*.png;*.jpg;*.jpeg;*.bmp||")
    if path:
        grid, rows, cols = image_to_grid(path, 100, 100, 10, max_samples=24)
    else:
        rows = cols = 20
        grid = [rg.Point3d(c * 5, r * 5, 8 * math.sin(c / 3.0) * math.cos(r / 3.0))
                for r in range(rows) for c in range(cols)]
    srf = surface_from_grid(grid, rows, cols, mode="control")
    describe(srf); add_surface(srf, "relief_surface")

    sc.doc.Views.Redraw()


if __name__ == "__main__":
    main()

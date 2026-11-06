#!/usr/bin/env python3
"""Image / point data -> NURBS -> Rhino .3dm, WITHOUT Rhino running.

Pipeline:   image (or AI depth map / XYZ grid)  ->  point grid
            ->  geomdl least-squares / interpolating fit
            ->  rhino3dm NurbsSurface  ->  .3dm you can open in Rhino.

Install:    pip install geomdl rhino3dm pillow numpy
Examples:   python nurbs_offline.py demo out.3dm
            python nurbs_offline.py heightmap depth.png out.3dm --width 400 --height 60
            python nurbs_offline.py xyzgrid points.txt out.3dm --cols 20 --rows 15

Key gotcha handled here: geomdl knot vectors have n+p+1 values, Rhino/openNURBS
knot vectors have n+p-1 (first and last knot dropped). See knots_to_rhino().
"""
import argparse
import math
import sys

import numpy as np
import rhino3dm
from geomdl import BSpline, NURBS, fitting


# --------------------------------------------------------------------------
# Fitting (geomdl)
# --------------------------------------------------------------------------
def fit_curve(points, degree=3, ctrl=None):
    """Fit a B-spline curve through `points` (list of [x,y,z]).

    ctrl=None  -> interpolate (curve passes through every point)
    ctrl=int   -> least-squares approximation with that many control points
                  (smooths noise; ctrl must be > degree and <= len(points))
    """
    pts = [list(map(float, p)) for p in points]
    if ctrl is None:
        return fitting.interpolate_curve(pts, degree)
    return fitting.approximate_curve(pts, degree, ctrlpts_size=int(ctrl))


def fit_surface(grid, rows, cols, degree=3, ctrl_u=None, ctrl_v=None):
    """Fit a B-spline surface to a regular grid of points.

    grid   : flat list of [x,y,z], ordered v-major (rows of `cols` points).
             i.e. index = row * cols + col.
    rows   : number of rows    (size_u in geomdl terms)
    cols   : number of columns (size_v)
    ctrl_* : None -> interpolate every point (heavy for big grids!)
             int  -> least-squares approximation with that many control
                     points per direction (what you want for images).
    """
    pts = [list(map(float, p)) for p in grid]
    if len(pts) != rows * cols:
        raise ValueError("grid has %d points, expected %d*%d" % (len(pts), rows, cols))
    du = min(degree, rows - 1)
    dv = min(degree, cols - 1)
    if ctrl_u is None and ctrl_v is None:
        return fitting.interpolate_surface(pts, rows, cols, du, dv)
    cu = int(ctrl_u or rows)
    cv = int(ctrl_v or cols)
    return fitting.approximate_surface(pts, rows, cols, du, dv,
                                       ctrlpts_size_u=cu, ctrlpts_size_v=cv)


# --------------------------------------------------------------------------
# Image -> point grid
# --------------------------------------------------------------------------
def heightmap_to_grid(path, width=100.0, height=100.0, z_scale=10.0,
                      max_samples=64, invert=False, blur=1.0):
    """Read an image as a heightfield. Brightness -> Z.

    Returns (grid, rows, cols). The image is resampled so its longest side has
    at most `max_samples` samples (a fit with 64x64 samples is already ~4k pts).
    Works with any depth map: a monocular-depth AI output (MiDaS, Depth Anything,
    ...) saved as PNG is exactly what this expects.
    """
    from PIL import Image, ImageFilter

    img = Image.open(path).convert("L")
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    w, h = img.size
    s = max_samples / float(max(w, h))
    if s < 1.0:
        img = img.resize((max(2, int(round(w * s))), max(2, int(round(h * s)))),
                         Image.LANCZOS)
    a = np.asarray(img, dtype=float) / 255.0
    if invert:
        a = 1.0 - a
    rows, cols = a.shape
    grid = []
    for r in range(rows):
        y = height * (1.0 - r / float(rows - 1))      # image row 0 = top
        for c in range(cols):
            x = width * c / float(cols - 1)
            grid.append([x, y, a[r, c] * z_scale])
    return grid, rows, cols


def read_xyz_grid(path, rows=None, cols=None):
    """Load whitespace/comma separated XYZ text, already ordered as a grid."""
    data = np.loadtxt(path, delimiter=None if "," not in open(path).read(2000) else ",")
    if rows is None or cols is None:
        raise ValueError("--rows and --cols are required for xyzgrid")
    return data.tolist(), rows, cols


# --------------------------------------------------------------------------
# geomdl -> rhino3dm
# --------------------------------------------------------------------------
def knots_to_rhino(kv):
    """geomdl knot vector (n+p+1) -> openNURBS knot vector (n+p-1)."""
    kv = list(kv)
    return kv[1:-1]


def _weights(geom):
    w = getattr(geom, "weights", None)
    return list(w) if w else None


def curve_to_rhino3dm(crv):
    pts = crv.ctrlpts
    w = _weights(crv)
    order = crv.degree + 1
    out = rhino3dm.NurbsCurve(3, w is not None, order, len(pts))
    for i, p in enumerate(pts):
        if w is None:
            out.Points[i] = rhino3dm.Point4d(p[0], p[1], p[2], 1.0)
        else:  # openNURBS stores homogeneous (wx, wy, wz, w)
            out.Points[i] = rhino3dm.Point4d(p[0] * w[i], p[1] * w[i], p[2] * w[i], w[i])
    for i, k in enumerate(knots_to_rhino(crv.knotvector)):
        out.Knots[i] = k
    return out


def surface_to_rhino3dm(srf):
    """geomdl surface -> rhino3dm.NurbsSurface.

    geomdl ctrlpts are u-major: index = i * size_v + j  (i along u, j along v).
    """
    nu, nv = srf.ctrlpts_size_u, srf.ctrlpts_size_v
    w = _weights(srf)
    out = rhino3dm.NurbsSurface.Create(3, w is not None,
                                       srf.degree_u + 1, srf.degree_v + 1, nu, nv)
    for i in range(nu):
        for j in range(nv):
            k = i * nv + j
            p = srf.ctrlpts[k]
            if w is None:
                out.Points[i, j] = rhino3dm.Point4d(p[0], p[1], p[2], 1.0)
            else:
                out.Points[i, j] = rhino3dm.Point4d(p[0] * w[k], p[1] * w[k], p[2] * w[k], w[k])
    for i, k in enumerate(knots_to_rhino(srf.knotvector_u)):
        out.KnotsU[i] = k
    for i, k in enumerate(knots_to_rhino(srf.knotvector_v)):
        out.KnotsV[i] = k
    return out


def write_3dm(path, geometries, layer_names=None):
    """Write rhino3dm geometry objects to a .3dm (Rhino 8 format)."""
    f = rhino3dm.File3dm()
    for i, g in enumerate(geometries):
        attr = rhino3dm.ObjectAttributes()
        if layer_names:
            attr.Name = layer_names[i]
        f.Objects.Add(g, attr)
    ok = f.Write(path, 8)
    if not ok:
        raise IOError("could not write %s" % path)
    return path


# --------------------------------------------------------------------------
# Demo + CLI
# --------------------------------------------------------------------------
def demo_geometry():
    """A fitted curve + a fitted bumpy surface (no input files needed)."""
    t = np.linspace(0, 2 * math.pi, 24)
    crv_pts = [[20 * math.cos(a), 20 * math.sin(a), 3 * a] for a in t]
    crv = fit_curve(crv_pts, degree=3)

    rows = cols = 24
    grid = []
    for r in range(rows):
        for c in range(cols):
            x, y = c * 5.0, r * 5.0
            z = 8 * math.sin(x / 18.0) * math.cos(y / 14.0)
            grid.append([x, y, z])
    srf = fit_surface(grid, rows, cols, degree=3, ctrl_u=10, ctrl_v=10)
    return crv, srf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="write a demo curve + surface")
    d.add_argument("out")

    h = sub.add_parser("heightmap", help="image/depth map -> NURBS surface")
    h.add_argument("image")
    h.add_argument("out")
    h.add_argument("--width", type=float, default=100.0, help="model width (units)")
    h.add_argument("--height", type=float, default=100.0, help="model height (units)")
    h.add_argument("--z-scale", type=float, default=10.0, help="max relief height")
    h.add_argument("--samples", type=int, default=64, help="max samples on longest side")
    h.add_argument("--ctrl", type=int, default=16, help="control points per direction")
    h.add_argument("--degree", type=int, default=3)
    h.add_argument("--invert", action="store_true")
    h.add_argument("--blur", type=float, default=1.0)

    x = sub.add_parser("xyzgrid", help="ordered XYZ grid text file -> NURBS surface")
    x.add_argument("points")
    x.add_argument("out")
    x.add_argument("--rows", type=int, required=True)
    x.add_argument("--cols", type=int, required=True)
    x.add_argument("--ctrl", type=int, default=None, help="omit to interpolate")
    x.add_argument("--degree", type=int, default=3)

    a = ap.parse_args(argv)
    if a.cmd == "demo":
        crv, srf = demo_geometry()
        write_3dm(a.out, [curve_to_rhino3dm(crv), surface_to_rhino3dm(srf)])
    elif a.cmd == "heightmap":
        grid, rows, cols = heightmap_to_grid(a.image, a.width, a.height, a.z_scale,
                                             a.samples, a.invert, a.blur)
        srf = fit_surface(grid, rows, cols, a.degree,
                          min(a.ctrl, rows), min(a.ctrl, cols))
        write_3dm(a.out, [surface_to_rhino3dm(srf)])
    else:
        grid, rows, cols = read_xyz_grid(a.points, a.rows, a.cols)
        srf = fit_surface(grid, rows, cols, a.degree, a.ctrl, a.ctrl)
        write_3dm(a.out, [surface_to_rhino3dm(srf)])
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

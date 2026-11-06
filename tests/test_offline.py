import math, os, sys
import numpy as np
import pytest
import rhino3dm
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nurbs_offline as n


def test_knot_conversion_length():
    crv, srf = n.demo_geometry()
    assert len(n.knots_to_rhino(crv.knotvector)) == len(crv.ctrlpts) + crv.degree - 1


def test_curve_roundtrip_matches_geomdl():
    crv, _ = n.demo_geometry()
    r = n.curve_to_rhino3dm(crv)
    assert r.IsValid
    for t in (0.0, 0.3, 0.77, 1.0):
        g = crv.evaluate_single(t)
        d = r.Domain
        p = r.PointAt(d.T0 + t * (d.T1 - d.T0))
        assert (p.X - g[0]) ** 2 + (p.Y - g[1]) ** 2 + (p.Z - g[2]) ** 2 < 1e-12


def test_surface_roundtrip_matches_geomdl(tmp_path):
    _, srf = n.demo_geometry()
    r = n.surface_to_rhino3dm(srf)
    assert r.IsValid
    for u, v in ((0, 0), (0.5, 0.5), (0.2, 0.9), (1, 1)):
        g = srf.evaluate_single((u, v))
        du, dv = r.Domain(0), r.Domain(1)
        p = r.PointAt(du.T0 + u * (du.T1 - du.T0), dv.T0 + v * (dv.T1 - dv.T0))
        assert abs(p.X - g[0]) + abs(p.Y - g[1]) + abs(p.Z - g[2]) < 1e-9
    out = str(tmp_path / "x.3dm")
    n.write_3dm(out, [r])
    assert rhino3dm.File3dm.Read(out).Objects[0].Geometry.IsValid


def test_heightmap_pipeline(tmp_path):
    from PIL import Image
    yy, xx = np.mgrid[0:80, 0:120]
    img = (255 * (0.5 + 0.5 * np.sin(xx / 15.0) * np.cos(yy / 10.0))).astype("uint8")
    p = str(tmp_path / "h.png")
    Image.fromarray(img).save(p)
    out = str(tmp_path / "o.3dm")
    assert n.main(["heightmap", p, out, "--ctrl", "12", "--samples", "40"]) == 0
    g = rhino3dm.File3dm.Read(out).Objects[0].Geometry
    assert g.IsValid
    bb = g.GetBoundingBox()
    assert 90 < bb.Max.X - bb.Min.X < 110  # width ~100

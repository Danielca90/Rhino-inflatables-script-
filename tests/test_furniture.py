import math, os, sys, types
from unittest import mock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import furniture_parametric as fp

KINDS = list(fp.PARAMS)


@pytest.mark.parametrize("kind", KINDS)
def test_defaults_build_and_stand_on_floor(kind):
    parts = fp.build_parts(kind)
    assert parts
    lo, hi = fp.bbox(parts)
    assert lo[2] == pytest.approx(0.0, abs=1e-6)
    for p in parts:
        if p["kind"] == "box":
            x0, x1, y0, y1, z0, z1 = p["box"]
            assert x1 > x0 and y1 > y0 and z1 > z0


@pytest.mark.parametrize("kind", KINDS)
def test_extreme_and_garbage_values_never_crash(kind):
    for pick in ("min", "max"):
        vals = {p["key"]: p[pick] for p in fp.PARAMS[kind] if p["kind"] != "choice"}
        assert fp.build_parts(kind, vals)
    assert fp.build_parts(kind, {p["key"]: "abc" for p in fp.PARAMS[kind]})
    assert fp.build_parts(kind, {p["key"]: 1e9 for p in fp.PARAMS[kind] if p["kind"] != "choice"})


def test_table_overall_size_follows_params():
    for w, d, h in ((1200, 700, 720), (2400, 1000, 760)):
        lo, hi = fp.bbox(fp.build_parts("table", dict(width=w, depth=d, height=h)))
        assert hi[0] - lo[0] == pytest.approx(w)
        assert hi[1] - lo[1] == pytest.approx(d)
        assert hi[2] == pytest.approx(h)


@pytest.mark.parametrize("style,kind", [("square", "box"), ("tapered", "taper"), ("round", "cyl")])
def test_table_leg_styles(style, kind):
    legs = [p for p in fp.build_parts("table", {"leg_style": style}) if p["group"] == "Legs"]
    assert len(legs) == 4 and all(p["kind"] == kind for p in legs)


def test_table_apron_toggle():
    assert not [p for p in fp.build_parts("table", {"apron_h": 0}) if p["group"] == "Aprons"]
    assert len([p for p in fp.build_parts("table") if p["group"] == "Aprons"]) == 4


def test_chair_seat_height_and_back_tilt():
    parts = fp.build_parts("chair", {"seat_h": 470, "back_h": 400, "back_tilt": 0})
    seat = next(p for p in parts if p["name"] == "Seat")
    assert seat["box"][5] == 470
    top0 = fp.bbox(parts)[1]
    tilted = fp.bbox(fp.build_parts("chair", {"seat_h": 470, "back_h": 400, "back_tilt": 15}))[1]
    assert tilted[1] > top0[1]                       # leans toward rear (+Y)
    a = math.radians(15)   # top corner of the 38 mm post also rises by (s/2)*sin(a)
    assert tilted[2] == pytest.approx(470 + 400 * math.cos(a) + 19 * math.sin(a), abs=0.01)


def test_chair_slats_count():
    assert len([p for p in fp.build_parts("chair", {"slats": 5}) if p["name"] == "Back slat"]) == 5
    assert [p for p in fp.build_parts("chair", {"slats": 0}) if p["name"] == "Back panel"]


def test_bookshelf_even_spacing_and_count():
    parts = fp.build_parts("bookshelf", {"shelves": 4})
    shelves = sorted((p for p in parts if p["name"].startswith("Shelf")),
                     key=lambda p: p["box"][4])
    assert len(shelves) == 4
    bottom = next(p for p in parts if p["name"] == "Bottom")
    top = next(p for p in parts if p["name"] == "Top")
    edges = [bottom["box"][5]] + sum(([s["box"][4], s["box"][5]] for s in shelves), []) + [top["box"][4]]
    gaps = [edges[i + 1] - edges[i] for i in range(0, len(edges), 2)]
    assert max(gaps) - min(gaps) < 1e-6


def test_bookshelf_caps_shelves_so_gaps_stay_usable():
    parts = fp.build_parts("bookshelf", {"height": 300, "shelves": 12})
    assert len([p for p in parts if p["name"].startswith("Shelf")]) < 12


def test_cut_list_groups_and_csv(tmp_path):
    rows = fp.cut_list(fp.build_parts("bookshelf", {"shelves": 3}))
    assert next(r for r in rows if r["part"] == "Shelf")["qty"] == 3
    out = tmp_path / "c.csv"
    fp.save_cut_list_csv(fp.build_parts("table"), str(out))
    assert out.read_text().splitlines()[0] == "qty,part,size_mm"


# ---- smoke test of the Rhino/Eto layer against stand-in modules ----------
def test_rhino_and_ui_layers_run_against_mocks(monkeypatch):
    m = mock.MagicMock()
    for attr, val in dict(IN_RHINO=True, Rhino=m, rg=m, sc=m, rs=m, List=mock.MagicMock()).items():
        monkeypatch.setattr(fp, attr, val, raising=False)
    sc = fp.sc
    sc.sticky = {}
    sc.doc.Objects.AddBrep.side_effect = lambda b: object()
    # every kind of part realizes and gets added
    for kind in KINDS:
        s = fp.Session(kind)
        s.rebuild()
        assert len(s.ids) == len(s.parts)
        s.rebuild()                                   # redraw deletes previous
        assert sc.doc.Objects.Delete.called
        assert "mm" in s.size_text()
        s.keep()
        assert s.ids == []
    for style in fp.LEG_STYLES:
        assert fp.realize(fp.build_parts("table", {"leg_style": style})[1]) is not None
    # UI construction path (event wiring, panel swap) must not raise
    fp.show_ui.__globals__["traceback"] = fp.traceback
    ef = mock.MagicMock()
    sys.modules["Eto"] = mock.MagicMock(Forms=ef, Drawing=mock.MagicMock())
    sys.modules["Eto.Forms"] = ef
    sys.modules["Eto.Drawing"] = mock.MagicMock()
    fp.show_ui()
    assert "parametric_furniture_form" in sc.sticky

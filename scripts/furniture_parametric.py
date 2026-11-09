# -*- coding: utf-8 -*-
"""Parametric furniture for Rhino 7 and 8 (Mac + Windows).

Works on Rhino 7 (IronPython 2.7) and Rhino 8 (IronPython or Python 3): no f-strings,
no numpy, no pip installs.

Run (Rhino 7):  Tools > PythonScript > Run...  > pick this file
Run (Rhino 8):  Tools > Script > Run Python Script...  (or Script Editor > Run)
A floating panel appears. Move a slider / type a value and the piece is
deleted and redrawn automatically. Pieces: table, chair, bookshelf.
Units: millimetres, Z up, piece centred on X/Y origin, standing on Z=0.

Design: two layers so the logic can be tested without Rhino
  1. SPEC layer (pure Python)  params -> list of part dicts (+ cut list, bbox)
  2. RHINO layer               part dicts -> Breps on layers, Eto panel, redraw
From the Script Editor you can also skip the UI:
    import furniture_parametric as fp; fp.build_in_rhino("table", width=2000)
"""
from __future__ import division   # IronPython 2.7: make / true division

import csv
import math
import sys
import traceback

try:
    import Rhino
    import Rhino.Geometry as rg
    import Rhino.UI
    import scriptcontext as sc
    import rhinoscriptsyntax as rs
    from System.Collections.Generic import List
    IN_RHINO = True
except ImportError:          # plain Python: spec layer + tests still work
    IN_RHINO = False

# ======================================================================
# 1. PARAMETER DEFINITIONS
# ======================================================================
LEG_STYLES = ["square", "tapered", "round"]


def P(key, label, lo, hi, default, step=1.0, kind="float", choices=None):
    return {"key": key, "label": label, "min": lo, "max": hi, "default": default,
            "step": step, "kind": kind, "choices": choices}


PARAMS = {
    "table": [
        P("width", "Width", 600, 3000, 1600, 10),
        P("depth", "Depth", 400, 1200, 800, 10),
        P("height", "Height", 400, 1100, 740, 5),
        P("top_t", "Top thickness", 15, 80, 30, 1),
        P("leg_size", "Leg size", 30, 120, 60, 1),
        P("leg_style", "Leg style", 0, 0, "square", kind="choice", choices=LEG_STYLES),
        P("taper", "Taper (foot/top)", 0.3, 1.0, 0.6, 0.05),
        P("inset", "Leg inset", 0, 300, 40, 5),
        P("apron_h", "Apron height (0=none)", 0, 200, 80, 5),
        P("apron_t", "Apron thickness", 10, 40, 20, 1),
    ],
    "chair": [
        P("seat_w", "Seat width", 300, 700, 450, 5),
        P("seat_d", "Seat depth", 300, 650, 440, 5),
        P("seat_h", "Seat height", 300, 600, 450, 5),
        P("seat_t", "Seat thickness", 15, 80, 35, 1),
        P("leg_size", "Leg size", 20, 70, 38, 1),
        P("leg_style", "Leg style", 0, 0, "tapered", kind="choice", choices=LEG_STYLES),
        P("taper", "Taper (foot/top)", 0.3, 1.0, 0.65, 0.05),
        P("back_h", "Back height (0=none)", 0, 800, 420, 10),
        P("back_tilt", "Back tilt (deg)", 0, 25, 8, 1),
        P("back_t", "Back panel thickness", 10, 50, 22, 1),
        P("slats", "Back slats (0=solid)", 0, 8, 0, 1, kind="int"),
    ],
    "bookshelf": [
        P("width", "Width", 300, 2000, 800, 10),
        P("height", "Height", 300, 2400, 1800, 10),
        P("depth", "Depth", 150, 600, 300, 5),
        P("t", "Board thickness", 12, 40, 18, 1),
        P("shelves", "Shelves", 0, 12, 4, 1, kind="int"),
        P("plinth_h", "Plinth height (0=none)", 0, 150, 60, 5),
        P("back_t", "Back panel (0=none)", 0, 12, 6, 1),
    ],
}


def defaults(kind):
    return {p["key"]: p["default"] for p in PARAMS[kind]}


def clean(kind, values=None):
    """Merge with defaults, clamp to limits, fix types. Never raises on bad numbers."""
    out = defaults(kind)
    for p in PARAMS[kind]:
        k = p["key"]
        if values and k in values:
            v = values[k]
            if p["kind"] == "choice":
                out[k] = v if v in p["choices"] else p["default"]
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = p["default"]
            v = min(max(v, p["min"]), p["max"])
            out[k] = int(round(v)) if p["kind"] == "int" else v
    return out


# ======================================================================
# 2. SPEC LAYER: params -> parts
# ======================================================================
def _box(name, group, x0, x1, y0, y1, z0, z1, tilt=0.0, pivot=(0.0, 0.0)):
    return {"name": name, "group": group, "kind": "box",
            "box": (min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1),
                    min(z0, z1), max(z0, z1)),
            "tilt": tilt, "pivot": pivot}


def _leg(name, style, cx, cy, z0, z1, size, taper):
    h = (z1 - z0)
    if style == "round":
        return {"name": name, "group": "Legs", "kind": "cyl",
                "cx": cx, "cy": cy, "z0": z0, "z1": z1, "r": size / 2.0}
    if style == "tapered":
        return {"name": name, "group": "Legs", "kind": "taper", "cx": cx, "cy": cy,
                "z0": z0, "z1": z1, "top": size, "bottom": size * taper}
    return _box(name, "Legs", cx - size / 2, cx + size / 2, cy - size / 2, cy + size / 2, z0, z1)


def build_table(v):
    w, d, h, tt, s = v["width"], v["depth"], v["height"], v["top_t"], v["leg_size"]
    leg_h = h - tt
    inset = min(v["inset"], max(0.0, min(w, d) / 2.0 - s))
    cx, cy = w / 2.0 - inset - s / 2.0, d / 2.0 - inset - s / 2.0
    parts = [_box("Top", "Top", -w / 2, w / 2, -d / 2, d / 2, leg_h, h)]
    n = 0
    for sx in (-1, 1):
        for sy in (-1, 1):
            n += 1
            parts.append(_leg("Leg %d" % n, v["leg_style"], sx * cx, sy * cy, 0.0, leg_h,
                              s, v["taper"]))
    if v["apron_h"] > 0 and cx > s / 2.0 and cy > s / 2.0:
        z0, z1, at = leg_h - min(v["apron_h"], leg_h), leg_h, v["apron_t"]
        for sy in (-1, 1):   # long aprons, flush with leg outer faces
            o = sy * (cy + s / 2.0)
            parts.append(_box("Apron long", "Aprons", -cx + s / 2, cx - s / 2,
                              o, o - sy * at, z0, z1))
        for sx in (-1, 1):   # short aprons
            o = sx * (cx + s / 2.0)
            parts.append(_box("Apron short", "Aprons", o, o - sx * at,
                              -cy + s / 2, cy - s / 2, z0, z1))
    return parts


def build_chair(v):
    w, d, sh, st, s = v["seat_w"], v["seat_d"], v["seat_h"], v["seat_t"], v["leg_size"]
    leg_h = sh - st
    cx, cy = w / 2.0 - s / 2.0 - 10.0, d / 2.0 - s / 2.0 - 10.0
    parts = [_box("Seat", "Seat", -w / 2, w / 2, -d / 2, d / 2, leg_h, sh)]
    n = 0
    for sx in (-1, 1):
        for sy in (-1, 1):       # rear = +Y
            n += 1
            parts.append(_leg("Leg %d" % n, v["leg_style"], sx * cx, sy * cy, 0.0, leg_h,
                              s, v["taper"]))
    bh = v["back_h"]
    if bh > 0:
        tilt, piv = v["back_tilt"], (cy, sh)       # lean back about seat-top rear
        for sx in (-1, 1):
            parts.append(_box("Back post", "Back", sx * cx - s / 2, sx * cx + s / 2,
                              cy - s / 2, cy + s / 2, sh, sh + bh, tilt, piv))
        inner0, inner1 = -cx + s / 2, cx - s / 2
        z0, z1 = sh + bh * 0.45, sh + bh * 0.95
        t, k = v["back_t"], v["slats"]
        if k == 0:
            parts.append(_box("Back panel", "Back", inner0, inner1, cy - t / 2, cy + t / 2,
                              z0, z1, tilt, piv))
        else:
            gap = 20.0
            sw = max(5.0, ((inner1 - inner0) - gap * (k + 1)) / k)
            for i in range(k):
                x0 = inner0 + gap + i * (sw + gap)
                parts.append(_box("Back slat", "Back", x0, x0 + sw, cy - t / 2, cy + t / 2,
                                  z0, z1, tilt, piv))
    return parts


def build_bookshelf(v):
    w, h, d, t = v["width"], v["height"], v["depth"], v["t"]
    ph, bt = v["plinth_h"], v["back_t"]
    iw0, iw1 = -w / 2 + t, w / 2 - t                  # inner width span
    yf, yb = -d / 2, d / 2 - bt                       # front, front of back panel
    parts = [_box("Side L", "Carcass", -w / 2, -w / 2 + t, -d / 2, d / 2, 0, h),
             _box("Side R", "Carcass", w / 2 - t, w / 2, -d / 2, d / 2, 0, h),
             _box("Bottom", "Carcass", iw0, iw1, yf, yb, ph, ph + t),
             _box("Top", "Carcass", iw0, iw1, yf, yb, h - t, h)]
    z0, z1 = ph + t, h - t
    max_n = int(max(0, math.floor(((z1 - z0) - 80.0) / (t + 80.0))))
    n = min(v["shelves"], max_n)
    gap = ((z1 - z0) - n * t) / (n + 1)
    for i in range(n):
        zb = z0 + gap * (i + 1) + t * i
        parts.append(_box("Shelf %d" % (i + 1), "Shelves", iw0, iw1, yf, yb, zb, zb + t))
    if bt > 0:
        parts.append(_box("Back panel", "Back", iw0, iw1, d / 2 - bt, d / 2, ph, h))
    if ph > 0:
        parts.append(_box("Plinth", "Carcass", iw0, iw1, yf + 30.0, yb, 0, ph))
    return parts


BUILDERS = {"table": build_table, "chair": build_chair, "bookshelf": build_bookshelf}


def build_parts(kind, values=None):
    return BUILDERS[kind](clean(kind, values))


# ---- queries on a spec (also used by tests) ---------------------------
def _rot(y, z, tilt, pivot):
    if not tilt:
        return y, z
    f = -math.radians(tilt)          # tilting back = rotate -tilt about +X
    py, pz = pivot
    dy, dz = y - py, z - pz
    return (py + dy * math.cos(f) - dz * math.sin(f),
            pz + dy * math.sin(f) + dz * math.cos(f))


def corners(p):
    """Points that bound a part, after tilt (x, y, z)."""
    if p["kind"] == "box":
        x0, x1, y0, y1, z0, z1 = p["box"]
        pts = []
        for x in (x0, x1):
            for y in (y0, y1):
                for z in (z0, z1):
                    yy, zz = _rot(y, z, p["tilt"], p["pivot"])
                    pts.append((x, yy, zz))
        return pts
    r = p["r"] if p["kind"] == "cyl" else p["top"] / 2.0
    return [(p["cx"] + sx * r, p["cy"] + sy * r, z)
            for sx in (-1, 1) for sy in (-1, 1) for z in (p["z0"], p["z1"])]


def bbox(parts):
    pts = [c for p in parts for c in corners(p)]
    lo = tuple(min(c[i] for c in pts) for i in range(3))
    hi = tuple(max(c[i] for c in pts) for i in range(3))
    return lo, hi


def cut_list(parts):
    """Group identical parts. Boxes -> L x W x T; turned/tapered legs described."""
    rows = {}
    for p in parts:
        if p["kind"] == "box":
            x0, x1, y0, y1, z0, z1 = p["box"]
            dims = sorted([x1 - x0, y1 - y0, z1 - z0], reverse=True)
            desc = "%.0f x %.0f x %.0f" % tuple(dims)
        elif p["kind"] == "cyl":
            desc = "dia %.0f x %.0f long" % (p["r"] * 2, p["z1"] - p["z0"])
        else:
            desc = "tapered %.0f->%.0f sq x %.0f long" % (p["top"], p["bottom"], p["z1"] - p["z0"])
        key = (p["name"].rstrip("0123456789 ") or p["name"], desc)
        rows[key] = rows.get(key, 0) + 1
    return [{"qty": q, "part": k[0], "size_mm": k[1]} for k, q in sorted(rows.items())]


def cut_list_text(parts):
    rows = cut_list(parts)
    return "\n".join("%2d x  %-12s %s" % (r["qty"], r["part"], r["size_mm"]) for r in rows)


def save_cut_list_csv(parts, path):
    if sys.version_info[0] >= 3:
        f = open(path, "w", newline="")
    else:                                   # IronPython 2.7: csv wants binary mode
        f = open(path, "wb")
    with f:
        wr = csv.DictWriter(f, fieldnames=["qty", "part", "size_mm"])
        wr.writeheader()
        wr.writerows(cut_list(parts))


# ======================================================================
# 3. RHINO LAYER: spec -> Breps
# ======================================================================
GROUP_COLORS = {"Top": (150, 105, 60), "Legs": (110, 75, 45), "Aprons": (130, 90, 50),
                "Seat": (150, 105, 60), "Back": (125, 85, 50), "Carcass": (170, 125, 80),
                "Shelves": (190, 145, 95)}
ROOT_LAYER = "Parametric Furniture"


def _rect_curve(cx, cy, z, size):
    h = size / 2.0
    pl = rg.Polyline(5)
    for x, y in ((-h, -h), (h, -h), (h, h), (-h, h), (-h, -h)):
        pl.Add(cx + x, cy + y, z)
    return pl.ToNurbsCurve()


def realize(p):
    """One spec part -> Rhino Brep (or None)."""
    if p["kind"] == "box":
        x0, x1, y0, y1, z0, z1 = p["box"]
        brep = rg.Box(rg.Plane.WorldXY, rg.Interval(x0, x1), rg.Interval(y0, y1),
                      rg.Interval(z0, z1)).ToBrep()
        if p["tilt"]:
            xf = rg.Transform.Rotation(-math.radians(p["tilt"]), rg.Vector3d.XAxis,
                                       rg.Point3d(0, p["pivot"][0], p["pivot"][1]))
            brep.Transform(xf)
        return brep
    if p["kind"] == "cyl":
        circle = rg.Circle(rg.Plane(rg.Point3d(p["cx"], p["cy"], p["z0"]), rg.Vector3d.ZAxis),
                           p["r"])
        return rg.Cylinder(circle, p["z1"] - p["z0"]).ToBrep(True, True)
    curves = List[rg.Curve]()
    curves.Add(_rect_curve(p["cx"], p["cy"], p["z0"], p["bottom"]))
    curves.Add(_rect_curve(p["cx"], p["cy"], p["z1"], p["top"]))
    lofts = rg.Brep.CreateFromLoft(curves, rg.Point3d.Unset, rg.Point3d.Unset,
                                   rg.LoftType.Straight, False)
    if not lofts:
        return None
    capped = lofts[0].CapPlanarHoles(sc.doc.ModelAbsoluteTolerance)
    return capped or lofts[0]


def _ensure_layer(group):
    if not rs.IsLayer(ROOT_LAYER):
        rs.AddLayer(ROOT_LAYER)
    full = ROOT_LAYER + "::" + group
    if not rs.IsLayer(full):
        rs.AddLayer(group, GROUP_COLORS.get(group, (140, 100, 60)), parent=ROOT_LAYER)
    return full


class Session(object):
    """Holds current piece type, values and the Rhino objects it drew."""

    def __init__(self, kind="table"):
        self.kind = kind
        self.values = {k: defaults(k) for k in PARAMS}
        self.ids = []
        self.parts = []

    def clear(self):
        for gid in self.ids:
            sc.doc.Objects.Delete(gid, True)
        self.ids = []

    def rebuild(self):
        sc.doc = Rhino.RhinoDoc.ActiveDoc
        self.clear()
        self.parts = build_parts(self.kind, self.values[self.kind])
        sc.doc.Views.RedrawEnabled = False
        try:
            for p in self.parts:
                brep = realize(p)
                if brep is None:
                    continue
                gid = sc.doc.Objects.AddBrep(brep)
                rs.ObjectLayer(gid, _ensure_layer(p["group"]))
                rs.ObjectName(gid, p["name"])
                self.ids.append(gid)
        finally:
            sc.doc.Views.RedrawEnabled = True
        sc.doc.Views.Redraw()

    def keep(self):
        """Stop tracking: current piece stays in the model, grouped; next change starts a new one."""
        if self.ids:
            g = rs.AddGroup(self.kind.capitalize())
            rs.AddObjectsToGroup(self.ids, g)
        self.ids = []

    def size_text(self):
        lo, hi = bbox(self.parts)
        return "%.0f W x %.0f D x %.0f H mm" % (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


def build_in_rhino(kind="table", **overrides):
    """No-UI helper: draw one piece with parameter overrides and keep it."""
    s = Session(kind)
    s.values[kind] = clean(kind, overrides)
    s.rebuild()
    print(cut_list_text(s.parts))
    s.keep()
    return s


# ======================================================================
# 4. ETO PANEL (live redraw)
# ======================================================================
def show_ui():
    import Eto.Forms as ef
    import Eto.Drawing as ed

    old = sc.sticky.get("parametric_furniture_form")
    if old is not None:
        try:
            old.Close()
        except Exception:
            pass

    session = Session("table")
    session.rebuild()

    form = ef.Form()
    form.Title = "Parametric Furniture"
    form.Padding = ed.Padding(12)
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Resizable = False

    holder = ef.Panel()
    info = ef.Label()
    state = {"busy": False}

    timer = ef.UITimer()
    timer.Interval = 0.12          # debounce: redraw 120 ms after the last change

    def on_tick(sender, e):
        timer.Stop()
        try:
            session.rebuild()
            info.Text = session.size_text()
        except Exception:
            Rhino.RhinoApp.WriteLine("Furniture rebuild failed:\n" + traceback.format_exc())

    timer.Elapsed += on_tick

    def changed():
        timer.Stop()
        timer.Start()

    def make_row(layout, p):
        key = p["key"]
        vals = session.values[session.kind]
        label = ef.Label()
        label.Text = p["label"]
        label.Width = 150
        if p["kind"] == "choice":
            dd = ef.DropDown()
            for c in p["choices"]:
                dd.Items.Add(ef.ListItem())
                dd.Items[dd.Items.Count - 1].Text = c
                dd.Items[dd.Items.Count - 1].Key = c
            dd.SelectedKey = vals[key]

            def on_dd(sender, e):
                vals[key] = sender.SelectedKey
                changed()
            dd.SelectedIndexChanged += on_dd
            layout.AddRow(label, dd)
            return
        scale = 1.0 / p["step"]
        slider = ef.Slider()
        slider.MinValue = int(round(p["min"] * scale))
        slider.MaxValue = int(round(p["max"] * scale))
        slider.Value = int(round(vals[key] * scale))
        slider.Width = 200
        stepper = ef.NumericStepper()
        stepper.MinValue, stepper.MaxValue = float(p["min"]), float(p["max"])
        stepper.Increment = float(p["step"])
        stepper.DecimalPlaces = 0 if p["step"] >= 1 else 2
        stepper.Value = float(vals[key])
        stepper.Width = 80

        def apply(v):
            vals[key] = int(round(v)) if p["kind"] == "int" else float(v)
            changed()

        def on_slider(sender, e):
            if state["busy"]:
                return
            state["busy"] = True
            v = sender.Value / scale
            stepper.Value = v
            state["busy"] = False
            apply(v)

        def on_step(sender, e):
            if state["busy"]:
                return
            state["busy"] = True
            slider.Value = int(round(sender.Value * scale))
            state["busy"] = False
            apply(sender.Value)

        slider.ValueChanged += on_slider
        stepper.ValueChanged += on_step
        layout.AddRow(label, slider, stepper)

    def build_panel():
        layout = ef.DynamicLayout()
        layout.DefaultSpacing = ed.Size(8, 6)
        for p in PARAMS[session.kind]:
            make_row(layout, p)
        holder.Content = layout

    kind_dd = ef.DropDown()
    for k in ("table", "chair", "bookshelf"):
        kind_dd.Items.Add(ef.ListItem())
        kind_dd.Items[kind_dd.Items.Count - 1].Text = k.capitalize()
        kind_dd.Items[kind_dd.Items.Count - 1].Key = k
    kind_dd.SelectedKey = "table"

    def on_kind(sender, e):
        session.keep()                      # leave the old piece in the model
        session.kind = sender.SelectedKey
        build_panel()
        changed()
    kind_dd.SelectedIndexChanged += on_kind

    def mk_button(text, fn):
        b = ef.Button()
        b.Text = text
        b.Click += fn
        return b

    def on_keep(sender, e):
        session.keep()
        Rhino.RhinoApp.WriteLine("Piece kept. Change a slider to start a new one.")
        changed()

    def on_cutlist(sender, e):
        text = cut_list_text(session.parts)
        Rhino.RhinoApp.WriteLine("CUT LIST (" + session.size_text() + ")\n" + text)
        try:
            dlg = ef.SaveFileDialog()
            dlg.FileName = session.kind + "_cutlist.csv"
            if dlg.ShowDialog(form) == ef.DialogResult.Ok:
                save_cut_list_csv(session.parts, dlg.FileName)
        except Exception:
            Rhino.RhinoApp.WriteLine("Could not save CSV:\n" + traceback.format_exc())

    def on_close(sender, e):
        form.Close()

    def on_closed(sender, e):
        timer.Stop()
        sc.sticky.pop("parametric_furniture_form", None)

    form.Closed += on_closed

    top = ef.DynamicLayout()
    top.DefaultSpacing = ed.Size(8, 8)
    top.AddRow(kind_dd)
    top.AddRow(holder)
    top.AddRow(info)
    btns = ef.DynamicLayout()
    btns.DefaultSpacing = ed.Size(8, 0)
    btns.AddRow(mk_button("Keep piece", on_keep), mk_button("Cut list...", on_cutlist),
                mk_button("Close", on_close))
    top.AddRow(btns)
    form.Content = top

    build_panel()
    info.Text = session.size_text()
    sc.sticky["parametric_furniture_form"] = form
    form.Show()


def main():
    if IN_RHINO:
        show_ui()
    else:
        for k in PARAMS:
            parts = build_parts(k)
            lo, hi = bbox(parts)
            print("== %s  %.0f x %.0f x %.0f mm ==" % (k, hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]))
            print(cut_list_text(parts))


if __name__ == "__main__":
    main()

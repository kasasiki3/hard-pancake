"""基板の銅箔（充填後）から、相ごとの直流抵抗・ゲート線長・検出線長を出す。KiCadのpythonで実行。"""
import collections
import json
import math
import os
import sys

import numpy as np
import pcbnew
from shapely.geometry import Polygon
import shapely

b = pcbnew.LoadBoard(sys.argv[1] if len(sys.argv) > 1 else "kicad/pancake.kicad_pcb")
S = .25
bb = b.GetBoardEdgesBoundingBox()
X0, Y0 = bb.GetLeft() / 1e6, bb.GetTop() / 1e6
NX, NY = int(bb.GetWidth() / 1e6 / S) + 1, int(bb.GetHeight() / 1e6 / S) + 1
L = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
yy, xx = np.mgrid[0:NY, 0:NX]
px, py = X0 + xx.ravel() * S, Y0 + yy.ravel() * S
out = {}
for net in sys.argv[2:] or ["VBUS", "GND", "Net-(J2-Pin_1)", "Net-(J3-Pin_1)", "Net-(J4-Pin_1)"]:
    m = np.zeros((4, NY, NX), bool)
    for li, l in enumerate(L):
        polys = []
        for z in b.Zones():
            if z.GetNetname() == net and z.IsOnLayer(l):
                ps = z.GetFilledPolysList(l)
                for k in range(ps.OutlineCount()):
                    o = ps.Outline(k)
                    sh = Polygon([(o.CPoint(i).x / 1e6, o.CPoint(i).y / 1e6) for i in range(o.PointCount())],
                                 [[(ps.Hole(k, h).CPoint(i).x / 1e6, ps.Hole(k, h).CPoint(i).y / 1e6) for i in range(ps.Hole(k, h).PointCount())]
                                  for h in range(ps.HoleCount(k))])
                    polys.append(sh if sh.is_valid else shapely.make_valid(sh))
        for f in b.Footprints():
            for p in f.Pads():
                if p.GetNetname() == net and p.IsOnLayer(l):
                    ps = pcbnew.SHAPE_POLY_SET()
                    p.TransformShapeToPolygon(ps, l, 0, 10000, pcbnew.ERROR_OUTSIDE)
                    for k in range(ps.OutlineCount()):
                        o = ps.Outline(k)
                        polys.append(Polygon([(o.CPoint(i).x / 1e6, o.CPoint(i).y / 1e6) for i in range(o.PointCount())]).buffer(0))
        for sh in polys:
            m[li] |= shapely.contains_xy(sh, px, py).reshape(NY, NX)
    v = []
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == net:
            v.append((t.GetPosition().x / 1e6, t.GetPosition().y / 1e6, t.GetDrillValue() / 1e6))
    pads = {}
    for f in b.Footprints():
        for p in f.Pads():
            if p.GetNetname() == net:
                q = p.GetPosition()
                if p.GetDrillSizeX():
                    v.append((q.x / 1e6, q.y / 1e6, p.GetDrillSizeX() / 1e6))
                bx = p.GetBoundingBox()
                pads.setdefault(f.GetReference(), []).append((bx.GetLeft() / 1e6, bx.GetTop() / 1e6, bx.GetRight() / 1e6, bx.GetBottom() / 1e6))
    out[net] = dict(vias=v, pads=pads)
    np.save("tools/build/mask_%s.npy" % (net.replace("/", "").replace("(", "").replace(")", "")), m)
json.dump(dict(S=S, X0=X0, Y0=Y0, nets=out), open("tools/build/res.json", "w"))
ln = collections.defaultdict(float)
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_TRACE_T:
        ln[t.GetNetname()] += t.GetLength() / 1e6
for ph, (h, l, sh) in {"A": (1, 2, 2), "B": (3, 4, 3), "C": (5, 6, 4)}.items():
    nv = lambda n: sum(1 for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == n)
    print(ph, "GH %.0f GL %.0f SH %.0f SP %.0f SN %.0f mm" % tuple(
        ln[n] for n in ("Net-(Q%d-G)" % h, "Net-(Q%d-G)" % l, "Net-(J%d-Pin_1)" % sh, "Net-(U2-SP%s)" % ph, "Net-(U2-SN%s)" % ph)),
        "gate vias", nv("Net-(Q%d-G)" % h), nv("Net-(Q%d-G)" % l))
for net in out:
    m = np.load("tools/build/mask_%s.npy" % (net.replace("/", "").replace("(", "").replace(")", "")))
    zs = [sum(z.GetFilledPolysList(l).Area() for z in b.Zones() if z.GetNetname() == net and z.IsOnLayer(l)) / 1e12 for l in L]
    print(net, "raster", [round(float(x) * S * S) for x in m.sum((1, 2))], "zone mm2", [round(z) for z in zs])

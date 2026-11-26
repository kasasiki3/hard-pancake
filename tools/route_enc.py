"""エンコーダ端子（J5・J6）につながる8本だけを、表裏2層の迷路法で引く（2026-11-26、KiCad 10付属のpythonで実行）。

  <KiCad>/bin/python tools/route_enc.py     build/placed_fr.kicad_pcb → build/routes_enc.json

他の配線（tools/routes_81.json、固定）とパッド・ゾーンは障害物。Freeroutingは周りを固定するとこの8本が引けなかった。
"""
import heapq
import json
import os

import numpy as np
import pcbnew
import shapely
from shapely.geometry import Polygon, Point

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "tools", "build")
NETS = ["Net-(J6-Pin_6)", "Net-(J6-Pin_5)", "Net-(J6-Pin_4)", "Net-(J5-Pin_4)", "Net-(J5-Pin_5)", "Net-(J5-Pin_6)",
        "Net-(J5-Pin_1)", "Net-(J6-Pin_1)"]
WIDTH = {"Net-(J5-Pin_1)": .4, "Net-(J6-Pin_1)": .4}
CLR = .2       # 他の銅との間隔（規則0.15に余裕）
VD = .5        # ビア径
X0, Y0, X1, Y1 = 64.0, 6.0, 91.4, 54.0
S = .1
NX, NY = int((X1 - X0) / S) + 1, int((Y1 - Y0) / S) + 1
LAY = [pcbnew.F_Cu, pcbnew.B_Cu]

b = pcbnew.LoadBoard(os.path.join(BUILD, "placed_fr.kicad_pcb"))
gx, gy = np.meshgrid(X0 + np.arange(NX) * S, Y0 + np.arange(NY) * S)


def poly_of(item, layer, extra):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, pcbnew.FromMM(extra), pcbnew.FromMM(.01), pcbnew.ERROR_OUTSIDE)
    out = []
    for k in range(ps.OutlineCount()):
        o = ps.Outline(k)
        pts = [(o.CPoint(j).x / 1e6, o.CPoint(j).y / 1e6) for j in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(Polygon(pts).buffer(0))
    return out


def raster(polys):
    m = np.zeros((NY, NX), bool)
    for q in polys:
        x0, y0, x1, y1 = q.bounds
        i0, i1 = max(0, int((x0 - X0) / S) - 1), min(NX, int((x1 - X0) / S) + 2)
        j0, j1 = max(0, int((y0 - Y0) / S) - 1), min(NY, int((y1 - Y0) / S) + 2)
        if i0 >= i1 or j0 >= j1:
            continue
        m[j0:j1, i0:i1] |= shapely.contains_xy(q, gx[j0:j1, i0:i1], gy[j0:j1, i0:i1])
    return m


# 銅のある物（ネット付き）を層ごとに集める。ゾーンは表裏のGNDの全面ベタ以外（電源段の銅など）
items = []   # (net, layer, polygon(余白なし))
for f in b.Footprints():
    for p in f.Pads():
        for li, l in enumerate(LAY):
            if p.IsOnLayer(l):
                items += [(p.GetNetname(), li, q) for q in poly_of(p, l, 0)]
for t in b.GetTracks():
    for li, l in enumerate(LAY):
        if t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() == l:
            items += [(t.GetNetname(), li, q) for q in poly_of(t, l, 0)]
for z in b.Zones():
    if z.GetIsRuleArea() or (z.GetNetname() in ("GND", "GND_ISO") and z.GetAssignedPriority() == 0):
        continue
    for li, l in enumerate(LAY):
        if z.IsOnLayer(l):
            o = z.Outline()
            for k in range(o.OutlineCount()):
                oo = o.Outline(k)
                items.append((z.GetNetname(), li, Polygon([(oo.CPoint(j).x / 1e6, oo.CPoint(j).y / 1e6) for j in range(oo.PointCount())]).buffer(0)))
# 穴（取付穴など）は両層とも障害物
edge = Polygon([(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)])
board = Polygon([(0.3, 0.3), (91.7, 0.3), (91.7, 67.7), (0.3, 67.7)])

routes_t, routes_v = [], []
mine = {n: [[], []] for n in NETS}   # 引いた線（多角形、層ごと）


def blocked(net, w):
    """net以外の銅から (CLR + w/2) 以内のセル"""
    m = np.zeros((2, NY, NX), bool)
    for n, li, q in items:
        if n != net:
            m[li] |= raster([q.buffer(CLR + w / 2)])
    for n2, (pf, pb) in mine.items():
        if n2 != net:
            for li, ps in enumerate((pf, pb)):
                m[li] |= raster([q.buffer(CLR + w / 2) for q in ps])
    out = ~shapely.contains_xy(board.buffer(-(.3 + w / 2)), gx, gy)
    m |= out[None]
    return m


def astar(net, w, srcs, goal):
    blk = blocked(net, w)
    vblk = np.zeros((NY, NX), bool)
    for n, li, q in items:
        if n != net:
            vblk |= raster([q.buffer(CLR + VD / 2)])
    for n2, (pf, pb) in mine.items():
        if n2 != net:
            vblk |= raster([q.buffer(CLR + VD / 2) for q in pf + pb])
    vblk |= ~shapely.contains_xy(board.buffer(-(.3 + VD / 2)), gx, gy)
    D = {}
    pq = []
    for s in srcs:
        D[s] = 0
        heapq.heappush(pq, (0, s, None))
    prev = {}
    dirs = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    while pq:
        d, s, pr = heapq.heappop(pq)
        if d > D.get(s, 1e18):
            continue
        if s in goal:
            path = [s]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        l, j, i = s
        for di, dj, c in dirs:
            ni, nj = i + di, j + dj
            if 0 <= ni < NX and 0 <= nj < NY and not blk[l, nj, ni]:
                q = (l, nj, ni)
                nd = d + c + (.3 if l == 1 else 0)
                if nd < D.get(q, 1e18):
                    D[q] = nd
                    prev[q] = s
                    heapq.heappush(pq, (nd, q, s))
        if not vblk[j, i]:
            q = (1 - l, j, i)
            nd = d + 25
            if nd < D.get(q, 1e18):
                D[q] = nd
                prev[q] = s
                heapq.heappush(pq, (nd, q, s))
    return None


def cells_of(polys, li, w):
    m = raster([q for q in polys])
    return {(li, j, i) for j, i in zip(*np.nonzero(m))}


for net in NETS:
    w = WIDTH.get(net, .2)
    pads = [(f.GetReference(), p) for f in b.Footprints() for p in f.Pads() if p.GetNetname() == net]
    # パッドの中心付近のセル（層ごと）
    targets = []
    for ref, p in pads:
        c = Point(p.GetPosition().x / 1e6, p.GetPosition().y / 1e6)
        t = set()
        for li, l in enumerate(LAY):
            if p.IsOnLayer(l):
                t |= cells_of([c.buffer(.12)], li, w)
        targets.append((ref, t))
    # J（端子）から始め、近い順につなぐ木
    tree = set(next(t for r, t in targets if r in ("J5", "J6")))
    rest = [t for r, t in targets if r not in ("J5", "J6")]
    while rest:
        rest.sort(key=lambda t: min(abs(a[1] - c[1]) + abs(a[2] - c[2]) for a in list(t)[:1] for c in list(tree)[:200]))
        goal = rest.pop(0)
        path = astar(net, w, list(tree), goal)
        if path is None:
            raise SystemExit("fail " + net)
        # 折れ点だけ残して線・ビアにする
        pts = [(l, X0 + i * S, Y0 + j * S) for l, j, i in path]
        k = 0
        for n in range(1, len(pts)):
            a, c = pts[n - 1], pts[n]
            if a[0] != c[0]:
                if n - 1 > k:
                    routes_t.append((net, ["F.Cu", "B.Cu"][a[0]], w, pts[k][1:], a[1:]))
                routes_v.append((net, round(a[1], 3), round(a[2], 3), VD))
                mine[net][0].append(Point(a[1], a[2]).buffer(VD / 2))
                mine[net][1].append(Point(a[1], a[2]).buffer(VD / 2))
                k = n
            elif n + 1 == len(pts) or pts[n + 1][0] != c[0] or (round(pts[n + 1][1] - c[1], 3), round(pts[n + 1][2] - c[2], 3)) != (round(c[1] - a[1], 3), round(c[2] - a[2], 3)):
                if n > k:
                    routes_t.append((net, ["F.Cu", "B.Cu"][c[0]], w, pts[k][1:], c[1:]))
                    from shapely.geometry import LineString
                    mine[net][c[0]].append(LineString([pts[k][1:], c[1:]]).buffer(w / 2))
                k = n
        tree |= set(path) | goal
    print(net, "ok")

routes_t = [(n, l, w, (round(a[0], 3), round(a[1], 3)), (round(c[0], 3), round(c[1], 3))) for n, l, w, a, c in routes_t]
json.dump(dict(tracks=routes_t, vias=routes_v), open(os.path.join(BUILD, "routes_enc.json"), "w"))
print(len(routes_t), "tracks", len(routes_v), "vias")

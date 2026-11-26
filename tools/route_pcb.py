"""gen_pcb.py place の結果(geo.json)を2層(F/B)で自動配線する。GND・+3V3・VBUS・GND_ISOは内層へビアで落とす。"""
import heapq
import json
import random
import os
import sys

import numpy as np
import scipy.ndimage
from numba import njit
import shapely
from shapely.geometry import LineString, Point, Polygon

BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
G = json.load(open(os.path.join(BUILD, "geo.json")))
S = .1
N = 931
CLR = .155
VR = .25
WID = [.2, .25, .4]
RAD = [.1, .125, .2, VR]
PLANES = {"GND": G["MAIN"], "GND_ISO": G["ISO"], "+3V3": G["P3V3"], "VBUS": G["VBUS_IN2"]}
LAY = {"F.Cu": 0, "B.Cu": 1}
# 検出線は線幅0.2のまま、周りとの間隔だけ太線並みに広く取る
THIN = lambda n: n.startswith("Net-(U2-S") and n[9] in "PN" and n[-2] in "ABC"
ISO_NETS = {"GND_ISO", "Net-(C44-Pad1)", "Net-(J8-Pad4)", "Net-(JP1-A)", "Net-(JP1-B)", "Net-(JP2-A)", "Net-(JP2-B)",
            "Net-(JP3-A)", "Net-(JP3-B)", "Net-(JP4-A)", "Net-(JP4-B)", "Net-(U6-VISOIN)"}


# 多角形に入る格子点
def cells(poly):
    x0, y0, x1, y1 = poly.bounds
    i0, i1 = max(0, int(x0 / S) - 1), min(N - 1, int(x1 / S) + 2)
    j0, j1 = max(0, int(y0 / S) - 1), min(N - 1, int(y1 / S) + 2)
    if i1 < i0 or j1 < j0:
        return np.zeros(0, int), np.zeros(0, int)
    jj, ii = np.mgrid[j0:j1 + 1, i0:i1 + 1]
    m = shapely.contains_xy(poly, ii.ravel() * S, jj.ravel() * S)
    return jj.ravel()[m], ii.ravel()[m]


names = sorted({p["net"] for p in G["pads"] if p["net"]})
nid = {n: i + 1 for i, n in enumerate(names)}
st = np.zeros((4, 2, N, N), np.int16)   # 幅クラス(3=ビア)ごとの固定障害物
novia = np.zeros((N, N), bool)


def block(poly, net, layer, extra=0.0):
    k = nid.get(net, -1)
    for c in range(4):
        jj, ii = cells(poly.buffer(CLR + RAD[c] + extra))
        a = st[c, layer]
        cur = a[jj, ii]
        a[jj, ii] = np.where((cur == 0) | (cur == k), k, -1)


copper = {}          # net -> [(poly, layer)]
for p in G["pads"]:
    poly = shapely.unary_union([Polygon(q) for q in p["polys"]]) if p["polys"] else None
    if poly is None:
        continue
    p["poly"] = poly
    for l in ([0, 1] if p["th"] else [LAY[x] for x in p["layers"]]):
        block(poly, p["net"], l, .12 if p["th"] and not p["num"] else 0)
    jj, ii = cells(poly.buffer((.6 if p["ref"].startswith("NT") else .15 if not p["th"] else .25) + VR))
    novia[jj, ii] = True
for z in G["zones"]:
    z["p"] = Polygon(z["poly"])
    if z["layer"] in LAY and z["prio"] >= 3:
        # 大きいゾーンのほうが同じ場所の小さいゾーンに削られるので、小さいほうで塗る
        q = z["p"]
        for o in G["zones"]:
            if o is not z and o["layer"] == z["layer"] and o["prio"] > z["prio"] and o["net"] != z["net"]:
                q = q.difference(Polygon(o["poly"]).buffer(.3))
        for o in G["pads"]:
            if o["net"] != z["net"] and "poly" in o and (o["th"] or z["layer"] in o["layers"]):
                q = q.difference(o["poly"].buffer(.3))
        for net, x, y, d in G["vias"]:
            if net != z["net"]:
                q = q.difference(Point(x, y).buffer(d / 2 + .3))
        for net, l, w, a, b in G["tracks"]:
            if net != z["net"] and l == z["layer"]:
                q = q.difference(LineString([a, b]).buffer(w / 2 + .3))
        z["p"] = q
        block(q, z["net"], LAY[z["layer"]], .05)
        copper.setdefault(z["net"], []).append((q, LAY[z["layer"]]))
for net, x, y, d in G["vias"]:
    for l in (0, 1):
        block(Point(x, y).buffer(d / 2), net, l)
    jj, ii = cells(Point(x, y).buffer(.3 + .3))
    novia[jj, ii] = True
for net, l, w, a, b in G["tracks"]:
    q = LineString([a, b]).buffer(w / 2)
    block(q, net, LAY[l])
    copper.setdefault(net, []).append((q, LAY[l]))
vcop = {}
for net, x, y, d in G["vias"]:
    vcop.setdefault(net, []).append([(Point(x, y).buffer(d / 2), l) for l in (0, 1)])

for x0, y0, x1, y1 in G["KEEP"]:
    q = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    for l in (0, 1):
        for c in range(4):
            a, b = cells(q)
            cur = st[c, l][a, b]
            st[c, l][a, b] = np.where(cur == 0, -2, cur)
jj, ii = np.mgrid[0:N, 0:N]
inmain = shapely.contains_xy(Polygon(G["MAIN"]).buffer(-.25), ii.ravel() * S, jj.ravel() * S).reshape(N, N)
iniso = shapely.contains_xy(Polygon(G["ISO"]).buffer(-.25), ii.ravel() * S, jj.ravel() * S).reshape(N, N)
planemask = {}
for n, poly in PLANES.items():
    m = np.zeros((N, N), bool)
    a, b = cells(Polygon(poly).buffer(-.6))
    m[a, b] = True
    if n == "GND":
        for q in G["NOGND"]:
            a, b = cells(Polygon(q).buffer(.6))
            m[a, b] = False
    planemask[n] = m


@njit(cache=True)
def astar(okT, okV, cost, vcost, src, goalT, goalV, N, VIA, hx0, hx1, hy0, hy1, lpen):
    D = np.full(2 * N * N, 1e18)
    P = np.full(2 * N * N, -1)
    h = [(0.0, 0.0, 0)]
    h.pop()
    for s in src:
        D[s] = 0
        P[s] = -2
        heapq.heappush(h, (0.0, 0.0, s))
    while h:
        f, d, s = heapq.heappop(h)
        if s < 0:
            return -s - 1, 1, P
        if d > D[s] + 1e-9:
            continue
        l = s // (N * N)
        r = s - l * N * N
        y = r // N
        x = r - y * N
        if goalT[l, y, x]:
            return s, 0, P
        if goalV[y, x] and okV[y, x]:
            g = d + VIA * .6 + vcost[y, x]
            heapq.heappush(h, (g, g, -s - 1))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                ny = y + dy
                nx = x + dx
                if ny < 0 or nx < 0 or ny >= N or nx >= N or not okT[l, ny, nx]:
                    continue
                g = d + (1.0 if dx == 0 or dy == 0 else 1.41421) * cost[l, ny, nx] * lpen[l]
                q = l * N * N + ny * N + nx
                if g < D[q] - 1e-9:
                    D[q] = g
                    P[q] = s
                    ex = max(hx0 - nx, 0, nx - hx1)
                    ey = max(hy0 - ny, 0, ny - hy1)
                    e = max(ex, ey) + .41421 * min(ex, ey)
                    heapq.heappush(h, (g + e, g, q))
        if okV[y, x]:
            q = (1 - l) * N * N + y * N + x
            g = d + VIA + vcost[y, x]
            if g < D[q] - 1e-9:
                D[q] = g
                P[q] = s
                ex = max(hx0 - x, 0, x - hx1)
                ey = max(hy0 - y, 0, y - hy1)
                heapq.heappush(h, (g + max(ex, ey) + .41421 * min(ex, ey), g, q))
    return -1, 0, P


disc = {}


# 点列を半径rで太らせて占有を足す
def stamp(occ, layers, pts, r, v):
    R = int(r / S + 1e-6)
    if r not in disc:
        yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
        m = (yy * yy + xx * xx) * S * S < r * r - 1e-9
        disc[r] = (yy[m], xx[m])
    dy, dx = disc[r]
    a = np.array(pts)
    Y = (a[:, 1][:, None] + dy[None]).ravel()
    X = (a[:, 0][:, None] + dx[None]).ravel()
    k = np.unique(np.clip(Y, 0, N - 1) * N + np.clip(X, 0, N - 1))
    for l in layers:
        occ[l].ravel()[k] += v


occ = np.zeros((4, 2, N, N), np.int16)
hist = np.zeros((2, N, N), np.float32)


def wclass(net):
    if net in ("+5V", "Net-(U1-EN)", "/制御 (MCU・CAN・エンコーダ)/SWD_5V", "Net-(U6-VISOIN)", "Net-(J8-Pad4)"):
        return 2
    if net.startswith("Net-(U2-S") and net[-2] in "ABC" and net[9] in "PN":
        return 0
    if net.startswith("Net-(Q") or net in ("Net-(J2-Pin_1)", "Net-(J3-Pin_1)", "Net-(J4-Pin_1)", "Net-(U2-CPH)", "Net-(U2-CPL)",
                                           "Net-(U2-VCP)", "Net-(U2-CB)", "Net-(D3-K)"):
        return 1
    return 0


# 接続すべき仕事: 面のネットはパッドごと、その他は木
pads = {}
for p in G["pads"]:
    if p["net"] and "poly" in p and not p["net"].startswith("unconnected"):
        pads.setdefault(p["net"], []).append(p)
# ネットのパッドと固定銅箔を塊にまとめる
def groups(net):
    items = []
    for p in pads[net]:
        items.append([(p["poly"], l) for l in ([0, 1] if p["th"] else [LAY[x] for x in p["layers"]])])
    for c in copper.get(net, []):
        items.append([c])
    items += vcop.get(net, [])
    par = list(range(len(items)))

    def f(a):
        while par[a] != a:
            a = par[a]
        return a
    for i in range(len(items)):
        for j in range(i):
            if any(l == m and a.distance(b) < .001 for a, l in items[i] for b, m in items[j]):
                par[f(i)] = f(j)
    g = {}
    for i, it in enumerate(items):
        g.setdefault(f(i), []).append((it, i < len(pads[net]) and pads[net][i]))
    return list(g.values())


jobs = []
for net in names:
    if net not in pads:
        continue
    gs = groups(net)
    if net in PLANES:
        todo = []
        for g in gs:
            ok = False
            for it, p in g:
                if p and p["th"]:
                    ok = True
                for q, l in it:
                    for vn, x, y, d in G["vias"]:
                        if vn == net and q.distance(Point(x, y)) < .01:
                            ok = True
            if not ok and any(p for it, p in g):
                todo.append(g)
        for g in todo:
            jobs.append((net, [g]))
    elif len(gs) > 1:
        jobs.append((net, gs))


def gcells(g):
    out = []
    for it, p in g:
        for q, l in it:
            jj, ii = cells(q.buffer(-.04) if q.area > .1 else q)
            if len(jj) == 0:
                c = q.representative_point()
                jj, ii = np.array([round(c.y / S)]), np.array([round(c.x / S)])
            out.append(l * N * N + jj * N + ii)
    return np.unique(np.concatenate(out))


# 縦束のある網は、束の上端(Y0)でだけ外へつなぐ（途中で合流すると並びが崩れ、検出線がゲート線に近づく）
def toponly(net, cs):
    for n, l, w, a, b in G["tracks"]:
        if n == net and l == "B.Cu" and abs(a[0] - b[0]) < 1e-6 and min(a[1], b[1]) == G["TOP"]:
            y = (cs % (N * N)) // N * S
            x = (cs % (N * N)) % N * S
            m = (y < G["TOP"] + .8) & (y > G["TOP"] - .4) & (abs(x - a[0]) < .3)
            if m.any():
                return cs[m]
    return cs


JOB = []
for net, gs in jobs:
    JOB.append(dict(net=net, gs=[toponly(net, gcells(g)) for g in gs], c=wclass(net), routes=[], plane=net in PLANES, bundle=any(n == net and l == "B.Cu" for n, l, w, a, b in G["tracks"]) and net not in PLANES))
def span(j):
    a = np.concatenate(j["gs"]) % (N * N)
    return (a // N).max() - (a // N).min() + (a % N).max() - (a % N).min()
JOB.sort(key=lambda j: (not j["plane"], span(j)))
print(len(JOB), "jobs")


def apply(j, v):
    # 同じネットの別の仕事どうしは重なってよいが、簡単のため占有として数え、自分の分だけ引いて探索する
    for path, kind in j["routes"]:
        for l in (0, 1):
            pts = [(s % (N * N) % N, s % (N * N) // N) for s in path if s // (N * N) == l]
            if pts:
                for c in range(4):
                    stamp(occ[c], [l], pts, RAD[j["c"]] + CLR + RAD[c], v)
        vs = []
        for a, b in zip(path, path[1:]):
            if a // (N * N) != b // (N * N):
                vs.append((a % (N * N) % N, a % (N * N) // N))
        if kind:
            vs.append((path[-1] % (N * N) % N, path[-1] % (N * N) // N))
        if vs:
            for c in range(4):
                stamp(occ[c], [0, 1], vs, VR + CLR + RAD[c] + (.1 if c == 3 else 0), v)


def route(j, pres):
    net, c, k = j["net"], j["c"], nid[j["net"]]
    reg = iniso if net in ISO_NETS else inmain
    okT = ((st[c] == 0) | (st[c] == k)) & reg[None]
    free = net in ("GND", "+5V", "Net-(D3-K)")
    if free:
        okT |= (st[c] == -2) & reg[None]
        # 5Vはコイルの裏を通さない
        if net == "+5V":
            okT[1] &= st[c][1] != -2
    # 太い線がピンに入れない場合の逃げ: 自分のパッドの中と近くは細い線で判定
    okV = ((st[3][0] == 0) | (st[3][0] == k)) & ((st[3][1] == 0) | (st[3][1] == k)) & reg & ~novia
    if free:
        okV |= (np.isin(st[3][0], (0, k, -2)) & np.isin(st[3][1], (0, k, -2)) & reg & ~novia)
    # 24Vの線を水晶の周りに通さない
    if net == "VBUS":
        okT[:, int(13 / S):int(24 / S), int(62 / S):int(72 / S)] = False
    # 温度の線はゲート・検出線の束に入れず、VBUSバーの右端を回す
    if net.endswith("NTC_SENSE"):
        okT[:, int(36 / S):, :int(63.4 / S)] = False
        okV = okV.copy()
        okV[int(36 / S):, :int(63.4 / S)] = False
    other = occ[c].astype(np.float32)
    cost = 1 + hist + pres * other
    # ゲート・検出線は、DRVのすぐ近くを除いて裏面に揃える（ペアが別の層に分かれないように）
    if j["bundle"]:
        f = np.full((N, N), 2.5, np.float32)
        f[int(19 / S):int(32 / S), int(36 / S):int(50 / S)] = 1
        cost[0] = cost[0] * f
    # 検出線は、ゲート・SH線から0.6mm以上離れるほど安くする（逆も同じ）
    if j["bundle"]:
        near = np.zeros((2, N, N), bool)
        for q in JOB:
            if q["bundle"] and THIN(q["net"]) != THIN(net):
                for path, kind in q["routes"]:
                    a = np.array(path)
                    near[a // (N * N), a % (N * N) // N, a % (N * N) % N] = True
        for l in (0, 1):
            cost[l] = cost[l] + 1.6 * scipy.ndimage.binary_dilation(near[l], iterations=6)
    vcost = pres * 3 * (occ[3][0] + occ[3][1]).astype(np.float32)
    lpen = np.array([1.0, 1.0])
    routes = []
    no = np.zeros((N, N), bool)
    if j["plane"]:
        jobsl = [(j["gs"][0], None)]
    else:
        order = sorted(j["gs"], key=lambda g: len(g))
        jobsl = None
    if j["plane"]:
        src = j["gs"][0]
        for s in src:
            okT[s // (N * N), s % (N * N) // N, s % N if False else s % (N * N) % N] = True
        e, kind, P = astar(okT, okV, cost, vcost, src, np.zeros((2, N, N), bool), planemask[net], N, 12.0, 0, N, 0, N, lpen)
        if e < 0:
            return None
        path = [e]
        while P[path[-1]] >= 0:
            path.append(P[path[-1]])
        return [(path[::-1], kind)]
    rest = [g for g in j["gs"]]
    conn = rest.pop(int(np.argmax([len(g) for g in rest])))
    for g in j["gs"]:
        l, r = g // (N * N), g % (N * N)
        okT[l, r // N, r % N] = True
    while rest:
        goal = np.zeros((2, N, N), bool)
        for g in rest:
            goal[g // (N * N), g % (N * N) // N, g % (N * N) % N] = True
        allg = np.concatenate(rest) % (N * N)
        e, kind, P = astar(okT, okV, cost, vcost, conn, goal, no, N, 12.0, (allg % N).min(), (allg % N).max(), (allg // N).min(), (allg // N).max(), lpen)
        if e < 0:
            return None
        path = [e]
        while P[path[-1]] >= 0:
            path.append(P[path[-1]])
        path = path[::-1]
        routes.append((path, 0))
        i = next(i for i, g in enumerate(rest) if e in g)
        conn = np.unique(np.concatenate([conn, rest.pop(i), np.array(path)]))
    return routes


def conflicts(j):
    n = 0
    for path, kind in j["routes"]:
        for s in path:
            l, r = s // (N * N), s % (N * N)
            if occ[j["c"]][l, r // N, r % N]:
                n += 1
                hist[l, r // N, r % N] += 1
        for a, b in list(zip(path, path[1:])) + ([(path[-1], path[-1] + N * N if path[-1] < N * N else path[-1] - N * N)] if kind else []):
            if a // (N * N) != b // (N * N):
                r = a % (N * N)
                if occ[3][0, r // N, r % N] or occ[3][1, r // N, r % N]:
                    n += 1
                    hist[:, r // N, r % N] += 1
    return n


pres = .5
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
for it in range(int(sys.argv[1]) if len(sys.argv) > 1 else 40):
    fail, bad, badnets = [], 0, []
    if it > 4:
        random.shuffle(JOB)
    for j in JOB:
        if j["routes"]:
            apply(j, -1)
            # 2周目以降は衝突しているものだけ引き直す
            if it > 1 and not (j["bundle"] and it < 14) and not conflicts(j):
                apply(j, 1)
                continue
        r = route(j, pres)
        if r is None:
            fail.append(j["net"])
            j["bad"] = [(int(q % (N * N) % N) * S, int(q % (N * N) // N) * S) for q in j["gs"][0][:1]]
            j["routes"] = []
            continue
        j["routes"] = r
        apply(j, 1)
    for j in JOB:
        if j["routes"]:
            apply(j, -1)
            c = conflicts(j)
            apply(j, 1)
            if c:
                bad += c
                badnets.append(j["net"])
    print(it, "fail", sorted(set(fail)), "conf", bad, badnets[:14], flush=True)
    if not bad and not fail and it:
        break
    pres = min(pres * 1.25, 25)

if bad or fail:
    print("FAILAT", [(j["net"], j.get("bad")) for j in JOB if not j["routes"]])
    for j in JOB:
        if j["routes"]:
            apply(j, -1)
            pts = [(s // (N * N), round((s % (N * N) % N) * S, 1), round((s % (N * N) // N) * S, 1)) for path, k in j["routes"] for s in path
                   if occ[j["c"]][s // (N * N), s % (N * N) // N, s % (N * N) % N]]
            apply(j, 1)
            if pts:
                print("CONF", j["net"], pts[::4][:8])
    sys.exit(1)
tr, vi = [], []
for j in JOB:
    for path, kind in j["routes"]:
        xy = [(s // (N * N), s % (N * N) % N, s % (N * N) // N) for s in path]
        k = 0
        for i in range(1, len(xy)):
            a, b = xy[i - 1], xy[i]
            if a[0] != b[0]:
                if i - 1 > k:
                    tr.append((j["net"], a[0], j["c"], xy[k], a))
                vi.append((j["net"], round(a[1] * S, 3), round(a[2] * S, 3), VR * 2))
                k = i
            elif i + 1 == len(xy) or xy[i + 1][0] != b[0] or (xy[i + 1][1] - b[1], xy[i + 1][2] - b[2]) != (b[1] - a[1], b[2] - a[2]):
                tr.append((j["net"], a[0], j["c"], xy[k], b))
                k = i
        if kind:
            vi.append((j["net"], round(xy[-1][1] * S, 3), round(xy[-1][2] * S, 3), VR * 2))
json.dump(dict(tracks=[(n, ["F.Cu", "B.Cu"][l], .2 if THIN(n) else WID[c], (round(a[1] * S, 3), round(a[2] * S, 3)), (round(b[1] * S, 3), round(b[2] * S, 3)))
                       for n, l, c, a, b in tr], vias=vi), open(os.path.join(BUILD, "routes%s.json" % (sys.argv[2] if len(sys.argv) > 2 else "")), "w"))
print(len(tr), "tracks", len(vi), "vias")

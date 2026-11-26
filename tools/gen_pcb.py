"""固いパンケーキ: 基板ジェネレータ（KiCad 10付属のpythonで実行）。

実行順（Gitルートで）:
  kicad-cli sch export netlist kicad/pancake.kicad_sch -o tools/build/n.net
  <KiCad>/bin/python tools/gen_pcb.py place     配置・銅箔・ビア → build/placed.kicad_pcb, build/geo.json
  python tools/route_pcb.py                     自動配線 → build/routes<乱数の種>.json。採用したものを tools/routes.json に置く
  <KiCad>/bin/python tools/gen_pcb.py finish    配線を入れてゾーン充填 → kicad/pancake.kicad_pcb
"""
import json
import math
import os
import sys

import pcbnew
from pcbnew import B_Cu, F_Cu, In1_Cu, In2_Cu

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import find, first, parse  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "tools", "build")
OUT = os.path.join(ROOT, "kicad", "pancake.kicad_pcb")
FPLIB = "C:/Program Files/KiCad/10.0/share/kicad/footprints/"
W, H = 81.0, 68.0
CR = 4.5    # 角の丸み。moteusと同じく取付穴の中心と同心にする
COLS = {"A": 22.8, "B": 40.2, "C": 57.6}
CAPX = (31.5, 48.9, 66.3)    # 電解は各相のFETの隣
OFF = [0, 0]
MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# 絶縁の島（GND_ISO側）と、それ以外の銅箔の範囲。間は3mm以上あける
# 右上のねじ穴の周りは、ねじ経由で島とつながらないように銅を置かない
ISO = [(10.5, .5), (29.5, .5), (29.5, 27), (16, 27), (16, 38), (.5, 38), (.5, 10.5), (10.5, 10.5)]
# 外形の丸みに沿った角（中心は取付穴、半径はCR-端からの距離）
def arc(cx, cy, r, a0):
    return [(cx + r * math.cos(math.radians(a0 + 10 * k)), cy + r * math.sin(math.radians(a0 + 10 * k))) for k in range(10)]


MAIN = [(33.3, .55)] + arc(W - CR, CR, CR - .55, 270) + arc(W - CR, H - CR, CR - .55, 0) + arc(CR, H - CR, CR - .55, 90) + [
    (.55, 41.4), (19.4, 41.4), (19.4, 30.4), (33.3, 30.4)]
P3V3 = [(33.8, 1), (76.2, 1), (80, 5), (80, 63), (76.2, 67), (64.6, 67), (64.6, 50), (66.2, 50), (66.2, 45), (71.2, 45), (71.2, 27.6), (43, 27.6),
        (43, 16.4), (33.8, 16.4)]
VBUS_IN2 = [(33.6, 17), (42.4, 17), (42.4, 27), (41, 27), (41, 36), (70.6, 36), (70.6, 44.2), (65.4, 44.2), (65.4, 49.2), (11, 49.2), (11, 48.4), (.8, 48.4), (.8, 41.8), (19.8, 41.8),
            (19.8, 31), (33.6, 31)]
GND_IN2 = [(.8, 49), (10.4, 49), (10.4, 49.7), (64, 49.7), (64, 67.2)] + arc(CR, H - CR, CR - .8, 90)

# 部品: ref -> (x, y, 回転)
PLACE = {
    "J1": (7.6, 52.8, 90),
    "D1": (22.7, 33.8, 90),
    "C1": (31.5, 37, 90),
    "C2": (48.9, 37, 90),
    "C3": (66.3, 37, 90),
    "H1": (4.5, 4.5, 0),
    "H2": (76.5, 4.5, 0),
    "H3": (4.5, 63.5, 0),
    "H4": (76.5, 63.5, 0),
    "J8": (7.74, 16.2, -90),
    "J9": (7.74, 32.7, -90),
    "J5": (67.6, 56.6, 0),
    "J6": (67.6, 48, 0),
    "U4": (79, 42.5, 90),
    "R23": (77.5, 37.6, 90),
    "R22": (78.7, 37.6, 90),
    "R21": (79.9, 37.6, 90),
    "U5": (75.1, 42.5, 90),
    "R26": (73.9, 37.6, 90),
    "R24": (75.1, 37.6, 90),
    "R25": (76.3, 37.6, 90),
    "C14": (39.05, 17.4, 90),
    "R10": (38.3, 21.4, 180),
    "R9": (38.3, 20.35, 0),
    "D3": (44.3, 16.05, 180),
    "L1": (47.7, 10.9, 0),
    "C18": (53.5, 10.9, 0),
    "C13": (35.5, 28.75, 180),
    "NT7": (35.5, 40.7, -90),
    "TH1": (63.8, 52, 90),
    "D2": (49.4, 3.8, 0),
    "C4": (52.7, 3.8, -90),
    "U1": (55.8, 3.8, 0),
    "C5": (59.1, 3.8, -90),
    "J7": (62.3, 4.9, 0),
    "SW1": (76.4, 11.6, 0),
    "D4": (78.6, 17, 180),
    "R19": (75.6, 17, 0),
    "D5": (78.6, 19, 180),
    "R20": (75.6, 19, 0),
    "TP17": (56.8, 7.4, 0),
    "TP18": (45.8, 3.4, 0),
    "TP19": (57.6, 34, 0),
    "TP16": (17.4, 42.7, 0),
    "TP13": (39.4, 30.2, 0),
    "TP10": (54.6, 29.2, 0),
    "TP11": (57.2, 29.2, 0),
    "TP12": (59.8, 29.2, 0),
    "TP15": (62.4, 29.2, 0),
    "TP14": (65.0, 29.2, 0),
    "TP20": (67.6, 29.2, 0),
    "U2": (44.05, 24.05, 0),
    "C10": (50.6, 20.8, -90),
    "C11": (50.8, 27.3, 0),
    "R7": (50.8, 24.2, 0),
    "R8": (50.8, 23, 0),
    "R3": (50.8, 25.4, 180),
    "C16": (36.4, 22.1, 90),
    "C15": (36.3, 24.4, 180),
    "C12": (36.4, 26.25, 180),
    "C17": (43.55, 18.85, 90),
    "U3": (61.05, 19.05, -180),
    "Y1": (68.7, 19.5, 90),
    "C35": (69.3, 23.0, -90),
    "C36": (68.1, 16.4, 90),
    "C28": (67.0, 23.2, -90),
    "C29": (63.7, 25.0, -180),
    "C30": (55.2, 21.5, 90),
    "C32": (58.5, 13.0, 0),
    "C34": (60.5, 13.0, 0),
    "C33": (59.5, 11.0, 0),
    "C31": (59.1, 9.0, 0),
    "C7": (67.0, 14.3, 90),
    "R4": (67.0, 12.2, -90),
    "C6": (68.4, 14.3, 90),
    "R2": (68.4, 12.2, -90),
    "R1": (72, 10, -90),
    "C8": (63.5, 12.6, 90),
    "R5": (63.5, 10.4, -90),
    "C9": (62.3, 12.6, 90),
    "R6": (62.3, 10.4, -90),
    "R18": (61.9, 25.4, 90),
    "C37": (67.0, 26.4, -90),
    "R17": (57, 27.4, 0),
    "U6": (31.4, 14.0, -180),
    "C39": (35.6, 13.4, -90),
    "C40": (35.6, 10.4, 90),
    "C38": (37.4, 13.25, -90),
    "C42": (26.8, 13.6, -90),
    "C41": (25.0, 13.4, -90),
    "C43": (26.2, 10.6, -180),
    "D6": (25.9, 17.8, -180),
    "JP1": (20.8, 18.8, -180),
    "JP2": (20.8, 10.8, -180),
    "JP3": (26.6, 22.7, -180),
    "JP4": (21.4, 22.7, -180),
    "R27": (21.4, 16.0, 90),
    "R28": (21.4, 13.6, 90),
    "R29": (20.2, 16.0, 90),
    "R30": (20.2, 13.6, 90),
    "C44": (22.7, 14.6, 90),
}
# 相ごとに同じ配置を3回
for i, (ph, c) in enumerate(COLS.items()):
    n = lambda p, base, step: p + str(base + step * i)
    PLACE.update({k: (x, y - 11, r) for k, (x, y, r) in {
        n("Q", 1, 2): (c, 57.9, 90), n("Q", 2, 2): (c, 65.3, 90), n("R", 11, 2): (c + 2, 71, 0),
        n("C", 19, 3): (c + 2.1, 52, 90), n("C", 20, 3): (c - 1.2, 51.4, 90),
        n("NT", 1, 2): (c + .3, 72.2, 180), n("NT", 2, 2): (c + 3.7, 72.2, 0),
        n("J", 2, 1): (c - 7.4, 72.1, 0),
        n("TP", 1, 3): (c + 5, 60.65, 0), n("TP", 2, 3): (c + 4.1, 66.3, 0), n("TP", 3, 3): (c + 3.7, 63.9, 0),
        # 未実装の部品は裏面（1番パッドの向きで指定）
        n("C", 45, 1): (c - 1.2, 61.1, "up"), n("R", 12, 2): (c - 2.1, 74.3, "left"), n("C", 21, 3): (c + 1.7, 74.3, "left")}.items()})


DENSE = set("C4 C5 R17 R21 R22 R23 R24 R25 R26 R1 R2 R4 R5 R6 C6 C7 C8 C9 C28 C29 C30 C31 C32 C33 C34 C35 C36 C39 C40 C41 C42 C43 C44 R18 R27 R28 R29 R30 "
            "R3 R7 R8 R9 R10 C10 C11 C12 C15 C16 C17 R12 R14 R16 C20 C23 C26 TH1 R20 C21 C24 C27 C19 C22 C25 C1 C2 C3".split())


def netlist():
    t = parse(open(os.path.join(BUILD, "n.net"), encoding="utf-8").read())[0]
    comps, pins = {}, {}
    for c in find(first(t, "components"), "comp"):
        sp = first(c, "sheetpath")
        fp = first(c, "footprint")
        tst = first(c, "tstamps")[1]
        comps[first(c, "ref")[1]] = dict(
            value=first(c, "value")[1], fp=fp[1] if fp else None,
            path=first(sp, "tstamps")[1] + tst,
            sheet=first(sp, "names")[1],
            nobom=any(p[1][1] == "exclude_from_bom" for p in find(c, "property")),
            dnp=any(p[1][1] == "dnp" for p in find(c, "property")),
            fields={f[1][1]: f[2] for f in (find(first(c, "fields"), "field") if first(c, "fields") else [])
                    if len(f) > 2})
    for n in find(first(t, "nets"), "net"):
        for nd in find(n, "node"):
            pins[(first(nd, "ref")[1], first(nd, "pin")[1])] = first(n, "name")[1]
    return comps, pins


def load_fp(lid):
    lib, name = lid.split(":")
    base = os.path.join(ROOT, "kicad", "pancake.pretty") if lib == "pancake" else FPLIB + lib + ".pretty"
    f = pcbnew.FootprintLoad(base, name)
    if not f:
        raise SystemExit("no footprint " + lid)
    f.SetFPID(pcbnew.LIB_ID(lib, name))
    return f


def place():
    comps, pins = netlist()
    b = pcbnew.NewBoard(os.path.join(BUILD, "placed.kicad_pcb"))
    b.SetCopperLayerCount(4)
    nets = {}
    for nm in sorted(set(pins.values())):
        nets[nm] = pcbnew.NETINFO_ITEM(b, nm)
        b.Add(nets[nm])
    for ref in ("H1", "H2", "H3", "H4"):
        comps[ref] = dict(value="M3", fp="pancake:M3_Mount_moteus", path=None, dnp=False)
    for ref, c in comps.items():
        f = load_fp(c["fp"])
        f.SetReference(ref)
        f.SetValue(c["value"])
        x, y, r = PLACE[ref]
        b.Add(f)
        f.SetPosition(V(x, y))
        if isinstance(r, str):
            f.Flip(V(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
            for d in (0, 90, 180, 270):
                f.SetOrientationDegrees(d)
                q = f.FindPadByNumber("1").GetPosition() - V(x, y)
                if (q.y < -MM(.3) if r == "up" else q.x < -MM(.3)):
                    break
        else:
            f.SetOrientationDegrees(r)
        if c["path"]:
            f.SetPath(pcbnew.KIID_PATH(c["path"]))
            f.SetSheetname(c["sheet"])
        else:
            f.SetBoardOnly(True)
        f.SetDNP(c["dnp"])
        if c["path"]:
            f.SetExcludedFromBOM(c["nobom"])
            for k, v in c["fields"].items():
                if k not in ("Footprint", "Datasheet", "Description"):
                    f.SetField(k, v)
                    f.GetField(k).SetVisible(False)
        # 部品が密な所の番号は実装図(F.Fab)側だけにし、シルクには出さない
        if ref[0] in "HRCT" and (ref[0] == "H" or ref in DENSE) or ref in ("J2", "J3", "J4", "J1", "R21", "R22", "R23", "R24", "R25", "R26", "TP10", "TP11", "TP12", "TP14", "TP15", "TP20", "U4", "U5", "D1", "R17", "C38", "J8", "J9", "D6", "R11", "R13", "R15", "J5", "J6", "J7", "SW1", "D4", "D5", "C17", "D3", "U2", "R19"):
            f.Reference().SetVisible(False)
        f.Reference().SetTextSize(V(.8, .8))
        f.Reference().SetTextThickness(MM(.12))
        if ref[0] == "H":
            nets["MOUNT_" + ref] = pcbnew.NETINFO_ITEM(b, "MOUNT_" + ref)
            b.Add(nets["MOUNT_" + ref])
            for p in f.Pads():
                p.SetNet(nets["MOUNT_" + ref])
        for p in f.Pads():
            nm = pins.get((ref, p.GetNumber()))
            if nm:
                p.SetNet(nets[nm])
    # 外形
    def edge(kind):
        e = pcbnew.PCB_SHAPE(b, kind)
        e.SetLayer(pcbnew.Edge_Cuts)
        e.SetWidth(MM(.1))
        b.Add(e)
        return e
    for p, q in (((CR, 0), (W - CR, 0)), ((W, CR), (W, H - CR)), ((W - CR, H), (CR, H)), ((0, H - CR), (0, CR))):
        e = edge(pcbnew.SHAPE_T_SEGMENT)
        e.SetStart(V(*p))
        e.SetEnd(V(*q))
    k = CR * (1 - .5 ** .5)
    for p, m, q in (((0, CR), (k, k), (CR, 0)), ((W - CR, 0), (W - k, k), (W, CR)),
                    ((W, H - CR), (W - k, H - k), (W - CR, H)), ((CR, H), (k, H - k), (0, H - CR))):
        e = edge(pcbnew.SHAPE_T_ARC)
        e.SetArcGeometry(V(*p), V(*m), V(*q))

    def net_of(ref, pin):
        return pins[(ref, pin)]
    zones, vias, tracks = [], [], []    # router用にも残す
    BARE = ("GND", "GND_ISO", "+3V3")

    def zone(net, layers, poly, prio, thermal=False):
        poly = [(x + OFF[0], y + OFF[1]) for x, y in poly]
        for l in layers:
            z = pcbnew.ZONE(b)
            z.SetLayer(l)
            z.SetNet(nets[net])
            ol = z.Outline()
            ol.NewOutline()
            for x, y in poly:
                ol.Append(MM(x), MM(y))
            z.SetAssignedPriority(prio)
            z.SetLocalClearance(MM(.25 if prio else .2))
            z.SetMinThickness(MM(.2))
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL if thermal else pcbnew.ZONE_CONNECTION_FULL)
            z.SetThermalReliefGap(MM(.25))
            z.SetThermalReliefSpokeWidth(MM(.4))
            z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
            b.Add(z)
            zones.append(dict(net=net, layer=b.GetLayerName(l), poly=poly, prio=prio))

    def via(net, x, y, d=.6):
        x, y = x + OFF[0], y + OFF[1]
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(V(x, y))
        v.SetWidth(MM(d))
        v.SetDrill(MM(.3))
        v.SetNet(nets[net])
        b.Add(v)
        vias.append((net, x, y, d))

    def trk(net, layer, w, *pts):
        for p, q in zip(pts, pts[1:]):
            if p == q:
                continue
            p, q = [(x + OFF[0], y + OFF[1]) for x, y in (p, q)]
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(V(*p))
            t.SetEnd(V(*q))
            t.SetWidth(MM(w))
            t.SetLayer(layer)
            t.SetNet(nets[net])
            b.Add(t)
            tracks.append((net, b.GetLayerName(layer), w, p, q))

    # 面
    zone("GND", [F_Cu, B_Cu], MAIN, 0, True)
    zone("GND", [In1_Cu], MAIN, 0, True)
    zone("GND_ISO", [F_Cu, In1_Cu, In2_Cu, B_Cu], ISO, 0, True)
    zone("+3V3", [In2_Cu], P3V3, 1, True)
    # ゲート・検出線の束（L4）の参照面をGNDにする
    zone("GND", [In2_Cu], rect(41.4, 28, 70.8, 35.6), 1)
    zone("VBUS", [In2_Cu], VBUS_IN2, 1)
    zone("GND", [In2_Cu], GND_IN2, 1)
    # VBUS: XT60の真横がバー。L2はGNDのまま
    zone("VBUS", [F_Cu], [(.8, 41.7), (19.6, 41.7), (19.6, 41), (70.6, 41), (70.6, 44.4), (65.6, 44.4), (65.6, 48.7),
                          (11, 48.7), (11, 48.2), (.8, 48.2)], 3)
    zone("VBUS", [B_Cu], [(.8, 41.7), (19.6, 41.7), (19.6, 39), (24.9, 39), (24.9, 48.7), (11, 48.7), (11, 48.2), (.8, 48.2)], 3)
    for x0, x1 in ((29.5, 41.9), (46.2, 59.7), (64.4, 70.6)):
        zone("VBUS", [B_Cu], rect(x0, 37.2, x1 if x1 < 70 else 71.6, 48.7 if x1 < 70 else 44.4), 3)
    zone("VBUS", [F_Cu], rect(20.6, 34.7, 24.8, 37.2), 4)
    for x in CAPX:
        zone("VBUS", [F_Cu], rect(x - 3.4, 38.7, x + 3.4, 41.3), 4)

    # ビアの千鳥配列（moteus風）
    def hexa(net, x0, y0, x1, y1, px=1.2, py=1.04, d=.6):
        y, k = y0, 0
        while y <= y1 + 1e-6:
            x = x0 + (px / 2 if k % 2 else 0)
            while x <= x1 + 1e-6:
                via(net, round(x, 3), round(y, 3), d)
                x += px
            y, k = y + py, k + 1
    hexa("VBUS", 10.9, 42.4, 15.6, 45, 2.2, 1.8)
    # TVS: VBUSバーを削らず、C20の上に置く（VBUSはL3から上げる）
    for x in (20.9, 24.5):
        for y in (35.1, 36, 36.9):
            via("VBUS", x, y, .5)
        for y in (30.95, 31.9, 32.85):
            via("GND", x, y)
            trk("GND", F_Cu, .5, (x, y), (22.7, y))
    hexa("GND", 3, 57.4, 9.8, 59.5)
    for x in CAPX:
        for dx in (-1.95, 2.1):
            for y in (39.3, 40.4, 42):
                via("VBUS", x + dx, y)
            for y in (30.8, 31.9, 33, 34.1):
                via("GND", x + dx, y)
    OFF[1] = -11
    for i, (ph, c) in enumerate(COLS.items()):
        hs, ls = "Q%d" % (1 + 2 * i), "Q%d" % (2 + 2 * i)
        sh, sp = net_of(hs, "1"), net_of(ls, "1")
        gh, gl = net_of(hs, "4"), net_of(ls, "4")
        spk, snk = net_of("NT%d" % (1 + 2 * i), "1"), net_of("NT%d" % (2 + 2 * i), "1")
        # 相: モーターパッドまでの帯は4層とも使う
        zone(sh, [F_Cu], [(c - 10.6, 60.1), (c + 1.25, 60.1), (c + 1.25, 61.5), (c + 5.1, 61.8), (c + 5.1, 64.8), (c + 3.2, 64.8),
                          (c + 3.2, 67), (c - 3.1, 67), (c - 3.1, 75.3), (c - 10.6, 75.3)], 4)
        zone(sh, [In1_Cu, In2_Cu], rect(c - 10.6, 60.2, c - 4.3, 75.3), 4)
        zone(sh, [B_Cu], [(c - 10.6, 60.2), (c - 3.1, 60.2), (c - 3.1, 73.3), (c - 3, 73.3), (c - 3, 75.3), (c - 10.6, 75.3)], 4)
        zone(sp, [F_Cu], [(c - 2.55, 67.4), (c + 1.25, 67.4), (c + 1.25, 71.2), (c - .1, 71.4), (c - .1, 72.8), (c - 2.55, 72.8)], 4)
        zone(sp, [B_Cu], rect(c - 2.7, 61.9, c + 1.6, 72.4), 4)
        for x, y in ((-2.2, 69.1), (-2.2, 70), (-2.2, 70.9), (-2.2, 71.8), (.25, 69.15), (.95, 69.2), (.25, 70.1), (.95, 70.2)):
            via(sp, c + x, y)
        hexa(sh, c - 10.1, 60.9, c - 4.8, 68.5, .9, .78, .5)
        for x in (-9.6, -7.2, -4.8):
            for y in (55.5, 57.5):
                # TVSのパッドの下は避ける
                via("VBUS", c + x, y)
        for x in (-3.6, -1.2, 1.2):
            via("VBUS", c + x, 54.4)
        for y in (55.3, 56.5, 57.7):
            via("VBUS", c + 6.7, y)
        for y in (56.5, 58.3):
            via("VBUS", c - 3.5, y)
        for x in (-4.8, -3.6, -2.4, -1.2, 0, 1.2):
            if c + x > 20.2:
                if ph == "A":
                    via("GND", c + x, 48.78, .5)
                else:
                    via("GND", c + x, 48.5)
                    via("GND", c + x, 47.4)
        gv = [(x, y) for x in (3.5, 4.3, 5, 5.7) for y in (73.5, 74.4, 75.3, 76.3, 77.3)] + [(6.2, y) for y in (70.2, 71.3, 72.4)]
        gv += [(x, yy) for yy in (76.4, 77.6) for x in (-9.6, -8.4, -7.2, -6, -4.8, -3.6, -2.4, -1.2, 0, 1.2, 2.4)]
        for x, y in gv:
            # 右下のねじの座面にかかるビアは置かない
            if (c + x - 76.5) ** 2 + (y - 11 - 63.5) ** 2 > 3.5 ** 2:
                via("GND", c + x, y)
        # ゲート・検出線の縦束（裏面）。並びをDRVのピン順に合わせる（Bだけ逆順）
        Y0 = 50
        if ph == "B":
            xgh, xsh, xgl, xsp, xsn = 5.3, 4.7, 4.1, 2.65, 2.2
            psp = [(1.6, 72.2), (2.3, 72.9), (2.9, 72.9), (3.4, 72.4), (3.4, 71.1), (2.65, 70.35)]
            psn = [(2.4, 72.2), (2.2, 72)]
        else:
            xgh, xsh, xgl, xsp, xsn = 2.7, 3.4, 4.1, 5.5, 5.95
            psp = [(1.6, 72.2), (5.5, 68.3)]
            psn = [(2.4, 72.2), (5.95, 68.65)]
        via(gh, c + xgh, 60.65)
        trk(gh, F_Cu, .25, (c + 1.91, 60.65), (c + 5, 60.65))
        trk(gh, B_Cu, .25, (c + xgh, 60.65), (c + xgh, Y0))
        via(sh, c + xsh, 62.6)
        trk(sh, B_Cu, .25, (c + xsh, 62.6), (c + xsh, Y0))
        via(gl, c + xgl, 68.05)
        trk(gl, F_Cu, .25, (c + 1.91, 68.05), (c + xgl, 68.05), (c + 4.1, 67.25), (c + 4.1, 66.3))
        trk(gl, B_Cu, .25, (c + xgl, 68.05), (c + xgl, Y0))
        for nn, x0, lane, pts in ((spk, .8, xsp, psp), (snk, 3.2, xsn, psn)):
            vx, vy = pts[0]
            via(nn, c + vx, vy, .5)
            trk(nn, F_Cu, .2, (c + x0, 72.2), (c + vx, vy))
            trk(nn, B_Cu, .2, *([(c + x, y) for x, y in pts] + [(c + lane, Y0)]))
    # 5V降圧
    OFF[:] = [0, 0]
    # SW: pin45 → C17 → D3 → L1。入力ループ(C14-VIN-SW-D3-GND)を表面だけで閉じる
    zone(net_of("U2", "45"), [F_Cu], [(42.4, 20), (42.68, 20.3), (42.68, 20.9), (42.92, 20.9), (42.92, 18.9), (44.1, 18.7), (44.3, 17.8),
                                      (47.6, 17.8), (47.6, 15.2), (46.4, 15.2), (46.4, 8.2), (44.7, 8.2), (44.7, 17.4), (42.4, 17.5)], 6)
    zone("+5V", [F_Cu], rect(49.2, 8.2, 52.8, 13.8), 6)
    zone("VBUS", [F_Cu], [(37.7, 18.2), (40.4, 18.2), (41.4, 19.4), (42, 20.1), (42, 20.9), (41.6, 20.9), (41.4, 20.2), (40.2, 19.7), (37.7, 19.7)], 6)
    zone("GND", [F_Cu], rect(37.7, 14.3, 43.6, 17.1), 5)
    for x in (38.3, 39.3, 40.3, 41.5, 42.5, 43.3):
        via("GND", x, 14.75)
    for x, y, x1, y1 in ((55.9, 10, 55, 10.4), (55.9, 10.9, 55, 10.9), (55.9, 11.8, 55, 11.4)):
        via("GND", x, y)
        trk("GND", F_Cu, .5, (x, y), (x1, y1))
    trk(net_of("U2", "45"), F_Cu, .25, (42.8, 20.65), (42.8, 19.2))
    # VMピンからC12へ太い線で直結
    trk("VBUS", F_Cu, .28, (40.3, 23.8), (38.9, 23.8), (38.2, 24.9), (38.2, 25.6), (37.4, 26.2))
    # GNDピンはサーマルパッドへ直結
    u2 = b.FindFootprintByReference("U2")
    for p in u2.Pads():
        n = p.GetNumber()
        x, y = p.GetPosition().x / 1e6, p.GetPosition().y / 1e6
        if n in ("2",):
            trk("GND", F_Cu, .2, (x, y), (42, y))
        if n in ("27", "29", "35"):
            trk("GND", F_Cu, .2, (x, y), (46.1, y))
        if n == "43":
            trk("GND", F_Cu, .2, (x, y), (x, 22.2))
        # 放熱ビアは0.2mm穴だと割増になるので0.3mmにする
        if n == "49" and p.GetDrillSizeX():
            p.SetDrillSize(V(.3, .3))
            p.SetSize(V(.5, .5))
    for f in b.Footprints():
        for p in f.Pads():
            if f.GetReference()[0] in "QCRD" and p.GetNetname() not in ("GND", "GND_ISO"):
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
            if f.GetReference() in ("R11", "R13", "R15", "J1", "D1", "C1", "C2", "C3", "C19", "C20", "C22", "C23", "C25", "C26", "C7", "C8", "C39", "U2") or f.GetReference() == "J1":
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    # 表示
    def text(t, x, y, size=1.0, side=F_Cu):
        s = pcbnew.PCB_TEXT(b)
        s.SetText(t)
        s.SetPosition(V(x, y))
        s.SetLayer(pcbnew.F_SilkS if side == F_Cu else pcbnew.B_SilkS)
        s.SetMirrored(side == B_Cu)
        s.SetTextSize(V(size, size))
        s.SetTextThickness(MM(size * .15))
        b.Add(s)
    for side in (F_Cu, B_Cu):
        for t, c in COLS.items():
            text(t, c - 3.2, 66, 1.4, side)
    text("+++", 4.2, 45.6, .9, B_Cu)
    text("---", 4.2, 52.8, .9, B_Cu)
    # 1番ピンから順に並べた信号名。ENC1だけSSI（絶対値）にも使える
    for y in (53.0, 44.5):
        for i, t in enumerate(("3", "G", "A", "B", "Z")):
            text(t, 67.6 + 2.5 * i, y, .8)
    text("ENC1", 79.3, 52.6, .8)
    text("ENC2", 66.2, 63.6 - 18.9, .8)
    for i, t in enumerate(("ENC1 SSI", "A=DO", "B=CLK", "Z=CSN")):
        text(t, 69.2, 62.8 + 1.25 * i, .8)
    for i, t in enumerate(("5", "D", "C", "R", "G")):
        text(t, 62.3 + 2 * i, 1.4, .8)
    text("SWD", 59.4, 1.4, .8)
    text("RESET", 76.4, 15.2, .8)
    text("HARD PANCAKE", 24.6, 28.9, .9)
    text("r1", 31, 28.9, .8)
    text("CAN", 17.7, 33.6, .9)
    text("ISOLATED", 22.5, 4, .8)
    for i, t in enumerate(("SOA", "SOB", "SOC", "FLT", "DVD", "GND")):
        text(t, 54.6 + 2.6 * i, 27.7, .8)
    ds = b.GetDesignSettings()
    ds.m_MinClearance = MM(.13)
    ds.m_TrackMinWidth = MM(.15)
    ds.m_ViasMinSize = MM(.5)
    ds.m_MinThroughDrill = MM(.3)
    ds.m_CopperEdgeClearance = MM(.3)
    b.Save(os.path.join(BUILD, "placed.kicad_pcb"))

    geo = dict(pads=[], zones=zones, vias=vias, tracks=tracks, MAIN=MAIN, ISO=ISO, P3V3=P3V3, TOP=39, KEEP=[(44.2, 7.6, 51.2, 14.2), (41, 14.4, 47.7, 18.4)], VBUS_IN2=VBUS_IN2, NOGND=[rect(c - 10.6, 49.2, c - 4.3, 64.3) for c in COLS.values()])
    for f in b.Footprints():
        for p in f.Pads():
            ps = pcbnew.SHAPE_POLY_SET()
            layers = [l for l in (F_Cu, B_Cu) if p.IsOnLayer(l)]
            hole = p.GetDrillSizeX() > 0
            p.TransformShapeToPolygon(ps, layers[0] if layers else F_Cu, 0, MM(.005), pcbnew.ERROR_OUTSIDE)
            polys = [[(ps.Outline(k).CPoint(j).x / 1e6, ps.Outline(k).CPoint(j).y / 1e6)
                      for j in range(ps.Outline(k).PointCount())] for k in range(ps.OutlineCount())]
            geo["pads"].append(dict(ref=f.GetReference(), num=p.GetNumber(), net=p.GetNetname(), polys=polys,
                                    layers=[b.GetLayerName(l) for l in layers], th=hole,
                                    x=p.GetPosition().x / 1e6, y=p.GetPosition().y / 1e6))
    json.dump(geo, open(os.path.join(BUILD, "geo.json"), "w"))
    # 外形の重なり
    cy = [(f.GetReference(), f.GetCourtyard(F_Cu if False else pcbnew.F_CrtYd)) for f in b.Footprints()]
    for i in range(len(cy)):
        for j in range(i):
            if cy[i][1].OutlineCount() and cy[j][1].OutlineCount():
                q = pcbnew.SHAPE_POLY_SET(cy[i][1])
                q.BooleanIntersection(cy[j][1])
                if q.OutlineCount() and q.Area() > 1e9:
                    print("overlap", cy[i][0], cy[j][0], round(q.Area() / 1e12, 3))


def finish():
    b = pcbnew.LoadBoard(os.path.join(BUILD, "placed.kicad_pcb"))
    r = json.load(open(os.path.join(ROOT, "tools", "routes.json")))
    L = {"F.Cu": F_Cu, "B.Cu": B_Cu}
    for net, layer, w, p, q in r["tracks"]:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(V(*p))
        t.SetEnd(V(*q))
        t.SetWidth(MM(w))
        t.SetLayer(L[layer])
        t.SetNet(b.FindNet(net))
        b.Add(t)
    for net, x, y, d in r["vias"]:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(V(x, y))
        v.SetWidth(MM(d))
        v.SetDrill(MM(.3))
        v.SetNet(b.FindNet(net))
        b.Add(v)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(OUT)


os.makedirs(BUILD, exist_ok=True)
{"place": place, "finish": finish}[sys.argv[1]]()

"""Freeroutingで配線する（2026-11-26、自作の route_pcb.py の代わり）。KiCad 10付属のpythonで実行。

  <KiCad>/bin/python tools/fr_route.py base     placed.kicad_pcb に電源段の束を足す → build/placed_fr.kicad_pcb
  <KiCad>/bin/python tools/fr_route.py export   build/placed.kicad_pcb → build/fr/pancake.dsn
  tools/build/fr/cli/freerouting-cli.exe -de tools/build/fr/pancake.dsn -do tools/build/fr/pancake.ses -mp 100
  <KiCad>/bin/python tools/fr_route.py import   SESを取り込み、ゾーンを充填して kicad/pancake.kicad_pcb へ

- gen_pcb.py place で置いた電源段の配線・ビアは固定（ロック）して渡す
- 内層（In1・In2）は電源層にして信号を通さない（GND・+3V3・VBUS・GND_ISOはビアで内層へ落とす）
- 表裏のGNDベタ（全面）はDSNから外す。残すと全面が障害物になる。取り込み後に充填する
- 電源段のゲート線・SH線・検出線（15本）と、Freeroutingが引けなかったU2-SOC（U2〜TP12）・U2-VDRAINは、束（レーン）を通す前の配線（route_pcb.py、81mm版）を tools/routes_bundle.json から固定で入れる
  （Freeroutingに任せると束を使わず、検出線のSP/SNが離れて走る）
- 線幅は route_pcb.py の wclass と同じ（0.4/0.25/0.2）。検出線は0.2で間隔を広く取る
"""
import os
import re
import sys

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "tools", "build")
DSN = os.path.join(BUILD, "fr", "pancake.dsn")
SES = os.path.join(BUILD, "fr", "pancake.ses")
OUT = os.path.join(ROOT, "kicad", "pancake.kicad_pcb")
PLANE_NETS = ("GND", "GND_ISO", "+3V3", "VBUS")
# gen_pcb.py の geo["KEEP"]（降圧のスイッチング部。表裏とも配線・ビア禁止）
KEEP = [(44.2, 7.6, 51.2, 14.2), (41, 14.4, 47.7, 18.4)]
MM = pcbnew.FromMM


def wclass(net):
    if net in ("+5V", "Net-(U1-EN)", "/制御 (MCU・CAN・エンコーダ)/SWD_5V", "Net-(U6-VISOIN)", "Net-(J8-Pad4)"):
        return "W40"
    if net.startswith("Net-(U2-S") and net[-2] in "ABC" and net[9] in "PN":
        return "SENSE"
    if net.startswith("Net-(Q") or net in ("Net-(J2-Pin_1)", "Net-(J3-Pin_1)", "Net-(J4-Pin_1)", "Net-(U2-CPH)", "Net-(U2-CPL)",
                                           "Net-(U2-VCP)", "Net-(U2-CB)", "Net-(D3-K)"):
        return "W25"
    return None


RULES = {"W40": (.4, .155), "W25": (.25, .155), "SENSE": (.2, .3)}


def base():
    """配置済みの盤に、電源段の束の配線を固定で足したもの"""
    import json
    b = pcbnew.LoadBoard(os.path.join(BUILD, "placed.kicad_pcb"))
    # 前回の配線（route_pcb.py、81mm版、DRC済み）のうち、動かした部品（J5・J6・C49・C50）につながるネット以外を固定で残す
    moved = set()
    for f in b.Footprints():
        if f.GetReference() in ("J5", "J6", "C49", "C50"):
            moved |= {p.GetNetname() for p in f.Pads()}
    moved -= set(PLANE_NETS)
    r = json.load(open(os.path.join(ROOT, "tools", "routes_81.json"), encoding="utf-8"))
    r = dict(tracks=[t for t in r["tracks"] if t[0] not in moved], vias=[v for v in r["vias"] if v[0] not in moved])
    print("reroute", sorted(moved))
    L = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
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
    # 足したままDSNに書き出すとKiCadが落ちるので、一度保存して読み直す
    f = os.path.join(BUILD, "placed_fr.kicad_pcb")
    b.Save(f)
    return f


def export():
    b = pcbnew.LoadBoard(FR_BASE)
    for l in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        b.SetLayerType(l, pcbnew.LT_POWER)
    for t in b.GetTracks():
        t.SetLocked(True)
    for z in list(b.Zones()):
        # 表裏のGNDの全面ベタ（優先度0）だけ外す。電源段の銅（優先度3以上）は障害物として残す
        if z.GetNetname() in ("GND", "GND_ISO") and z.GetAssignedPriority() == 0 and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
            b.Remove(z)
    for x0, y0, x1, y1 in KEEP:
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowZoneFills(False)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.B_Cu)
        z.SetLayerSet(ls)
        o = pcbnew.SHAPE_POLY_SET()
        o.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(MM(x), MM(y))
        z.SetOutline(o)
        b.Add(z)
    os.makedirs(os.path.dirname(DSN), exist_ok=True)
    if not pcbnew.ExportSpecctraDSN(b, DSN):
        raise SystemExit("DSN export failed")
    # ネットクラスを作り直す（KiCadの既定は線幅0.2・間隔0.2の1クラスだけ）
    s = open(DSN, encoding="utf-8").read()
    nets = re.findall(r'^    \(net ("[^"]*"|\S+)$', s, re.M)
    groups = {}
    for n in nets:
        groups.setdefault(wclass(n.strip('"')) or "DEF", []).append(n)
    rules = dict(RULES, DEF=(.2, .155))
    blk = ""
    for c, ns in groups.items():
        w, cl = rules[c]
        blk += ('    (class %s %s\n      (circuit (use_via "Via[0-3]_500:300_um"))\n      (rule (width %g) (clearance %g))\n    )\n'
                % (c, " ".join(ns), w * 1000, cl * 1000))
    a = s.index("    (class kicad_default")
    e = s.index("  )\n  (wiring")
    s = s[:a] + blk + s[e:]
    s = s.replace("      (clearance 200)\n      (clearance 50 (type smd_smd))", "      (clearance 155)\n      (clearance 50 (type smd_smd))")
    open(DSN, "w", encoding="utf-8").write(s)
    print("nets", len(nets), {c: len(v) for c, v in groups.items()})


def imp():
    # SESをそのまま取り込むと固定のビア（電源段のつなぎ）が消えるので、別の盤に取り込んで新しい配線・ビアだけ足す
    src = pcbnew.LoadBoard(os.path.join(BUILD, "placed.kicad_pcb"))
    if not pcbnew.ImportSpecctraSES(src, SES):
        raise SystemExit("SES import failed")
    b = pcbnew.LoadBoard(FR_BASE)
    key = lambda t: (t.GetNetname(), round(t.GetStart().x / 1e4), round(t.GetStart().y / 1e4), round(t.GetEnd().x / 1e4),
                     round(t.GetEnd().y / 1e4), t.GetLayer() if t.Type() == pcbnew.PCB_TRACE_T else -1)
    have = set()
    for t in b.GetTracks():
        have.add(key(t))
        if t.Type() == pcbnew.PCB_TRACE_T:   # 向きが逆でも同じ線
            have.add((t.GetNetname(), round(t.GetEnd().x / 1e4), round(t.GetEnd().y / 1e4), round(t.GetStart().x / 1e4),
                      round(t.GetStart().y / 1e4), t.GetLayer()))
    fixed = [(t.GetNetname(), t.GetLayer(), t.GetStart(), t.GetEnd()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]

    def on_fixed(t):
        # 両端が同じネット・同じ層の固定の線の上にあれば、その線の写し
        def on(p, a, c):
            ax, ay, cx, cy, px, py = a.x, a.y, c.x, c.y, p.x, p.y
            L2 = (cx - ax) ** 2 + (cy - ay) ** 2
            u = 0 if L2 == 0 else max(0, min(1, ((px - ax) * (cx - ax) + (py - ay) * (cy - ay)) / L2))
            return (ax + u * (cx - ax) - px) ** 2 + (ay + u * (cy - ay) - py) ** 2 < 2e4 ** 2
        return any(n == t.GetNetname() and l == t.GetLayer() and on(t.GetStart(), a, c) and on(t.GetEnd(), a, c) for n, l, a, c in fixed)
    nt = nv = 0
    for t in src.GetTracks():
        if key(t) in have or (t.Type() == pcbnew.PCB_TRACE_T and on_fixed(t)):
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(t.GetPosition())
            v.SetWidth(t.GetWidth(pcbnew.F_Cu))
            v.SetDrill(t.GetDrillValue())
            nv += 1
            n = v
        else:
            n = pcbnew.PCB_TRACK(b)
            n.SetStart(t.GetStart())
            n.SetEnd(t.GetEnd())
            n.SetWidth(t.GetWidth())
            n.SetLayer(t.GetLayer())
            nt += 1
        n.SetNet(b.FindNet(t.GetNetname()))
        b.Add(n)
    print("added tracks", nt, "vias", nv, "total", len(b.GetTracks()))
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(OUT)


def final():
    """placed_fr（前回の配線を固定）に route_enc.py の8本を足し、ゾーンを充填して kicad/pancake.kicad_pcb へ"""
    import json
    b = pcbnew.LoadBoard(FR_BASE)
    r = json.load(open(os.path.join(BUILD, "routes_enc.json"), encoding="utf-8"))
    L = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
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


FR_BASE = os.path.join(BUILD, "placed_fr.kicad_pcb")
if sys.argv[1] == "base":
    base()
else:
    {"export": export, "import": imp, "final": final}[sys.argv[1]]()

"""pancake.pretty の自作フットプリント（XT60PW-M、RJ45）を作る。"""
import os
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRETTY = os.path.join(ROOT, "kicad", "pancake.pretty")

# XT60: KiCad標準は1番が−。回路図のJ1は1番がVBUSなので番号を入れ替える
SRC = "C:/Program Files/KiCad/10.0/share/kicad/footprints/Connector_AMASS.pretty/AMASS_XT60PW-M_1x02_P7.20mm_Horizontal.kicad_mod"
s = open(SRC, encoding="utf-8").read()
s = s.replace('(pad "1" thru', '(pad "@" thru').replace('(pad "2" thru', '(pad "1" thru').replace('(pad "@" thru', '(pad "2" thru')
s = s.replace('"AMASS_XT60PW-M_1x02_P7.20mm_Horizontal"', '"XT60PW-M_1plus_2minus"')
open(os.path.join(PRETTY, "XT60PW-M_1plus_2minus.kicad_mod"), "w", encoding="utf-8", newline="\n").write(s)

# RJ45 R-RJ45R08P-A004: LCSC C385834の図面（1.02×7=7.14、列間1.78、ボス2-φ3.25 間隔12.70、ボスから遠い列4.32）。差込口は+Y
N = "RJ45_R-RJ45R08P-A004"
u = lambda: '(uuid "%s")' % uuid.uuid5(uuid.NAMESPACE_DNS, N + str(u.n)) if not setattr(u, "n", u.n + 1) else ""
u.n = 0
o = ['(footprint "%s" (version 20240108) (generator "gen") (layer "F.Cu")' % N,
     '(descr "Ckmtw R-RJ45R08P-A004 (LCSC C385834)") (attr through_hole)',
     '(property "Reference" "REF**" (at 0 -8.6 0) (layer "F.SilkS") %s (effects (font (size 1 1) (thickness 0.15))))' % u(),
     '(property "Value" "%s" (at 0 9 0) (layer "F.Fab") %s (effects (font (size 1 1) (thickness 0.15))))' % (N, u())]
for layer, x, y0, y1, w in (("F.Fab", 7.95, -7.36, 7.74, .1), ("F.CrtYd", 8.2, -7.6, 8, .05)):
    o.append('(fp_rect (start %s %s) (end %s %s) (stroke (width %s) (type solid)) (fill none) (layer "%s") %s)' % (-x, y0, x, y1, w, layer, u()))
for a, b, c, d in ((-8.05, -7.46, 8.05, -7.46), (-8.05, -7.46, -8.05, 6.8), (8.05, -7.46, 8.05, 6.8)):
    o.append('(fp_line (start %s %s) (end %s %s) (stroke (width 0.12) (type solid)) (layer "F.SilkS") %s)' % (a, b, c, d, u()))
o.append('(fp_text user "1" (at 5.2 0 0) (layer "F.SilkS") %s (effects (font (size 1 1) (thickness 0.15))))' % u())
for n in range(1, 9):
    o.append('(pad "%d" thru_hole %s (at %.2f %s) (size 1.4 1.4) (drill 0.9) (layers "*.Cu" "*.Mask") %s)'
             % (n, "rect" if n == 1 else "circle", 3.57 - 1.02 * (n - 1), 0 if n % 2 else -1.78, u()))
for x in (-6.35, 6.35):
    o.append('(pad "" np_thru_hole circle (at %s 2.54) (size 3.25 3.25) (drill 3.25) (layers "*.Cu" "*.Mask") %s)' % (x, u()))
o.append(")")
open(os.path.join(PRETTY, N + ".kicad_mod"), "w", encoding="utf-8", newline="\n").write("\n".join(o) + "\n")

# モーター線パッド: moteus r5 の POWER_M2.5（4.07mm角）を30A・AWG14用に6mm角へ拡大。ビア穴は0.3mm
import math
K = 6 / 4.07


def fp(name, attr, cy, pads):
    global N
    N = name
    u.n = 0
    o = ['(footprint "%s" (version 20240108) (generator "gen") (layer "F.Cu") (attr through_hole %s)' % (N, attr),
         '(property "Reference" "REF**" (at 0 -4 0) (layer "F.SilkS") %s (effects (font (size 1 1) (thickness 0.15))))' % u(),
         '(property "Value" "%s" (at 0 4 0) (layer "F.Fab") %s (effects (font (size 1 1) (thickness 0.15))))' % (N, u()),
         '(fp_rect (start %s %s) (end %s %s) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd") %s)' % (-cy, -cy, cy, cy, u())]
    for num, sh, x, y, size, drill in pads:
        o.append('(pad "%s" thru_hole %s (at %.3f %.3f) (size %s %s) (drill %s) (layers "*.Cu" "*.Mask") (zone_connect 2) %s %s)'
                 % (num, sh, x, y, size, size, drill, "(roundrect_rratio 0.07)" if sh == "roundrect" else "", u()))
    o.append(")")
    open(os.path.join(PRETTY, N + ".kicad_mod"), "w", encoding="utf-8", newline=chr(10)).write(chr(10).join(o) + chr(10))


pads = [("1", "roundrect", 0, 0, 6, 2.8)]
pads += [("1", "circle", sx * 1.27 * K, sy * 1.27 * K, 1.8, 1.3) for sx in (-1, 1) for sy in (-1, 1)]
for t, e in ((-.55, 1.75), (0, 1.75), (.55, 1.75), (-.275, 1.323), (.275, 1.323)):
    for g in (-1, 1):
        pads += [("1", "circle", t * K, g * e * K, .5, .3), ("1", "circle", g * e * K, t * K, .5, .3)]
fp("MotorPad_6x6_moteus", "exclude_from_pos_files exclude_from_bom", 3.1, pads)
# 取付穴: moteus r5 の M3_MOUNT_CORNER（どのネットにもつながない）
pads = [("1", "circle", 0, 0, 5.45, 3.2)]
pads += [("1", "circle", 2.2 * math.cos(k * math.pi / 4), 2.2 * math.sin(k * math.pi / 4), .46, .3) for k in range(8)]
fp("M3_Mount_moteus", "exclude_from_pos_files exclude_from_bom", 2.9, pads)

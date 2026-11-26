"""JLCPCB発注用の製造データを kicad/production/ に出す（ガーバー・ドリル・BOM・CPL）。

実行: python tools/export_jlc.py   （KiCad 10 の kicad-cli を使う）
- ガーバー・ドリルは zip にまとめる（JLCのPCB注文にそのまま上げる）
- BOM は LCSC番号でまとめる。DNP・BOM除外（テストポイント・取付穴・モーターパッド・ネットタイ）は入れない。
  手はんだの部品（HAND）はJLCのBOM・CPLから外し、pancake_bom_hand.csv に出す
- CPL の回転は KiCad の値に、JLCとKiCadで基準が違うパッケージの補正を足したもの。補正表は
  kicad-jlcpcb-tools の既定表に倣った推定なので、発注画面の部品配置プレビューで極性・向きを必ず目で確かめる
"""
import csv
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
PCB = os.path.join(ROOT, "kicad", "pancake.kicad_pcb")
SCH = os.path.join(ROOT, "kicad", "pancake.kicad_sch")
OUT = os.path.join(ROOT, "kicad", "production")
GBR = os.path.join(OUT, "gerber")

# LCSC番号ごとに足す角度。tools/jlc_rotation.py で JLC(EasyEDA)のフットプリントのパッド番号の配置と KiCad のものを
# 突き合わせ、EasyEDA = KiCad を d°回したもの、となる d から 補正 = -d とした（2026-11-26）。JLCの回転は反時計回りを正とみなす。
# 同じSOT-23-5でも部品ごとにEasyEDAの向きが違う（RT9013は270°、SN74LVC1G17は180°）ので、フットプリント名でなくLCSC番号で持つ。
# LQFP-48が270°になるのは kicad-jlcpcb-tools の既定表と一致。XT60(C98732)はパッド番号の振り方が違い照合できないので要目視。
ROT = {"C46528099": 180, "C113998": 180, "C37704": 180, "C2481": 0, "C2286": 180, "C246766": 180, "C225449": 180,
       "C157991": 180, "C157993": 180, "C385834": 180, "C83454": 0, "C145537": 90, "C318884": 0, "C47773": 270,
       "C543035": 0, "C529355": 270, "C558419": 90, "C22438481": 0, "C7836": 180, "C5308003": 180, "C98732": 0, "C13564": 0, "C13832": 0}
# 手はんだする部品（JLCのBOM・CPLから外し、pancake_bom_hand.csv に出す）。コネクタと、手はんだできるExtended部品（2026-11-26 本人方針）。
# Extendedでも JLC に残すのはリフローが要るもの: Q(SO-8FLの露出パッド)、U2(QFN)、U3(LQFP 0.5mm)、U6(LGA)、Y1(裏面電極)。BOM.md と対応させる
HAND = {"C98732": "XT60", "C385834": "RJ45", "C157993": "JST PH", "C225449": "JST XA", "C46528099": "電解 10×10.5",
        "C55151": "1210", "C710260": "2512", "C83454": "6×6インダクタ", "C113998": "SMB", "C2481": "SMA", "C246766": "SOT-23",
        "C47773": "SOT-23-5", "C558419": "SOT-23-6", "C7836": "SOT-23-5", "C13564": "0603", "C13832": "1206"}


def run(*a):
    r = subprocess.run([K, *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit("kicad-cli 失敗: %s\n%s%s" % (" ".join(a), r.stdout, r.stderr))
    return r.stdout


def main():
    os.makedirs(GBR, exist_ok=True)
    for f in os.listdir(GBR):
        os.remove(os.path.join(GBR, f))
    layers = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
    run("pcb", "export", "gerbers", "--check-zones", "--subtract-soldermask", "-l", layers, "-o", GBR, PCB)
    run("pcb", "export", "drill", "--format", "excellon", "--drill-origin", "absolute", "--excellon-units", "mm",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", "-o", GBR + os.sep, PCB)
    zp = os.path.join(OUT, "pancake_gerber.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(GBR)):
            z.write(os.path.join(GBR, f), f)

    # BOM（回路図のネットリストから。LCSC番号でまとめる）
    xml = os.path.join(OUT, "pancake.xml")
    run("sch", "export", "netlist", "--format", "kicadxml", "-o", xml, SCH)
    groups, missing = {}, []
    for c in ET.parse(xml).getroot().find("components"):
        p = {x.get("name"): x.get("value") for x in c.findall("property")}
        if "dnp" in p or "exclude_from_bom" in p:
            continue
        ref, val = c.get("ref"), c.findtext("value")
        fp = (c.findtext("footprint") or "").split(":")[-1]
        lcsc = p.get("LCSC", "")
        if not lcsc:
            missing.append(ref)
        g = groups.setdefault((lcsc, val, fp), [])
        g.append(ref)
    key = lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0))
    order = lambda t: key(sorted(t[1], key=key)[0])
    hand = {k: v for k, v in groups.items() if k[0] in HAND}
    groups = {k: v for k, v in groups.items() if k[0] not in HAND}
    with open(os.path.join(OUT, "pancake_bom_jlc.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (lcsc, val, fp), refs in sorted(groups.items(), key=order):
            w.writerow([val, ",".join(sorted(refs, key=key)), fp, lcsc])
    with open(os.path.join(OUT, "pancake_bom_hand.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Qty", "Footprint", "LCSC Part #"])
        for (lcsc, val, fp), refs in sorted(hand.items(), key=order):
            w.writerow([val, ",".join(sorted(refs, key=key)), len(refs), fp, lcsc])
    bom_refs = {r for refs in groups.values() for r in refs}
    ref_lcsc = {r: k[0] for k, refs in groups.items() for r in refs}

    # CPL
    pos = os.path.join(OUT, "pos.csv")
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp", "-o", pos, PCB)
    rows, unknown = [], set()
    with open(pos, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ref = r["Ref"]
            if ref not in bom_refs:
                continue
            rot = float(r["Rot"])
            lc = ref_lcsc.get(ref, "")
            if lc in ROT:
                rot += ROT[lc]
            elif not re.match(r"^[RC]\d", ref):
                unknown.add(ref)
            rows.append([ref, "%.4fmm" % float(r["PosX"]), "%.4fmm" % float(r["PosY"]),
                         "Top" if r["Side"] == "top" else "Bottom", "%g" % (rot % 360)])
    os.remove(pos)
    with open(os.path.join(OUT, "pancake_cpl_jlc.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(sorted(rows, key=lambda t: key(t[0])))
    no_pos = sorted(bom_refs - {r[0] for r in rows}, key=key)
    print("gerber:", zp)
    print("JLC: BOM %d行 / 部品%d個、CPL %d個。手はんだ: %d行 / %d個" % (
        len(groups), len(bom_refs), len(rows), len(hand), sum(len(v) for v in hand.values())))
    if missing:
        print("LCSC番号なし:", ",".join(sorted(missing, key=key)))
    if unknown:
        print("回転の補正が未照合（JLCのプレビューで要確認）:", ",".join(sorted(unknown, key=key)))
    if no_pos:
        print("CPLに無い（基板に無い）:", ",".join(no_pos))


if __name__ == "__main__":
    main()

"""JLCPCB発注用の製造データを kicad/production/ に出す（ガーバー・ドリル・BOM・CPL）。

実行: python tools/export_jlc.py   （KiCad 10 の kicad-cli を使う）
- ガーバー・ドリルは zip にまとめる（JLCのPCB注文にそのまま上げる）
- BOM は LCSC番号でまとめる。DNP・BOM除外（テストポイント・取付穴・モーターパッド・ネットタイ）は入れない
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

# (フットプリント名の正規表現, 足す角度)。tools/jlc_rotation.py で、JLC(EasyEDA)のフットプリントのパッド番号の配置と
# KiCadのものを突き合わせて求めた（2026-11-26）。JLCの回転は反時計回りを正とみなしている（90/270の部品はこの前提に依存）。
# 一致を確かめたもの: SOT-23(D2,D6) 180、SOT-23-5(U1) 270、SO-8FL(Q) 90、VQFN-48(U2) 0、CP_Elec 180、SMB 180、SMA 0、
# LED_0603 180、JST XH/PH 180、RJ45 180、SWPA6045S 0、TS-1187A 0（同番号パッドの組で確認）。
# LQFP-48・SOT-23-6・CA-IS2062A・水晶はEasyEDAの取得が制限で失敗し未確認（0のまま）。発注画面のプレビューで必ず確かめる
ROT = [(r"^SOT-23-5", 270), (r"^SOT-23-6", 0), (r"^SOT-23$", 180), (r"^ONSemi_SO-8FL", 90), (r"^CP_Elec_", 180),
       (r"^D_SMB", 180), (r"^LED_0603", 180), (r"^JST_XH_", 180), (r"^JST_PH_", 180), (r"^RJ45_", 180)]


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
    with open(os.path.join(OUT, "pancake_bom_jlc.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (lcsc, val, fp), refs in sorted(groups.items(), key=lambda t: key(sorted(t[1], key=key)[0])):
            w.writerow([val, ",".join(sorted(refs, key=key)), fp, lcsc])
    bom_refs = {r for refs in groups.values() for r in refs}

    # CPL
    pos = os.path.join(OUT, "pos.csv")
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp", "-o", pos, PCB)
    rows = []
    with open(pos, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ref = r["Ref"]
            if ref not in bom_refs:
                continue
            rot = float(r["Rot"])
            for pat, add in ROT:
                if re.search(pat, r["Package"]):
                    rot += add
                    break
            rows.append([ref, "%.4fmm" % float(r["PosX"]), "%.4fmm" % float(r["PosY"]),
                         "Top" if r["Side"] == "top" else "Bottom", "%g" % (rot % 360)])
    os.remove(pos)
    with open(os.path.join(OUT, "pancake_cpl_jlc.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(sorted(rows, key=lambda t: key(t[0])))
    no_pos = sorted(bom_refs - {r[0] for r in rows}, key=key)
    print("gerber:", zp)
    print("BOM %d行 / 部品%d個、CPL %d個" % (len(groups), len(bom_refs), len(rows)))
    if missing:
        print("LCSC番号なし:", ",".join(sorted(missing, key=key)))
    if no_pos:
        print("CPLに無い（基板に無い）:", ",".join(no_pos))


if __name__ == "__main__":
    main()

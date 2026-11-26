"""JLC(EasyEDA)のフットプリントとKiCadのフットプリントのパッド配置を突き合わせ、CPLの回転補正を求める。
KiCad付属pythonで実行: <KiCad>/bin/python tools/jlc_rotation.py
EasyEDAのパッド座標をLCSC番号ごとに取得し、KiCadのパッド（0°）を0/90/180/270°回したときに番号つきで一番合う角度を出す。
"""
import json, math, os, sys, urllib.request
import pcbnew
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("EDA_CACHE", os.path.join(ROOT, "tools", "build", "eda"))
os.makedirs(CACHE, exist_ok=True)


def eda(lcsc):
    f = os.path.join(CACHE, lcsc + ".json")
    if not os.path.exists(f):
        u = "https://easyeda.com/api/products/%s/components?version=6.4.19.5" % lcsc
        open(f, "wb").write(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "curl/8.0"}), timeout=30).read())
    d = json.load(open(f, encoding="utf-8"))["result"]["packageDetail"]
    ds = d["dataStr"]
    hx, hy = float(ds["head"]["x"]), float(ds["head"]["y"])
    pads = {}
    for s in ds["shape"]:
        if s.startswith("PAD~"):
            a = s.split("~")
            x, y, num = float(a[2]), float(a[3]), a[8]
            pads.setdefault(num, []).append(((x - hx) * 0.254, (y - hy) * 0.254))  # 10mil単位→mm、Y下向き
    return d["title"], pads


def kicad_pads(fp):
    o = fp.GetPosition(); ang = -math.radians(fp.GetOrientationDegrees())
    pads = {}
    for p in fp.Pads():
        q = p.GetPosition()
        dx, dy = pcbnew.ToMM(q.x - o.x), pcbnew.ToMM(q.y - o.y)
        # 基板上の回転を戻して0°の座標にする（Y下向き、角度は反時計回り正）
        c, s = math.cos(-ang), math.sin(-ang)
        x, y = dx * c + dy * s, -dx * s + dy * c
        pads.setdefault(p.GetNumber(), []).append((x, y))
    return pads


def rot(p, deg):  # 見た目で反時計回り(Y下向き座標)
    r = math.radians(deg); c, s = math.cos(r), math.sin(r)
    return (p[0] * c + p[1] * s, -p[0] * s + p[1] * c)


def score(kp, ep, deg):
    err, n = 0, 0
    for num, ks in kp.items():
        if num not in ep or not num:
            continue
        for k in ks:
            r = rot(k, deg)
            err += min(math.hypot(r[0] - e[0], r[1] - e[1]) for e in ep[num]); n += 1
    return err / n if n else 99


def centroid(ps):
    al = [p for v in ps.values() for p in v]
    return sum(p[0] for p in al) / len(al), sum(p[1] for p in al) / len(al)


b = pcbnew.LoadBoard(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "kicad", "pancake.kicad_pcb"))
seen = {}
for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
    f = fp.GetField("LCSC") if hasattr(fp, "GetField") else None
    lcsc = f.GetText() if f else ""
    if not lcsc:
        continue
    name = fp.GetFPID().GetLibItemName().wx_str()
    if name.startswith(("R_0", "C_0", "C_1", "R_1", "R_2")):  # 無極性の2端子は向きを問わない
        continue
    key = (name, lcsc)
    if key in seen:
        continue
    try:
        title, ep = eda(lcsc)
    except Exception as e:
        print("%-6s %-10s %-40s EasyEDA取得失敗 %s" % (fp.GetReference(), lcsc, name, e)); continue
    kp = kicad_pads(fp)
    # パッド重心を合わせる（原点の取り方が違う部品がある）
    kc, ec = centroid(kp), centroid(ep)
    kp = {n: [(x - kc[0], y - kc[1]) for x, y in v] for n, v in kp.items()}
    ep = {n: [(x - ec[0], y - ec[1]) for x, y in v] for n, v in ep.items()}
    res = sorted((score(kp, ep, d), d) for d in (0, 90, 180, 270))
    seen[key] = res[0][1]
    print("%-6s %-10s %-42s %-36s 補正%3d° 誤差%.2fmm (次点%3d° %.2f) ofs=(%.2f,%.2f)" % (
        fp.GetReference(), lcsc, name[:42], title[:36], res[0][1], res[0][0], res[1][1], res[1][0], ec[0] - 0, ec[1] - 0))
json.dump({"%s|%s" % k: v for k, v in seen.items()}, open(os.path.join(CACHE, "rot.json"), "w"), indent=1)

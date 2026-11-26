"""電流容量の目安（IPC-2221の式 I=k·dT^0.44·A^0.725、外層k=0.048・内層k=0.024、Aはmil²）。Saturn本体ではない。"""
def rise(I, w, t=.035, inner=False):
    k = .024 if inner else .048
    a = w * t / 6.4516e-4
    return (I / (k * a ** .725)) ** (1 / .44)
def cap(dT, area_mm2, k=.024):
    return k * dT ** .44 * (area_mm2 / 6.4516e-4) ** .725
import math
for oz, ti in ((1, .0343), (.5, .0152)):
    print("内層 %s oz" % oz)
    for nm, parts in {
        "相の帯 6.3mm×4層": [(6.3, .035, 0), (6.3, .035, 0), (6.3, ti, 1), (6.3, ti, 1)],
        "VBUSバー(列間) L1 7.7+L3 13": [(7.7, .035, 0), (10, ti, 1)],
        "VBUS XT60直後 L1 7+L3 8+L4 7": [(7, .035, 0), (7, .035, 0), (8, ti, 1)],
        "GND 下端帯 3mm×4": [(3, .035, 0), (3, .035, 0), (3, ti, 1), (3, ti, 1)],
        "SP(LS源→シャント) L1 3.4mm": [(3.4, .035, 0)]}.items():
        g = [w * t for w, t, i in parts]
        for I in (8, 15, 30):
            print("  %-30s %2dA dT=%s" % (nm, I, "/".join("%.1f" % rise(I * a / sum(g), w, t, i) for a, (w, t, i) in zip(g, parts))))
a = math.pi * .3 * .02
print("ビア0.3mm(めっき20um) 1本 dT10: 内層式%.2fA 外層式%.2fA dT20: %.2fA" % (cap(10, a), cap(10, a, .048), cap(20, a)))

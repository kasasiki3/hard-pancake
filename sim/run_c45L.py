"""C45〜C47を表面へ移したときの配線の誘導分（L45）でSPxの負側がどう変わるか（2026-11-26）。"""
from bridge_sim import run
new = dict(ld=".9n", lsw=".6n", lsh="1.5n", lret=".5n")
x2 = dict(ld="1.8n", lsw="1.2n", lsh="3n", lret="1n")
for lab, base in (("x1", new), ("x2", x2)):
    for L in ("none", "1n", "3n", "5n", "8n"):
        sn = "" if L == "none" else "L45 dh n45 %s Rpar=100\nC45 n45 sp 0.8u" % L
        for s in (1, -1):
            run("L45_%s_%s_%s" % (lab, L, "out" if s > 0 else "in"), sign=s, lgh="52n", lgl="40n", snub=sn, **base)

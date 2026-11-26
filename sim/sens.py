from bridge_sim import run
b = dict(ld=.9, lsw=.6, lsh=1.5, lret=.5)
for k in (1, 1.3, 1.6, 2):
    p = {a: "%.2fn" % (v * k) for a, v in b.items()}
    for il in (30, 45):
        run("loop x%.1f %dA" % (k, il), il=il, **p)
        run("loop x%.1f %dA C45" % (k, il), il=il, snub="L45 dh n45 3n Rpar=100\nC45 n45 sp 0.8u", **p)

from bridge_sim import run
# ループの寄生は寸法からの概算（L1-L2間0.2mm）。LRET=L2の戻り、LSH=シャント本体
new = dict(ld=".9n", lsw=".6n", lsh="1.5n", lret=".5n")
for ph, g, bk in (("A", "52n", "8n"), ("B", "27n", "7n"), ("C", "56n", "7n")):
    for s in (1, -1):
        run("%s_30A_%s" % (ph, "out" if s > 0 else "in"), sign=s, lgh=g, lgl="40n", lbulk=bk, **new)
run("C_15A_out", sign=1, il=15, lgh="56n", lgl="40n", **new)
run("C_30A_28V", sign=1, vb=28, lgh="56n", lgl="40n", **new)
sn = "Rsn sw s1 2.2\nCsn s1 0 2.2n"
run("C_30A_snub", sign=1, lgh="56n", lgl="40n", snub=sn, **new)

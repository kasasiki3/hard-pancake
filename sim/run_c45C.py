"""C45〜C47の容量（25Vバイアス時の実効値）でSPxの負側がどう変わるか。配線の誘導分は3nH（2026-11-26）。
50V X7R 1206 の25V実効はおよそ 1µF品で0.5µF、2.2µF品で1µF、4.7µF品で2µF（推測、メーカーのDCバイアス特性で要確認）。"""
from bridge_sim import run
new = dict(ld=".9n", lsw=".6n", lsh="1.5n", lret=".5n")
x2 = dict(ld="1.8n", lsw="1.2n", lsh="3n", lret="1n")
for lab, base in (("x1", new), ("x2", x2)):
    for C in ("0.3u", "0.5u", "1u", "2u"):
        for s in (1, -1):
            run("C45C_%s_%s_%s" % (lab, C, "out" if s > 0 else "in"), sign=s, lgh="52n", lgl="40n",
                snub="L45 dh n45 3n Rpar=100\nC45 n45 sp %s" % C, **base)

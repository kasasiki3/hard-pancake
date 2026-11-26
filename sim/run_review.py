"""2026-11-26 査読を受けた追加条件。低側ドライバをPGND基準に直したモデルで、SPの負側・低側の誤点弧(Vto下限)・C45〜C47の効果を見る。
SPx/SNxの絶対最大は連続±1V、200ns過渡±3V。SHxの過渡は-7V。GLxは-0.5V(連続)/-1.5V(過渡)（DRV8323Rデータシート7.1）。"""
from bridge_sim import run
new = dict(ld=".9n", lsw=".6n", lsh="1.5n", lret=".5n")
c45 = "L45 dh n45 1n Rpar=100\nC45 n45 sp 0.8u"
for name, kw in (
        ("nom", {}), ("nom_C45", dict(snub=c45)),
        ("x2", dict(ld="1.8n", lsw="1.2n", lsh="3n", lret="1n")),
        ("x2_C45", dict(ld="1.8n", lsw="1.2n", lsh="3n", lret="1n", snub=c45)),
        ("vto1.2", dict(vto=1.2)), ("vto0.8", dict(vto=0.8)), ("vto0.8_x2", dict(vto=0.8, ld="1.8n", lsw="1.2n", lsh="3n", lret="1n")),
        ("idrv60", dict(isrc="60m", isnk="120m")), ("idrv60_C45", dict(isrc="60m", isnk="120m", snub=c45)),
        ("lpg6n", dict(lpg="6n")), ("lpg6n_vto0.8", dict(lpg="6n", vto=0.8))):
    for s in (1, -1):
        p = dict(new); p.update(kw)
        run("R_%s_%s" % (name, "out" if s > 0 else "in"), sign=s, lgh="52n", lgl="40n", **p)

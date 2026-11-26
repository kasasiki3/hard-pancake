"""ハーフブリッジ＋寄生のLTspiceバッチ。FETはデータシート値から作った近似VDMOS、DRV8323は電流制限の近似。"""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LT = os.path.expandvars(r"%LOCALAPPDATA%\Programs\ADI\LTspice\LTspice.exe")
OUT = os.path.join(HERE, "run")
os.makedirs(OUT, exist_ok=True)
NET = """* half bridge
.param LPK=0.3n LCAP={lcap} LD={ld} LSW={lsw} LSH={lsh} LRET={lret} LGH={lgh} LGL={lgl} IS={isrc} IK={isnk} IL={il} VB={vb}
Vb bat 0 {{VB}}
Rb bat b1 10m
Lb b1 vb 1u Rpar=100
* bulk 100uF (30mohm, ESL) near each phase + other two
Lbk vb k1 {lbulk} Rpar=100
Rbk k1 k2 {rbulk}
Cbk k2 0 100u
Lk2 vb k3 {lbulk2} Rpar=100
Rk2 k3 k4 15m
Ck2 k4 0 200u
* ceramics: 2.2u 100V (1.5u at bias) + 0.1u
Lc1 vb c1 {{LCAP}} Rpar=100
Rc1 c1 c2 4m
Cc1 c2 gl0 1.5u
Lc2 vb c3 0.5n Rpar=100
Rc2 c3 c4 15m
Cc2 c4 gl0 0.09u
Lret gl0 0 {{LRET}} Rpar=100
Ld vb dh {{LD}} Rpar=100
Lhd dh dhi {{LPK}} Rpar=100
M1 dhi ghi shi shi FET
Lhs shi sw {{LPK}} Rpar=100
Lsw sw dl {{LSW}} Rpar=100
Lld dl dli {{LPK}} Rpar=100
M2 dli gli sli sli FET
Lls sli sp {{LPK}} Rpar=100
Rsh sp sn 0.5m
Lsh sn 0 {{LSH}} Rpar=100
* snubber
{snub}
* gate lines
Lgh gh0 gha {{LGH}} Rpar=100
Rgh gha ghi 1.2
Lgl gl00 gla {{LGL}} Rpar=100
Rgl gla gli 1.2
* driver: source IS / sink IK; off side held by 2A strong pulldown while other side on. return = own source trace
Bgh sw gh0 I=limit(1*(V(ch)*10.5-V(gh0,sw)), -(IK+V(cl)*2), IS)
Bgl sp gl00 I=limit(1*(V(cl)*10.5-V(gl00,sp)), -(IK+V(ch)*2), IS)
Vch ch 0 PULSE(0 1 {th} 5n 5n {ton} 100u)
Vcl cl 0 PULSE({cl0} {cl1} {tl} 5n 5n {toff} 100u)
Iload {ldir} 
Cp sw 0 100p
.model FET VDMOS(Rg=0 Vto=2.1 Kp=121 Rd=1.4m Rs=0.4m Rb=1.5m Cgdmax=0.9n Cgdmin=0.028n A=1.2 Cgs=3.55n Cjo=9.5n M=0.5 VJ=0.8 Is=1p TT={tt} BV=66 Ibv=1m Rds=10Meg)
.options reltol=2e-3 abstol=1e-6 vntol=1e-4 cshunt=1e-15
.tran 0 12u 0 1n
.meas TRAN vdsl_pk MAX V(dli,sli) FROM 1u TO 12u
.meas TRAN vdsh_pk MAX V(dhi,shi) FROM 1u TO 12u
.meas TRAN sw_min MIN V(sw) FROM 1u TO 12u
.meas TRAN sw_max MAX V(sw) FROM 1u TO 12u
.meas TRAN gl_bump MAX V(gli,sli) FROM {b0} TO {b1}
.meas TRAN gh_bump MAX V(ghi,shi) FROM {c0} TO {c1}
.meas TRAN gh_pk MAX V(ghi,shi) FROM 1u TO 12u
.meas TRAN gl_pk MAX V(gli,sli) FROM 1u TO 12u
.meas TRAN vb_pk MAX V(vb) FROM 1u TO 12u
.meas TRAN vb_min MIN V(vb) FROM 1u TO 12u
.meas TRAN sh_pk MAX V(sp) FROM 1u TO 12u
.end
"""


def run(name, **k):
    d = dict(lcap="0.35n", ld="1n", lsw=".6n", lsh="1.8n", lret=".8n", lgh="24n", lgl="20n", isrc="30m", isnk="60m", il=30, vb=25.2,
             lbulk="8n", rbulk="30m", lbulk2="10n", snub="", tt="15n", sign=1)
    d.update(k)
    s = d.pop("sign")
    # 電流の向き: +はswから出る（LSダイオード転流）、-は入る（HSダイオード転流）
    d["ldir"] = "sw 0 {IL}" if s > 0 else "0 sw {IL}"
    # LS on -> dead -> HS on -> dead -> LS on
    d.update(th="3u", ton="4u", tl="1.5u", cl0=1, cl1=0, toff="7.5u", b0="3u", b1="7u", c0="9u", c1="12u")
    f = os.path.join(OUT, name + ".cir")
    open(f, "w").write(NET.format(**d))
    subprocess.run([LT, "-b", f], timeout=300, creationflags=0x08000000)
    log = open(f[:-4] + ".log", "rb").read()
    log = log.decode("utf-16-le" if b"\0" in log[:40] else "utf-8", "ignore")
    m = {a.lower(): float(b) for a, b in re.findall(r"(?im)^(\w+_\w+):.*?=\s*([-\d.e+]+)", log)}
    print("%-22s" % name, " ".join("%s=%.1f" % (q, m[q]) for q in m) if m else log[-600:], flush=True)
    return m


if __name__ == "__main__":
    for s in (1, -1):
        t = "out" if s > 0 else "in"
        run("nom_30A_" + t, sign=s)
        run("loop2x_30A_" + t, sign=s, ld="2n", lsw="1.2n", lsh="3.6n", lret="1.6n")
        run("60A_" + t, sign=s, il=60)
        run("idrv60_120_" + t, sign=s, isrc="60m", isnk="120m")
        run("gate_x2_" + t, sign=s, lgh="60n", lgl="60n")

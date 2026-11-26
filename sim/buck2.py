# DRV8323R内蔵降圧(0.7MHz)のSW・VINを、基板のVBUS容量(電解300µF＋C13 10µF＋相の2.2µF)を入れて見る。
# buck.py は電源を1µH＋1.5µFだけで与えていて、LC共振でVINが42Vまで上がる（テストベンチの不備）。
# 内部ハイサイドFETのボディダイオード(DB)とCoss・ピン容量も入れる（無いとLloopの電流の行き場がなくRparで跳ねる）。SS16は0.5V・180pF級の近似
import os, re, subprocess
from bridge_sim import LT, OUT
for lp in ("2n", "8n", "16n"):
    for iload in ("0.05", "0.3", "0.6"):
        n = """buck2
Vin vi 0 25.2
Rb vi b0 20m
Lb b0 bus 50n Rpar=10
Cblk bus cb 300u
Rblk cb 0 10m
Lc bus c1 5n Rpar=50
C13 c1 c13 8u
R13 c13 g0 5m
Cin c1 c2 1.5u
Rc c2 g0 4m
Lloop c1 vin %s Rpar=5
S1 vin sw ctl 0 SW
Dbody sw vin DB
Coss vin sw 100p
Cpin vin g0 100p
Vctl ctl 0 PULSE(0 1 100n 5n 5n 290n 1430n)
Lw sw k 1n Rpar=50
D1 gd k DS
Ld 0 gd 1n Rpar=50
Lg g0 0 0.5n Rpar=50
Cs sw 0 60p
L1 sw out 22u
Co out 0 22u
Iload out 0 %s
.model SW SW(Ron=.9 Roff=1Meg Vt=.5 Vh=-.4)
.model DS D(Is=1u Rs=40m Cjo=180p N=1)
.model DB D(Is=1n Rs=0.5 Cjo=20p N=1.2)
.ic V(out)=5
.tran 0 200u 150u 1n
.meas TRAN sw_min MIN V(sw)
.meas TRAN sw_max MAX V(sw)
.meas TRAN vin_max MAX V(vin)
.meas TRAN vin_min MIN V(vin)
.end
""" % (lp, iload)
        f = os.path.join(OUT, "buck2_%s_%s.cir" % (lp, iload)); open(f, "w").write(n)
        subprocess.run([LT, "-b", f], timeout=300, creationflags=0x08000000)
        t = open(f[:-4] + ".log", "rb").read().replace(b"\0", b"").decode("utf8", "ignore")
        print(lp, iload, " ".join("%s=%.2f" % (a, float(b)) for a, b in re.findall(r"(\w+_m\w+):.*?=([-\d.e+]+)", t)), flush=True)

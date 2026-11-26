# DRV8323R内蔵降圧(0.7MHz)のSWの負側を入力ループLで見る。SS16は0.5V・100pF級の近似
import os,re,subprocess
from bridge_sim import LT,OUT
for lp in ("2n","4n","8n","16n"):
    n="""buck
Vin vi 0 25.2
Lc vi c1 1u Rpar=100
Cin c1 c2 1.5u ic=25.2
Rc c2 g0 4m
Lloop c1 vin %s Rpar=50
S1 vin sw ctl 0 SW
Vctl ctl 0 PULSE(0 1 100n 5n 5n 290n 1430n)
Lw sw k 1n Rpar=50
D1 gd k DS
Ld 0 gd 1n Rpar=50
Lg g0 0 0.5n Rpar=50
Cs sw 0 60p
L1 sw out 22u
Vo out 0 5
.model SW SW(Ron=.9 Roff=1Meg Vt=.5 Vh=-.4)
.model DS D(Is=1u Rs=40m Cjo=180p N=1)
.tran 0 60u 40u 1n
.meas TRAN sw_min MIN V(sw)
.meas TRAN sw_max MAX V(sw)
.end
"""%lp
    f=os.path.join(OUT,"buck_%s.cir"%lp); open(f,"w").write(n)
    subprocess.run([LT,"-b",f],timeout=120,creationflags=0x08000000)
    t=open(f[:-4]+".log","rb").read().replace(b"\0",b"").decode("utf8","ignore")
    print(lp,re.findall(r"(sw_m\w+):.*?=([-\d.e+]+)",t))

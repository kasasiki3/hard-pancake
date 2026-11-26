"""固いパンケーキ: KiCad回路図ジェネレータ。

部品・接続(ネット)・配置をここに書き、シート内の接続は自動配線(迷路法)で線を引いた
.kicad_sch 一式を kicad/ に出力する。ネットラベルは使わない。シートをまたぐ信号だけ
階層ラベルにし、ルートシートでシートピン同士を線でつなぐ。電源は電源シンボル。

実行: python tools/gen_sch.py
"""
import heapq
import math
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexp import Sym, dump, find, first, parse  # noqa: E402

KILIB = "C:/Program Files/KiCad/10.0/share/kicad/symbols/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kicad")
PROJECT = "pancake"
POWER_NETS = {"GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V",
              "+12V": "power:+12V", "VBUS": "power:VBUS",
              "GND_ISO": "pancake:GND_ISO"}
NC = None
GRID = 2.54
G = 1.27          # routing grid


def uid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- symbols
_libcache = {}


def libsym(lib_id):
    """Return a flattened lib symbol (list) named lib_id."""
    lib, name = lib_id.split(":")
    if lib == "pancake":
        return CUSTOM[name](lib_id)
    if lib not in _libcache:
        tree = parse(open(KILIB + lib + ".kicad_sym", encoding="utf-8").read())[0]
        _libcache[lib] = {s[1]: s for s in find(tree, "symbol")}
    syms = _libcache[lib]
    der = syms[name]
    ext = first(der, "extends")
    base = syms[ext[1]] if ext else der
    out = [Sym("symbol"), lib_id]
    props = {p[1]: p for p in find(base, "property")}
    for p in find(der, "property"):
        props[p[1]] = p
    for item in base[2:]:
        if not isinstance(item, list):
            continue
        if item[0] in ("property", "symbol", "extends", "embedded_fonts"):
            continue
        out.append(item)
    out.extend(props.values())
    for sub in find(base, "symbol"):
        sub = list(sub)
        sub[1] = name + sub[1][len(base[1]):]
        out.append(sub)
    if lib_id == "Interface_USB:CH340C":
        # V3 is tied to VCC in 3.3V mode (datasheet); mark it power input so ERC
        # does not see two power outputs on +3V3.
        for sub in find(out, "symbol"):
            for p in find(sub, "pin"):
                if first(p, "number")[1] == "4":
                    p[1] = Sym("power_in")
    return out


def pins_of(sym):
    """[(number, name, type, x, y, angle)] in symbol coordinates."""
    res = []
    for sub in find(sym, "symbol"):
        for p in find(sub, "pin"):
            at = first(p, "at")
            res.append((first(p, "number")[1], first(p, "name")[1], str(p[1]),
                        float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0))
    return res


def graphics_pts(sym):
    """Outline points of the symbol body (symbol coordinates)."""
    pts = []
    for sub in find(sym, "symbol"):
        for g in sub:
            if not isinstance(g, list):
                continue
            k = g[0]
            if k == "rectangle":
                for kk in ("start", "end"):
                    p = first(g, kk)
                    pts.append((float(p[1]), float(p[2])))
            elif k in ("polyline", "bezier"):
                for xy in find(first(g, "pts"), "xy"):
                    pts.append((float(xy[1]), float(xy[2])))
            elif k == "circle":
                c, r = first(g, "center"), float(first(g, "radius")[1])
                pts += [(float(c[1]) - r, float(c[2]) - r), (float(c[1]) + r, float(c[2]) + r)]
            elif k == "arc":
                for kk in ("start", "mid", "end"):
                    p = first(g, kk)
                    pts.append((float(p[1]), float(p[2])))
    return pts


def _font():
    return [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]


def _prop(name, value, x, y, hide=False):
    eff = _font()
    if hide:
        eff.append([Sym("hide"), Sym("yes")])
    return [Sym("property"), name, value, [Sym("at"), x, y, 0], eff]


def make_ic(name, ref, left, right, width=15.24):
    """Box symbol. left/right: [(num, name, type)] top to bottom; None = gap."""
    n = max(len(left), len(right))
    h = (n + 1) * GRID
    top = math.ceil(h / 2 / GRID) * GRID

    def build(lib_id):
        body = [Sym("symbol"), name + "_0_1",
                [Sym("rectangle"), [Sym("start"), -width / 2, top],
                 [Sym("end"), width / 2, top - h - GRID],
                 [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]],
                 [Sym("fill"), [Sym("type"), Sym("background")]]]]
        pins = [Sym("symbol"), name + "_1_1"]
        for side, lst in ((0, left), (1, right)):
            for i, p in enumerate(lst):
                if p is None:
                    continue
                num, pname, ptype = p
                y = top - GRID * (i + 1)
                x = -width / 2 - 5.08 if side == 0 else width / 2 + 5.08
                ang = 0 if side == 0 else 180
                pins.append([Sym("pin"), Sym(ptype), Sym("line"), [Sym("at"), x, y, ang],
                             [Sym("length"), 5.08],
                             [Sym("name"), pname, _font()],
                             [Sym("number"), num, _font()]])
        return [Sym("symbol"), lib_id,
                [Sym("pin_names"), [Sym("offset"), 1.016]],
                [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")],
                [Sym("on_board"), Sym("yes")],
                _prop("Reference", ref, 0, top + 2.54),
                _prop("Value", name, 0, top - h - 5.08),
                _prop("Footprint", "", 0, 0, True),
                _prop("Datasheet", "", 0, 0, True),
                _prop("Description", "", 0, 0, True),
                body, pins]
    return build


# 絶縁側GNDの電源シンボル (標準のGND2を土台に名前だけ替える)
def make_gnd_iso(lib_id):
    src = libsym("power:GND2")
    src[1] = lib_id
    for p in find(src, "property"):
        if p[1] == "Value":
            p[2] = "GND_ISO"
        elif p[1] == "Description":
            p[2] = "CANの絶縁側GND"
    for sub in find(src, "symbol"):
        sub[1] = sub[1].replace("GND2", "GND_ISO", 1)
    return src


CUSTOM = {
    "DRV8323RH": make_ic("DRV8323RH", "U", [
        ("37", "INHA", "input"),
        ("38", "INLA", "input"),
        ("39", "INHB", "input"),
        ("40", "INLB", "input"),
        ("41", "INHC", "input"),
        ("42", "INLC", "input"),
        None,
        ("33", "ENABLE", "input"),
        ("34", "CAL", "input"),
        ("28", "nFAULT", "open_collector"),
        None,
        ("25", "SOA", "output"),
        None,
        None,
        ("24", "SOB", "output"),
        None,
        None,
        ("23", "SOC", "output"),
        None,
        ("29", "MODE", "input"),
        ("30", "IDRIVE", "input"),
        ("31", "VDS", "input"),
        ("32", "GAIN", "input"),
        ("36", "DVDD", "power_out"),
        None,
        ("26", "VREF", "power_in"),
        None,
        ("35", "AGND", "power_in"),
        ("27", "DGND", "power_in"),
        ("2", "PGND", "power_in"),
        ("43", "BGND", "power_in"),
        ("49", "PAD", "passive"),
        ("46", "NC", "no_connect")], [
        ("6", "VM", "power_in"),
        ("7", "VDRAIN", "input"),
        None,
        ("5", "VCP", "passive"),
        ("4", "CPH", "passive"),
        ("3", "CPL", "passive"),
        None,
        ("8", "GHA", "output"),
        ("9", "SHA", "passive"),
        ("10", "GLA", "output"),
        ("11", "SPA", "passive"),
        ("12", "SNA", "passive"),
        None,
        ("17", "GHB", "output"),
        ("16", "SHB", "passive"),
        ("15", "GLB", "output"),
        ("14", "SPB", "passive"),
        ("13", "SNB", "passive"),
        None,
        ("18", "GHC", "output"),
        ("19", "SHC", "passive"),
        ("20", "GLC", "output"),
        ("21", "SPC", "passive"),
        ("22", "SNC", "passive"),
        None,
        ("47", "VIN", "power_in"),
        ("48", "nSHDN", "input"),
        None,
        ("45", "SW", "output"),
        ("44", "CB", "passive"),
        None,
        ("1", "FB", "input")], 25.4),
    "RT9013-33": make_ic("RT9013-33", "U", [
        ("1", "VIN", "power_in"), ("3", "EN", "input"), ("2", "GND", "power_in")], [
        ("5", "VOUT", "power_out"), ("4", "NC", "no_connect")]),
    "CA-IS2062A": make_ic("CA-IS2062A", "U", [
        ("1", "RXD", "output"), ("4", "TXD", "input"), None,
        ("6", "VDDP", "power_in"), None, ("7", "VDDL", "power_in"), None,
        ("5", "GNDP1", "power_in"), ("8", "GND1", "power_in"),
        ("2", "NC", "no_connect"), ("3", "NC", "no_connect")], [
        ("15", "CANH", "bidirectional"), ("14", "CANL", "bidirectional"), None,
        ("11", "VISOOUT", "power_out"), ("10", "VISOIN", "power_in"), None, None,
        ("12", "GNDP2", "power_in"), ("9", "GND2", "power_in"),
        ("16", "NC", "no_connect"), ("13", "NC", "no_connect")], 25.4),
    "GND_ISO": make_gnd_iso,
}

# ---------------------------------------------------------------- design
FP = {
    "R0402": "Resistor_SMD:R_0402_1005Metric", "R0603": "Resistor_SMD:R_0603_1608Metric",
    "R2512": "Resistor_SMD:R_2512_6332Metric",
    "C0402": "Capacitor_SMD:C_0402_1005Metric", "C0603": "Capacitor_SMD:C_0603_1608Metric",
    "C0805": "Capacitor_SMD:C_0805_2012Metric", "C1206": "Capacitor_SMD:C_1206_3216Metric",
    "C1210": "Capacitor_SMD:C_1210_3225Metric", "CP10": "Capacitor_SMD:CP_Elec_10x10.5",
    "SMB": "Diode_SMD:D_SMB", "SMA": "Diode_SMD:D_SMA", "LED0603": "LED_SMD:LED_0603_1608Metric",
    "SOT23": "Package_TO_SOT_SMD:SOT-23", "SOT23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT23-6": "Package_TO_SOT_SMD:SOT-23-6", "SOIC8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "XTAL3225": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
}

# JLCの部品番号 (Basic または Preferred Extended)。照合で別の部品に置き換わらないように回路図へ入れる
LCSC = {
    ("1uF 50V", "C_0603_1608"): "C15849", ("4.7uF 16V", "C_0603_1608"): "C19666",
    ("100nF 100V", "C_0805_2012"): "C28233", ("47nF 50V", "C_0603_1608"): "C1622",
    ("10uF 50V", "C_1206_3216"): "C13585", ("22uF 25V", "C_1206_3216"): "C12891",
    ("10uF 25V", "C_0805_2012"): "C15850", ("100nF", "C_0402_1005"): "C307331",
    ("100nF 50V", "C_0402_1005"): "C307331", ("10nF", "C_0402_1005"): "C15195",
    ("1nF", "C_0402_1005"): "C1523", ("4.7nF", "C_0402_1005"): "C1538",
    ("15pF", "C_0402_1005"): "C1548", ("120", "R_0402_1005"): "C25079",
    ("100", "R_0402_1005"): "C25076", ("1k", "R_0402_1005"): "C11702",
    ("5.6k", "R_0402_1005"): "C25908", ("10k", "R_0402_1005"): "C25744",
    ("18k", "R_0402_1005"): "C25762", ("100k", "R_0402_1005"): "C25741",
    ("LED", "LED_0603_1608"): "C2286", ("TS-1187A-B-A-B", None): "C318884",
}

PAGES = {}    # page -> list of comps
PORTS = {}    # page -> list of (net, x, y, side, shape)
FLAGS = {}    # page -> list of (net, x, y)
TIES = {}     # page -> list of (net~tag, x, y, block)
_counts = {}
CUR_BLOCK = ["?"]


def block(name):
    CUR_BLOCK[0] = name


def comp(page, prefix, lib_id, value, nets, at, rot=0, fp=None, mpn=None, in_bom=True,
         txt=None, mirror=False, dnp=False):
    """at: (x, y) mm. y may be a net name: align with that net's pin already placed."""
    _counts[prefix] = _counts.get(prefix, 0) + 1
    ref = "%s%d" % (prefix, _counts[prefix])
    PAGES.setdefault(page, []).append(dict(ref=ref, lib=lib_id, value=value, nets=nets,
                                           fp=FP.get(fp, fp), mpn=mpn, in_bom=in_bom,
                                           rot=rot, at=at, txt=txt, mirror=mirror, dnp=dnp,
                                           block=CUR_BLOCK[0]))
    return ref


def R(page, value, a, b, at, rot=0, fp="R0402", txt=None):
    """rot 0: pin1(a) top / 90: pin1 left / 180: pin1 bottom / 270: pin1 right."""
    return comp(page, "R", "Device:R", value, {"1": a, "2": b}, at, rot, fp, txt=txt)


def C(page, value, a, b, at, rot=0, fp="C0402", txt=None):
    return comp(page, "C", "Device:C", value, {"1": a, "2": b}, at, rot, fp, txt=txt)


def port(page, net, at, side, shape="passive"):
    """Hierarchical label. side 'L': text extends left, wire from the right."""
    PORTS.setdefault(page, []).append((net, at[0], at[1], side, shape))


def flag(page, net, at):
    FLAGS.setdefault(page, []).append((net, at[0], at[1], CUR_BLOCK[0]))


def tie(page, key, at):
    """Power symbol for a locally wired power net 'NET~tag'.
    Pins on 'NET~tag' are joined by drawn wires; this symbol ties them to NET."""
    TIES.setdefault(page, []).append((key, at[0], at[1], CUR_BLOCK[0]))


# ======== 電源シート
P = "power"
block("電源入力・保護")
comp(P, "J", "Connector_Generic:Conn_01x02", "XT60PW-M", {"1": "VBUS", "2": "GND"},
     (35, 60), 180, txt="left", fp="pancake:XT60PW-M_1plus_2minus")
comp(P, "D", "Device:D_TVS", "SMBJ30A", {"1": "VBUS", "2": "GND"}, (55, 60), 270, "SMB")
for i in range(3):
    comp(P, "C", "Device:C_Polarized", "100uF 63V", {"1": "VBUS", "2": "GND"}, (72 + 17 * i, 60),
         0, "CP10", "118EC447")
flag(P, "VBUS", (40, 85))
flag(P, "GND", (60, 85))

flag(P, "+5V", (85, 85))

block("3.3V LDO (RT9013)")
comp(P, "U", "pancake:RT9013-33", "RT9013-33GB",
     {"1": "VIN_LDO", "3": "VIN_LDO", "2": "GND", "5": "+3V3", "4": NC}, (190, 122),
     fp="SOT23-5")
C(P, "1uF 50V", "VIN_LDO", "GND", (165, 127), fp="C0603")
comp(P, "#FLG", "power:PWR_FLAG", "PWR_FLAG", {"1": "VIN_LDO"}, (180, 112), in_bom=False)
# 5V(降圧) と ST-Link(SWD)の5V をダイオードORしてLDOへ。ST-Linkだけでも MCU・エンコーダが動く
comp(P, "D", "Diode:BAT54C", "BAT54C", {"1": "+5V", "2": "SWD_5V", "3": "VIN_LDO"},
     (163, 105), 0, "SOT23", txt="above")
C(P, "1uF 50V", "+3V3", "GND", (215, 127), fp="C0603")

block("VBUS電圧検出 (約62Vフルスケール)")
R(P, "100k", "VBUS", "VBUS_SENSE", (260, 63))
R(P, "5.6k", "VBUS_SENSE", "GND", (260, 82))
C(P, "1nF", "VBUS_SENSE", "GND", (272, 82))
port(P, "VBUS_SENSE", (290, 73.66), "R", "output")

port(P, "SWD_5V", (140, None), "L", "input")

# ======== パワー段シート
B = "bridge"
block("ゲートドライバ・5V降圧 (DRV8323RH)")
drv = {"37": "PWM_AH", "38": "PWM_AL", "39": "PWM_BH", "40": "PWM_BL", "41": "PWM_CH",
       "42": "PWM_CL", "33": "DRV_EN", "34": "DRV_CAL", "28": "DRV_NFAULT",
       "25": "SOA", "24": "SOB", "23": "SOC",
       "29": "GND", "30": "IDRIVE", "31": "VDS_SET", "32": "DVDD", "36": "DVDD",
       "26": "+3V3", "35": "GND", "27": "GND", "2": "GND", "43": "GND", "49": "GND", "46": NC,
       "6": "VBUS", "7": "VDRAIN", "5": "VCP", "4": "CPH", "3": "CPL",
       "47": "VBUS", "48": NC, "45": "SW_5V", "44": "CB_5V", "1": "FB_5V"}
for ph, (gh, sh, gl, sp, sn) in zip("ABC", [("8", "9", "10", "11", "12"),
                                           ("17", "16", "15", "14", "13"),
                                           ("18", "19", "20", "21", "22")]):
    drv.update({gh: "GATE_%sH" % ph, sh: "PHASE_" + ph, gl: "GATE_%sL" % ph,
                sp: "SP_" + ph, sn: "SN_" + ph})
comp(B, "U", "pancake:DRV8323RH", "DRV8323RHRGZR", drv, (125, 105),
     fp="Package_DFN_QFN:Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm_ThermalVias")
for net in ("PWM_AH", "PWM_AL", "PWM_BH", "PWM_BL", "PWM_CH", "PWM_CL", "DRV_EN", "DRV_CAL"):
    port(B, net, (40, None), "L", "input")
port(B, "DRV_NFAULT", (40, None), "L", "output")
R(B, "10k", "+3V3", "DRV_NFAULT", (22, 110))
# SOx = 1.65V - 20mV/A (GAIN=40、0.5mΩ)
for k, ph in enumerate("ABC"):
    R(B, "100", "SO" + ph, "ISENSE_" + ph, (75, "SO" + ph), 270)
    C(B, "1nF", "ISENSE_" + ph, "GND", (24 + 14 * k, 168))
    port(B, "ISENSE_" + ph, (40, "SO" + ph), "L", "output")
# IDRIVE: 18k=30/60mA、75k=60/120mA。VDS: 18k=0.13V、75k=0.26V
R(B, "18k", "IDRIVE", "GND", (72, 168))
R(B, "18k", "VDS_SET", "GND", (84, 168))
C(B, "1uF 50V", "DVDD", "GND", (98, 168), fp="C0603")
C(B, "100nF", "+3V3", "GND", (114, 172))
C(B, "100nF 100V", "VBUS", "GND", (128, 172), fp="C0805")
C(B, "10uF 50V", "VBUS", "GND", (146, 172), fp="C1206")
C(B, "2.2uF 100V", "VBUS", "GND", (163, 172), fp="C1210")
C(B, "1uF 50V", "VCP", "VBUS", (165, 45), fp="C0603")
C(B, "47nF 50V", "CPH", "CPL", (182, 52), fp="C0603")
C(B, "100nF 50V", "CB_5V", "SW_5V", (112, 200), 90)
comp(B, "D", "Device:D_Schottky", "SS16", {"1": "SW_5V", "2": "GND"}, (125, 222), 270, "SMA")
comp(B, "L", "Device:L", "22uH", {"1": "SW_5V", "2": "+5V"}, (150, 212), 90,
     "Inductor_SMD:L_Sunlord_SWPA6045S", "SWPA6045S220MT")
# 0.765V x (1 + 100k/18k) = 5.02V
R(B, "100k", "+5V", "FB_5V", (172, 225))
R(B, "18k", "FB_5V", "GND", (172, 242))
C(B, "22uF 25V", "+5V", "GND", (190, 225), fp="C1206")
for k, ph in enumerate("ABC"):
    block("%s相 ハーフブリッジ" % ph)
    ox, oy = 225, 44 + 86 * k
    comp(B, "Q", "Transistor_FET:NTMFS016N06CT1G", "NTMFS5C628NLT1G",
         {"4": "GATE_%sH" % ph, "5": "VBUS~" + ph, "1": "PHASE_" + ph, "2": "PHASE_" + ph,
          "3": "PHASE_" + ph}, (ox + 38, oy - 10), txt="right")
    comp(B, "Q", "Transistor_FET:NTMFS016N06CT1G", "NTMFS5C628NLT1G",
         {"4": "GATE_%sL" % ph, "5": "PHASE_" + ph, "1": "SHUNT_" + ph, "2": "SHUNT_" + ph,
          "3": "SHUNT_" + ph}, (ox + 38, oy + 15), txt="right")
    comp(B, "R", "Device:R", "0.5m", {"1": "SHUNT_" + ph, "2": "GND~" + ph}, (ox + 40.54, oy + 35),
         0, "R2512", "RLM25FEGMR50M")
    comp(B, "J", "Connector_Generic:Conn_01x01", "モーター%s" % ph,
         {"1": "PHASE_" + ph}, (ox + 80, oy + 2), txt="right",
         fp="pancake:MotorPad_6x6_moteus")
    # 入力コンデンサは上FETドレイン〜シャントのGND端の間に置く (スイッチングループを最小に)
    C(B, "100nF 100V", "VBUS~" + ph, "GND~" + ph, (ox + 60, oy - 17), fp="C0805")
    C(B, "2.2uF 100V", "VBUS~" + ph, "GND~" + ph, (ox + 78, oy - 17), fp="C1210")
    # スナバは未実装パッド。試作で跳ねを見て実装する (下FETの直近に置く)
    comp(B, "R", "Device:R", "2.2", {"1": "PHASE_" + ph, "2": "SNUB_" + ph}, (ox + 112, oy + 12),
         0, "Resistor_SMD:R_1206_3216Metric", in_bom=False, dnp=True)
    comp(B, "C", "Device:C", "2.2nF 100V", {"1": "SNUB_" + ph, "2": "GND"}, (ox + 112, oy + 28),
         0, "C0603", in_bom=False, dnp=True)
    tie(B, "VBUS~" + ph, (ox + 92, oy - 24))
    tie(B, "GND~" + ph, (ox + 40.54, oy + 42))
block("FET温度検出 (NTCはFET近傍に配置)")
R(B, "10k", "+3V3", "NTC_SENSE", (365, 60))
comp(B, "TH", "Device:Thermistor_NTC", "10k NTC", {"1": "NTC_SENSE", "2": "GND"}, (365, 77),
     0, "R0603", "NCP18XH103F03RB")
port(B, "NTC_SENSE", (385, 68.58), "R", "output")

# ======== 制御シート (MCU・CAN・エンコーダ)
M = "ctrl"
block("MCU")
mcu = {"1": "+3V3", "2": NC, "3": NC, "4": NC, "5": "OSC_IN", "6": "OSC_OUT",
       "7": "NRST", "8": "VBUS_SENSE", "9": "ISENSE_A", "10": NC, "11": NC,
       "12": "ENC2_B", "13": "ENC2_Z", "14": "ENC2_A", "15": "ISENSE_B", "16": "ISENSE_C",
       "17": "DRV_CAL", "18": "DRV_EN", "19": "GND", "20": "+3V3", "21": "+3V3", "22": "LED1", "23": "GND",
       "24": "+3V3", "25": "NTC_SENSE", "26": "DRV_NFAULT", "27": "PWM_AL", "28": "PWM_BL",
       "29": "PWM_CL", "30": "PWM_AH", "31": "PWM_BH", "32": "PWM_CH", "33": "CAN_RX",
       "34": "CAN_TX", "35": "GND", "36": "+3V3", "37": "SWDIO", "38": "SWCLK", "39": NC,
       "40": "ENC1_B", "41": "ENC1_A", "42": "ENC1_Z", "43": "ENC1_A", "44": "ENC1_B",
       "45": "BOOT0", "46": "LED2", "47": "GND", "48": "+3V3"}
comp(M, "U", "MCU_ST_STM32G4:STM32G431CBTx", "STM32G431CBT6", mcu, (210, 140))
for net in ("ISENSE_C", "NTC_SENSE", "PWM_AL", "PWM_BL", "PWM_CL", "DRV_CAL", "DRV_EN",
            "DRV_NFAULT"):
    port(M, net, (180, None), "L",
         "input" if net.startswith(("ISENSE", "NTC", "DRV_N")) else "output")
for net in ("VBUS_SENSE", "ISENSE_A", "ISENSE_B", "PWM_AH", "PWM_BH", "PWM_CH"):
    port(M, net, (242, None), "R", "input" if net.startswith(("ISENSE", "VBUS")) else "output")
R(M, "10k", "GND", "BOOT0", (183, "BOOT0"), 90)

block("パスコン (VDD×3, VDDA, VREF+)")
for i, (v, fp) in enumerate([("100nF", None), ("100nF", None), ("100nF", None),
                             ("4.7uF 16V", "C0603"), ("100nF", None), ("1uF 50V", "C0603"),
                             ("100nF", None)]):
    C(M, v, "+3V3", "GND", (172 + 14 * i, 72), fp=fp or "C0402")

block("クロック")
comp(M, "Y", "Device:Crystal_GND24", "8MHz", {"1": "OSC_IN", "3": "OSC_OUT", "2": "GND",
                                              "4": "GND"}, (158, 98), 0, "XTAL3225",
     "TX32258M4FBDD2T")
C(M, "15pF", "OSC_IN", "GND", (146, 108))
C(M, "15pF", "OSC_OUT", "GND", (170, 108))

block("LED")
R(M, "1k", "LED2", "LED2_A", (130, "LED2"), 270)
comp(M, "D", "Device:LED", "LED", {"2": "LED2_A", "1": "GND"}, (118, "LED2"), 0, "LED0603",
     txt="above")
R(M, "1k", "LED1", "LED1_A", (157, "LED1"), 270, txt="below")
comp(M, "D", "Device:LED", "LED", {"2": "LED1_A", "1": "GND"}, (144, "LED1"), 0, "LED0603", txt="below")

block("エンコーダ1 (ABZ または SSI: A=DO, B=CLK, Z=CSN)")
# A/B は TIM4(PB6/PB7) と SPI3(PB4 MISO / PB3 SCK) の両方へ配線し、ファームでどちらかを使う
e1 = ["ENC1_Z", "ENC1_B", "ENC1_A"]
for i, s_ in enumerate(e1):
    R(M, "100", s_, s_ + "_C", (135, 127 + 7.62 * i), 270)
comp(M, "U", "Power_Protection:USBLC6-4SC6", "USBLC6-4SC6",
     {"5": "+3V3", "2": "GND", "1": "ENC1_A_C", "3": "ENC1_B_C", "4": "ENC1_Z_C", "6": NC},
     (95, 112), 90, None, "TPUSBLC6-4SC6", txt="right")
comp(M, "J", "Connector_Generic:Conn_01x05", "エンコーダ1",
     {"1": "+3V3", "2": "GND", "3": "ENC1_A_C", "4": "ENC1_B_C", "5": "ENC1_Z_C"},
     (40, 140), 180, txt="left", fp="Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical")

block("エンコーダ2 (ABZ)")
e2 = ["ENC2_B", "ENC2_Z", "ENC2_A"]
for i, s in enumerate(e2):
    R(M, "100", s, s + "_C", (295, 114.3 + 5.08 * i), 90)
comp(M, "U", "Power_Protection:USBLC6-4SC6", "USBLC6-4SC6",
     {"5": "+3V3", "2": "GND", "1": "ENC2_B_C", "3": "ENC2_Z_C", "4": "ENC2_A_C", "6": NC},
     (335, 97), 90, None, "TPUSBLC6-4SC6", txt="right")
comp(M, "J", "Connector_Generic:Conn_01x05", "エンコーダ2",
     {"1": "+3V3", "2": "GND", "3": "ENC2_A_C", "4": "ENC2_B_C", "5": "ENC2_Z_C"},
     (380, 119.38), 0, txt="right",
     fp="Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical")

block("SWD (ST-Link V2互換品、5Vで給電も受ける)")
comp(M, "J", "Connector_Generic:Conn_01x05", "SWD",
     {"1": "SWD_5V", "2": "SWDIO", "3": "SWCLK", "4": "NRST", "5": "GND"}, (252, 162), 0,
     "Connector_JST:JST_PH_B5B-PH-K_1x05_P2.00mm_Vertical", "B5B-PH-K-S", txt="right")
port(M, "SWD_5V", (275, None), "R", "output")
C(M, "100nF", "NRST", "GND", (240, 182))
comp(M, "SW", "Switch:SW_Push", "RESET", {"1": "NRST", "2": "GND"}, (230, 182), 270,
     "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "TS-1187A-B-A-B")

block("絶縁CANトランシーバ (右側はGND_ISOの島)")
comp(M, "U", "pancake:CA-IS2062A", "CA-IS2062A",
     {"1": "CAN_RX", "4": "CAN_TX", "5": "GND", "6": "+5V", "7": "+3V3", "8": "GND",
      "15": "CANH", "14": "CANL", "12": "GND_ISO", "11": "VISO", "10": "VISO",
      "9": "GND_ISO"}, (266, 227), fp="pancake:CA-IS2062A_LGA-16_4.65x5.2mm_P0.65mm")
# 同じ面で電源ピンから2mm以内に置く
C(M, "10uF 25V", "+5V", "GND", (210, 264), fp="C0805")
C(M, "100nF", "+5V", "GND", (226, 264))
C(M, "1uF 50V", "+3V3", "GND", (240, 264), fp="C0603")
C(M, "10uF 25V", "VISO", "GND_ISO", (255, 264), fp="C0805")
C(M, "100nF", "VISO", "GND_ISO", (269, 264))
C(M, "1uF 50V", "VISO", "GND_ISO", (281, 264), fp="C0603")
flag(M, "GND_ISO", (222, 224))

block("CAN保護・スプリット終端・RJ45×2 (数珠つなぎ)")
comp(M, "D", "Power_Protection:NUP2105L", "ESDCAN24-2BLY",
     {"1": "CANH", "2": "CANL", "3": "GND_ISO"}, (328, 200), 0, "SOT23", txt="left")
comp(M, "JP", "Jumper:SolderJumper_2_Open", "終端ON", {"1": "CANH", "2": "CANH_T"},
     (346, 202), 270,
     "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", in_bom=False)
comp(M, "JP", "Jumper:SolderJumper_2_Open", "終端ON", {"1": "CANL_T", "2": "CANL"},
     (346, 245), 270,
     "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", in_bom=False)
# 60Ω = 120Ω×2並列 (60.4ΩはJLCのBasicに無い)
for x in (346, 356):
    R(M, "120", "CANH_T", "CAN_SPLIT", (x, 215))
    R(M, "120", "CAN_SPLIT", "CANL_T", (x, 232))
C(M, "4.7nF", "CAN_SPLIT", "GND_ISO", (338, 223.5), 270)
# ピン配置は桔梗の雛形に合わせる: 1-2 CAN1、3-6 CAN2、4-5 12V(素通し)、7-8 GND。
# 7-8 GNDと素通しの12Vは絶縁側だけで完結させる (基板のGNDとつながない)。
# CAN1が既定 (JPの1-2が銅箔でつながっている)。CAN2を使うときは切って2-3をはんだ付けする。
for k, w in enumerate("HL"):
    comp(M, "JP", "Jumper:SolderJumper_3_Bridged12", "CAN1/CAN2",
         {"1": "CAN1" + w, "2": "CAN" + w, "3": "CAN2" + w}, (371, 211 + 22 * k), 0,
         "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm", in_bom=False, txt="above")
for i in range(2):
    comp(M, "J", "Connector:RJ45", "RJ45", {"1": "CAN1H", "2": "CAN1L", "3": "CAN2H",
                                            "6": "CAN2L", "4": "CAN_12V", "5": "CAN_12V",
                                            "7": "GND_ISO", "8": "GND_ISO"},
         (397, 195 + 42 * i), 180, "pancake:RJ45_R-RJ45R08P-A004", "R-RJ45R08P-A004",
         txt="above")

# ======== 測定用・調整用の追加 (既存の部品番号をずらさないよう最後に置く)


def nettie(page, a, b, at, rot=0):
    comp(page, "NT", "Device:NetTie_2", "NetTie", {"1": a, "2": b}, at, rot,
         "NetTie:NetTie-2_SMD_Pad0.5mm", in_bom=False, txt="above")


def tp(page, name, net, at):
    comp(page, "TP", "Connector:TestPoint", name, {"1": net}, at, 0,
         "TestPoint:TestPoint_Pad_D1.0mm", in_bom=False, txt="above")


for k, ph in enumerate("ABC"):
    block("%s相 ハーフブリッジ" % ph)
    ox, oy = 225, 44 + 86 * k
    # 検出線はシャントのパッドから引く (ネットタイはシャントの直近に置く)
    nettie(B, "SP_" + ph, "SHUNT_" + ph, (ox + 18, oy + 27))
    nettie(B, "SN_" + ph, "GND~" + ph, (ox + 18, oy + 37))
    # 上FETドレイン〜下FETソースの未実装パッド (シャントを通らない経路)
    comp(B, "C", "Device:C", "1uF 100V", {"1": "VBUS~" + ph, "2": "SHUNT_" + ph},
         (ox + 75, oy + 24), 0, "C1206", in_bom=False, dnp=True)
    tp(B, "GH" + ph, "GATE_%sH" % ph, (ox + 18, oy - 14))
    tp(B, "GL" + ph, "GATE_%sL" % ph, (ox + 18, oy + 10))
    tp(B, "SH" + ph, "PHASE_" + ph, (ox + 97, oy - 4))
block("ゲートドライバ・5V降圧 (DRV8323RH)")
nettie(B, "VDRAIN", "VBUS", (165, 66))
for k, ph in enumerate("ABC"):
    tp(B, "SO" + ph, "SO" + ph, (88, 92 + 7.62 * k))
tp(B, "VCP", "VCP", (198, 46))
tp(B, "DVDD", "DVDD", (92, 150))
tp(B, "nFAULT", "DRV_NFAULT", (30, 150))
block("テストポイント (電源)")
for k, net in enumerate(("VBUS", "+5V", "+3V3", "GND", "GND")):
    tp(P, net, net, (262 + 16 * k, 125))

SHEETS = [("power", "電源"), ("bridge", "パワー段"), ("ctrl", "制御 (MCU・CAN・エンコーダ)")]
PAPER = {"power": ("A3", 420, 297), "bridge": ("A3", 420, 297), "ctrl": ("A3", 420, 297)}

# ---------------------------------------------------------------- geometry helpers


def snap(v):
    return round(v / GRID) * GRID


def cell(x, y):
    return (round(x / G), round(y / G))


def outward(angle):
    a = math.radians(angle + 180)
    return round(math.cos(a)), -round(math.sin(a))


def xform(px, py, rot):
    r = math.radians(rot)
    rx = px * math.cos(r) - py * math.sin(r)
    ry = px * math.sin(r) + py * math.cos(r)
    return round(rx, 4), round(-ry, 4)


def place_pins(pins, rot):
    out = []
    for num, name, typ, px, py, ang in pins:
        sx, sy = xform(px, py, rot)
        out.append((num, name, typ, sx, sy, (ang + rot) % 360))
    return out


def text_w(s, size=1.27):
    return sum(size * (1.0 if ord(ch) > 0x2000 else 0.75) for ch in str(s))


# ---------------------------------------------------------------- router
class Router:
    BEND, CROSS, NEAR = 6, 8, 2

    def __init__(self, w, h):
        self.W, self.H = int(w / G), int(h / G)
        self.hard = set()
        self.soft = {}
        self.pins = {}        # cell -> (net, outward(dx,dy))
        self.occ = {}         # cell -> {net: set('H','V')}
        self.edges = {}       # net -> set of (cellA, cellB)

    def block_rect(self, x1, y1, x2, y2, soft=None):
        c1, c2 = cell(min(x1, x2), min(y1, y2)), cell(max(x1, x2), max(y1, y2))
        for i in range(c1[0], c2[0] + 1):
            for j in range(c1[1], c2[1] + 1):
                if soft is None:
                    self.hard.add((i, j))
                else:
                    self.soft[(i, j)] = max(self.soft.get((i, j), 0), soft)

    def add_pin(self, net, x, y, d):
        c = cell(x, y)
        self.pins[c] = (net, d)
        self.hard.discard(c)
        self.hard.discard((c[0] + d[0], c[1] + d[1]))

    def _ok(self, net, c, d, targets, untreed):
        i, j = c
        if not (2 <= i < self.W - 2 and 2 <= j < self.H - 2):
            return None
        others = {n: v for n, v in self.occ.get(c, {}).items() if n != net}
        if c in targets:
            if others:
                return None
            pd = self.pins.get(c)
            if pd and (d[0], d[1]) != (-pd[1][0], -pd[1][1]):
                return None
            return "end"
        if c in self.pins or c in self.hard or c in untreed:
            return None
        if others:
            perp = "V" if d[1] == 0 else "H"
            if len(others) == 1 and list(others.values())[0] == {perp}:
                return "cross"
            return None
        return "free"

    def route(self, net, src, sdir, targets, untreed):
        tx0 = min(t[0] for t in targets)
        tx1 = max(t[0] for t in targets)
        ty0 = min(t[1] for t in targets)
        ty1 = max(t[1] for t in targets)

        def h(c):
            return max(tx0 - c[0], 0, c[0] - tx1) + max(ty0 - c[1], 0, c[1] - ty1)

        first_c = (src[0] + sdir[0], src[1] + sdir[1])
        kind = self._ok(net, first_c, sdir, targets, untreed)
        if kind is None:
            return None
        start = (first_c, sdir)
        prev = {start: None}
        g = {start: 1}
        heap = [(1 + h(first_c), 1, first_c, sdir, kind)]
        while heap:
            f, gc, c, d, kind = heapq.heappop(heap)
            if g.get((c, d), 1e9) < gc:
                continue
            if kind == "end":
                path = []
                st = (c, d)
                while st:
                    path.append(st[0])
                    st = prev[st]
                path.append(src)
                return path[::-1]
            dirs = [d] if kind == "cross" else [(1, 0), (-1, 0), (0, 1), (0, -1)]
            for nd in dirs:
                if nd == (-d[0], -d[1]):
                    continue
                n = (c[0] + nd[0], c[1] + nd[1])
                k2 = self._ok(net, n, nd, targets, untreed)
                if k2 is None:
                    continue
                cost = 1 + self.soft.get(n, 0)
                if nd != d:
                    cost += self.BEND
                if k2 == "cross":
                    cost += self.CROSS
                for side in ((nd[1], nd[0]), (-nd[1], -nd[0])):
                    o = self.occ.get((n[0] + side[0], n[1] + side[1]))
                    if o and any(k != net for k in o):
                        cost += self.NEAR
                ng = gc + cost
                if ng < g.get((n, nd), 1e9):
                    g[(n, nd)] = ng
                    prev[(n, nd)] = (c, d)
                    heapq.heappush(heap, (ng + h(n), ng, n, nd, k2))
        return None

    def commit(self, net, path):
        es = self.edges.setdefault(net, set())
        for a, b in zip(path, path[1:]):
            dd = "H" if a[1] == b[1] else "V"
            for c in (a, b):
                self.occ.setdefault(c, {}).setdefault(net, set()).add(dd)
            es.add((min(a, b), max(a, b)))

    def route_net(self, net, terms):
        """terms: [(cell, outward)]. Returns False on failure."""
        terms = sorted(terms, key=lambda t: (t[0][0], t[0][1]))
        tree = {terms[0][0]}
        rest = terms[1:]
        while rest:
            rest.sort(key=lambda t: min(abs(t[0][0] - c[0]) + abs(t[0][1] - c[1]) for c in tree))
            t = rest.pop(0)
            untreed = {r[0] for r in rest}
            path = self.route(net, t[0], t[1], tree, untreed)
            if path is None:
                return False
            self.commit(net, path)
            tree.update(path)
        return True

    def wires(self, net):
        es = self.edges.get(net, set())
        adj = {}
        for a, b in es:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)

        def is_node(c):
            nb = adj[c]
            if len(nb) != 2:
                return True
            return (nb[0][0] - c[0], nb[0][1] - c[1]) != (c[0] - nb[1][0], c[1] - nb[1][1])
        segs, seen = [], set()
        for a in adj:
            if not is_node(a):
                continue
            for b in adj[a]:
                if (a, b) in seen:
                    continue
                d = (b[0] - a[0], b[1] - a[1])
                cur, nxt = a, b
                seen.update({(cur, nxt), (nxt, cur)})
                while not is_node(nxt):
                    cur, nxt = nxt, (nxt[0] + d[0], nxt[1] + d[1])
                    seen.update({(cur, nxt), (nxt, cur)})
                segs.append((a, nxt))
        juncs = [c for c in adj if len(adj[c]) >= 3]
        return segs, juncs


# ---------------------------------------------------------------- emitters


def text_item(txt, x, y, size=1.8):
    return [Sym("text"), txt, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), x, y, 0],
            [Sym("effects"), [Sym("font"), [Sym("size"), size, size], [Sym("bold"), Sym("yes")]],
             [Sym("justify"), Sym("left"), Sym("bottom")]],
            [Sym("uuid"), uid()]]


def rect_item(x1, y1, x2, y2):
    return [Sym("rectangle"), [Sym("start"), x1, y1], [Sym("end"), x2, y2],
            [Sym("stroke"), [Sym("width"), 0.2], [Sym("type"), Sym("dash")],
             [Sym("color"), 132, 132, 132, 1]],
            [Sym("fill"), [Sym("type"), Sym("none")]], [Sym("uuid"), uid()]]


def wire_item(x1, y1, x2, y2):
    return [Sym("wire"), [Sym("pts"), [Sym("xy"), x1, y1], [Sym("xy"), x2, y2]],
            [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]],
            [Sym("uuid"), uid()]]


def junction_item(x, y):
    return [Sym("junction"), [Sym("at"), x, y], [Sym("diameter"), 0],
            [Sym("color"), 0, 0, 0, 0], [Sym("uuid"), uid()]]


def sym_instance(lib_id, ref, value, x, y, rot, path, in_bom=True, hide=False, extra=()):
    s = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), x, y, rot], [Sym("unit"), 1],
         [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes" if in_bom else "no")],
         [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")], [Sym("uuid"), uid()]]
    s.extend(extra)
    return s


class Sheet:
    def __init__(self, page, path):
        self.page = page
        self.path = path
        self.items = []
        self.libs = {}
        _, w, h = PAPER[page]
        self.rt = Router(w, h)
        self.terms = {}          # net -> [(cell, outward)]
        self.bbox = {}           # block -> [x1,y1,x2,y2]
        self.nmem = {}           # block -> number of parts

    def grow(self, blk, x1, y1, x2, y2):
        b = self.bbox.setdefault(blk, [x1, y1, x2, y2])
        b[0], b[1] = min(b[0], x1), min(b[1], y1)
        b[2], b[3] = max(b[2], x2), max(b[3], y2)

    def power(self, net, x, y, dx, dy, blk):
        """Power symbol whose connection point is (x, y), body pointing (dx, dy)."""
        plib = POWER_NETS[net]
        self.libs.setdefault(plib, libsym(plib))
        if net.startswith("GND"):
            rot = {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}[(dx, dy)]
        else:
            rot = {(0, -1): 0, (0, 1): 180, (1, 0): 270, (-1, 0): 90}[(dx, dy)]
        _counts["#PWR"] = _counts.get("#PWR", 0) + 1
        pref = "#PWR%03d" % _counts["#PWR"]
        vx, vy = x + dx * 5.5, y + dy * 4.5
        if dy:
            vx = x
        elif net == "GND_ISO":      # 横向きの長い名前は水平に書き、隣の部品に重ねない
            vx = x + dx * (4 + text_w(net) / 2)
        self.items.append(
            [Sym("symbol"), [Sym("lib_id"), plib], [Sym("at"), x, y, rot],
             [Sym("unit"), 1], [Sym("exclude_from_sim"), Sym("no")],
             [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("yes")],
             [Sym("dnp"), Sym("no")], [Sym("uuid"), uid()],
             _prop("Reference", pref, x, y, True),
             _prop("Value", net, vx, vy, net == "GND"),
             _prop("Footprint", "", x, y, True),
             _prop("Datasheet", "", x, y, True),
             [Sym("pin"), "1", [Sym("uuid"), uid()]],
             [Sym("instances"), [Sym("project"), PROJECT,
                                 [Sym("path"), self.path, [Sym("reference"), pref],
                                  [Sym("unit"), 1]]]]])
        if net == "GND_ISO" and dx:
            self.items[-1][10][3][3] = 90
        # keep-out: symbol body + value text
        ex, ey = x + dx * 4, y + dy * 4
        self.rt.block_rect(min(x, ex) - 1.3, min(y, ey) - 1.3, max(x, ex) + 1.3, max(y, ey) + 1.3)
        if net != "GND":
            tw = text_w(net)
            if dy:
                self.rt.block_rect(x - tw / 2, vy - 1, x + tw / 2, vy + 1)
            else:
                self.rt.block_rect(vx - tw / 2, vy - 1, vx + tw / 2, vy + 1)
        self.grow(blk, min(x, ex) - 2, min(y, ey) - 2, max(x, ex) + 2, max(y, ey) + 2)

    def add_comp(self, c):
        sym = self.libs.setdefault(c["lib"], libsym(c["lib"]))
        raw = pins_of(sym)
        missing = set(c["nets"]) - {p[0] for p in raw}
        assert not missing, (c["ref"], missing)
        rot = c["rot"]
        pins = place_pins(raw, rot)
        if c["lib"] == "power:PWR_FLAG":         # wire attaches from below the flag
            pins = [(n, nm, t, x, y, 90) for n, nm, t, x, y, a in pins]
        if c["mirror"]:          # (mirror x): flip vertically; only used with rot 0
            assert rot == 0
            pins = [(n, nm, t, x, -y, (360 - a) % 360) for n, nm, t, x, y, a in pins]
        X = snap(c["at"][0])
        if isinstance(c["at"][1], str):
            Y = self.terms[c["at"][1]][0][0][1] * G
        else:
            Y = snap(c["at"][1])
        blk = c["block"]

        # body keep-out
        pts = [xform(px, py, rot) for px, py in graphics_pts(sym)]
        if c["mirror"]:
            pts = [(x, -y) for x, y in pts]
        pts += [(p[3], p[4]) for p in pins]
        bx1 = X + min(p[0] for p in pts) - 0.6
        bx2 = X + max(p[0] for p in pts) + 0.6
        by1 = Y + min(p[1] for p in pts) - 0.6
        by2 = Y + max(p[1] for p in pts) + 0.6
        self.rt.block_rect(bx1, by1, bx2, by2)
        self.grow(blk, bx1 - 1, by1 - 1, bx2 + 1, by2 + 1)
        self.nmem[blk] = self.nmem.get(blk, 0) + 1

        # reference / value text
        refv, valv = c["ref"], c["value"]
        tw = max(text_w(refv), text_w(valv))
        bl, bt = X + min(p[0] for p in pts), Y + min(p[1] for p in pts)
        br, bb = X + max(p[0] for p in pts), Y + max(p[1] for p in pts)
        vertical2 = len(pins) == 2 and all(abs(p[3]) < 0.01 for p in pins)
        horizontal2 = len(pins) == 2 and not vertical2
        mode = c["txt"] or ("right" if vertical2 else "above" if horizontal2 else "ic")
        if mode == "right":
            x0 = (X + 2.54) if vertical2 else br + 1.5
            rx, ry, vx, vy, just = x0, Y - 1.27, x0, Y + 1.27, "left"
            box = (x0, Y - 2.4, x0 + tw, Y + 2.4)
        elif mode == "left":
            x0 = bl - 1.5
            rx, ry, vx, vy, just = x0, Y - 1.27, x0, Y + 1.27, "right"
            box = (x0 - tw, Y - 2.4, x0, Y + 2.4)
        elif mode in ("above", "below"):
            ty = (min(bt, Y - 1.27) - 1.3) if mode == "above" else (max(bb, Y + 1.27) + 1.3)
            rx, ry, vx, vy, just = X - 0.6, ty, X + 0.6, ty, None
            box = (X - text_w(refv) - 1, ty - 0.9, X + text_w(valv) + 1, ty + 0.9)
        else:
            rx, ry, vx, vy, just = bx2 - 0.6, by1 - 3.8, bx2 - 0.6, by1 - 1.4, "right"
            box = (rx - tw, ry - 1, rx, vy + 0.8)
        self.rt.block_rect(*box, soft=25)
        self.grow(blk, *box)

        def tp(name, val, x, y):
            pr = _prop(name, val, x, y)
            # KiCad keeps fields horizontal/vertical only; under 90/180 rotation it
            # mirrors the justification, so pre-mirror it.
            pr[3][3] = {0: 0, 90: 270, 180: 0, 270: 90}[rot]
            j = just
            if mode in ("above", "below"):
                j = "right" if name == "Reference" else "left"
            if j and rot == 180:
                j = {"left": "right", "right": "left"}[j]
            if j:
                pr[4].append([Sym("justify"), Sym(j)])
            return pr

        s = [Sym("symbol"), [Sym("lib_id"), c["lib"]], [Sym("at"), X, Y, rot]]
        if c["mirror"]:
            s.append([Sym("mirror"), Sym("x")])
        s += [[Sym("unit"), 1],
             [Sym("exclude_from_sim"), Sym("no")],
             [Sym("in_bom"), Sym("yes" if c["in_bom"] else "no")],
             [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("yes" if c["dnp"] else "no")],
             [Sym("uuid"), uid()],
             tp("Reference", refv, rx, ry), tp("Value", valv, vx, vy)]
        fpv = c["fp"]
        if fpv is None:
            fpv = next((p[2] for p in find(sym, "property") if p[1] == "Footprint"), "")
        s.append(_prop("Footprint", fpv, X, Y, True))
        s.append(_prop("Datasheet", "~", X, Y, True))
        if c["mpn"]:
            s.append(_prop("MPN", c["mpn"], X, Y, True))
        lcsc = LCSC.get((c["value"], (c["fp"] or "").split(":")[-1].removesuffix("Metric")),
                        LCSC.get((c["mpn"], None)))
        if lcsc and c["in_bom"]:
            s.append(_prop("LCSC", lcsc, X, Y, True))
        for p in pins:
            s.append([Sym("pin"), p[0], [Sym("uuid"), uid()]])
        s.append([Sym("instances"), [Sym("project"), PROJECT,
                                     [Sym("path"), self.path, [Sym("reference"), c["ref"]],
                                      [Sym("unit"), 1]]]])
        self.items.append(s)

        # pins: signal -> router terminal, power -> stub + symbol, NC -> marker
        ends, sigs, done = [], [], set()
        for p in pins:
            px, py = X + p[3], Y + p[4]
            key = cell(px, py)
            net = c["nets"].get(p[0], "__unset__")
            if key in done:
                continue
            done.add(key)
            if net in ("__unset__", None):
                if p[2] != "no_connect":
                    self.items.append([Sym("no_connect"), [Sym("at"), px, py],
                                       [Sym("uuid"), uid()]])
                continue
            d = outward(p[5])
            if net in POWER_NETS:
                ex, ey = px + d[0] * 2.54, py + d[1] * 2.54
                self.items.append(wire_item(px, py, ex, ey))
                self.rt.block_rect(min(px, ex) - 0.6, min(py, ey) - 0.6,
                                   max(px, ex) + 0.6, max(py, ey) + 0.6)
                ends.append((net, ex, ey, d[0], d[1]))
            else:
                self.terms.setdefault(net, []).append((key, d))
                self.rt.add_pin(net, px, py, d)
                sigs.append((px + d[0] * 2.54, py + d[1] * 2.54, d))
        self._power_ends(ends, sigs, blk)

    def _power_ends(self, ends, sigs, blk):
        handled = set()
        for i, (net, ex, ey, dx, dy) in enumerate(ends):
            if i in handled:
                continue
            grp = [j for j, e in enumerate(ends) if e[0] == net and e[3] == dx and e[4] == dy
                   and (abs(e[2] - ey) < 0.01 if dy else abs(e[1] - ex) < 0.01)]
            # 間に信号ピンがある電源ピン同士は縦棒でつながない (信号の引き出しをふさぐため)
            def cut_by_signal(j):
                k = 2 if dx else 1
                lo, hi = sorted((ends[i][k], ends[j][k]))
                o = 1 if dx else 2
                return any(q[2] == (dx, dy) and abs(q[o - 1] - ends[i][o]) < 0.01
                           and lo < q[k - 1] < hi for q in sigs)
            grp = [j for j in grp if j not in handled and not cut_by_signal(j)]
            if len(grp) > 1:
                pts = [ends[j] for j in grp]
                if dy:
                    lo, hi = min(e[1] for e in pts), max(e[1] for e in pts)
                    clash = any(abs(e[2] - ey) < 0.01 and lo < e[1] < hi
                                for k, e in enumerate(ends) if k not in grp)
                else:
                    lo, hi = min(e[2] for e in pts), max(e[2] for e in pts)
                    clash = any(abs(e[1] - ex) < 0.01 and lo < e[2] < hi
                                for k, e in enumerate(ends) if k not in grp)
                if not clash:
                    handled.update(grp)
                    if dy:
                        self.items.append(wire_item(lo, ey, hi, ey))
                        self.rt.block_rect(lo - 0.6, ey - 0.6, hi + 0.6, ey + 0.6)
                        self.items.extend(junction_item(e[1], ey) for e in pts if lo < e[1] < hi)
                        self.power(net, lo, ey, dx, dy, blk)
                    else:
                        self.items.append(wire_item(ex, lo, ex, hi))
                        self.rt.block_rect(ex - 0.6, lo - 0.6, ex + 0.6, hi + 0.6)
                        self.items.extend(junction_item(ex, e[2]) for e in pts if lo < e[2] < hi)
                        self.power(net, ex, hi if net.startswith("GND") else lo, dx, dy, blk)
                    continue
            handled.add(i)
            self.power(net, ex, ey, dx, dy, blk)

    def add_flag(self, net, x, y, blk):
        x, y = snap(x), snap(y)
        self.libs.setdefault("power:PWR_FLAG", libsym("power:PWR_FLAG"))
        _counts["#FLG"] = _counts.get("#FLG", 0) + 1
        ref = "#FLG%02d" % _counts["#FLG"]
        frot = 0 if net.startswith("GND") else 180
        self.items.append(
            [Sym("symbol"), [Sym("lib_id"), "power:PWR_FLAG"], [Sym("at"), x, y, frot],
             [Sym("unit"), 1], [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no")],
             [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")], [Sym("uuid"), uid()],
             _prop("Reference", ref, x, y, True),
             _prop("Value", "PWR_FLAG", x + 1.5, y + (-4 if frot == 0 else 4)),
             _prop("Footprint", "", x, y, True), _prop("Datasheet", "", x, y, True),
             [Sym("pin"), "1", [Sym("uuid"), uid()]],
             [Sym("instances"), [Sym("project"), PROJECT,
                                 [Sym("path"), self.path, [Sym("reference"), ref],
                                  [Sym("unit"), 1]]]]])
        self.items[-1][10][4].append([Sym("justify"), Sym("left")])
        self.rt.block_rect(x - 2, y - 6, x + 12, y + 6)
        self.power(net, x, y, 0, 1 if net.startswith("GND") else -1, blk)

    def add_tie(self, key, x, y, blk):
        net = key.split("~")[0]
        x, y = snap(x), snap(y)
        d = (0, -1) if net == "GND" else (0, 1)     # wire leaves toward the circuit
        self.power(net, x, y, 0, -d[1], blk)
        self.terms.setdefault(key, []).append((cell(x, y), d))
        self.rt.add_pin(key, x, y, d)

    def add_port(self, net, x, y, side, shape):
        if y is None or isinstance(y, str):     # align with the first pin of that net
            y = self.terms[y or net][0][0][1] * G
        x, y = snap(x), round(y / G) * G
        ang, just, d = (180, "right", (1, 0)) if side == "L" else (0, "left", (-1, 0))
        self.items.append([Sym("hierarchical_label"), net, [Sym("shape"), Sym(shape)],
                           [Sym("at"), x, y, ang],
                           [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
                            [Sym("justify"), Sym(just)]],
                           [Sym("uuid"), uid()]])
        tw = text_w(net) + 2.5
        if side == "L":
            self.rt.block_rect(x - tw, y - 1.3, x - 0.1, y + 1.3)
        else:
            self.rt.block_rect(x + 0.1, y - 1.3, x + tw, y + 1.3)
        self.rt.block_rect(x, y - 1.3, x, y + 1.3)
        self.terms.setdefault(net, []).append((cell(x, y), d))
        self.rt.add_pin(net, x, y, d)

    def route_all(self):
        nets = [(n, t) for n, t in self.terms.items() if len(t) >= 2]

        def span(nt):
            cs = [c for c, _ in nt[1]]
            return (max(c[0] for c in cs) - min(c[0] for c in cs)
                    + max(c[1] for c in cs) - min(c[1] for c in cs))
        nets.sort(key=span)
        for _ in range(10):             # rip-up and retry: failed nets go first
            self.rt.occ, self.rt.edges = {}, {}
            failed = [n for n, t in nets if not self.rt.route_net(n, t)]
            if not failed:
                break
            nets = ([x for x in nets if x[0] in failed] +
                    [x for x in nets if x[0] not in failed])
        for net, terms in self.terms.items():
            if len(terms) < 2:
                failed.append(net + "(1 terminal)")
        for net in self.rt.edges:
            segs, juncs = self.rt.wires(net)
            for a, b in segs:
                self.items.append(wire_item(a[0] * G, a[1] * G, b[0] * G, b[1] * G))
            for j in juncs:
                self.items.append(junction_item(j[0] * G, j[1] * G))
        return failed

    def frames(self):
        for name, (x1, y1, x2, y2) in self.bbox.items():
            if self.nmem.get(name, 0) < 2:
                continue
            x1, y1, x2, y2 = x1 - 2, y1 - 6, x2 + 2, y2 + 2
            self.items.append(rect_item(x1, y1, x2, y2))
            self.items.append(text_item(name, x1 + 1.5, y1 + 4))


def build_sheet(page, root_uuid, sheet_uuid):
    sh = Sheet(page, "/%s/%s" % (root_uuid, sheet_uuid))
    for c in PAGES[page]:
        sh.add_comp(c)
    for net, x, y, blk in FLAGS.get(page, []):
        sh.add_flag(net, x, y, blk)
    for key, x, y, blk in TIES.get(page, []):
        sh.add_tie(key, x, y, blk)
    for net, x, y, side, shape in PORTS.get(page, []):
        sh.add_port(net, x, y, side, shape)
    failed = sh.route_all()
    sh.frames()
    paper = PAPER[page][0]
    doc = [Sym("kicad_sch"), [Sym("version"), Sym("20231120")],
           [Sym("generator"), "eeschema"], [Sym("generator_version"), "8.0"],
           [Sym("uuid"), sheet_file_uuid[page]], [Sym("paper"), paper],
           [Sym("lib_symbols")] + list(sh.libs.values())] + sh.items
    return doc, failed


sheet_file_uuid = {n: uid() for n, _ in SHEETS}


def sheet_symbol(x, y, w, h, title, fname, su, root_uuid, pnum, pins):
    s = [Sym("sheet"), [Sym("at"), x, y], [Sym("size"), w, h],
         [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")],
         [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")],
         [Sym("fields_autoplaced"), Sym("yes")],
         [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]],
         [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]],
         [Sym("uuid"), su],
         [Sym("property"), "Sheetname", title, [Sym("at"), x, y - 0.7, 0],
          [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
           [Sym("justify"), Sym("left"), Sym("bottom")]]],
         [Sym("property"), "Sheetfile", fname + ".kicad_sch",
          [Sym("at"), x, y + h + 0.6, 0],
          [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
           [Sym("justify"), Sym("left"), Sym("top")]]]]
    for name, shape, px, py, right in pins:
        s.append([Sym("pin"), name, Sym(shape), [Sym("at"), px, py, 0 if right else 180],
                  [Sym("uuid"), uid()],
                  [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
                   [Sym("justify"), Sym("right" if right else "left")]]])
    s.append([Sym("instances"), [Sym("project"), PROJECT,
                                 [Sym("path"), "/" + root_uuid, [Sym("page"), str(pnum)]]]])
    return s


def main():
    os.makedirs(OUT, exist_ok=True)
    root_uuid = uid()
    sus = {n: uid() for n, _ in SHEETS}
    bad = False
    for fname, _ in SHEETS:
        doc, failed = build_sheet(fname, root_uuid, sus[fname])
        if failed:
            bad = True
            print("UNROUTED on", fname, ":", ", ".join(failed))
        with open(os.path.join(OUT, fname + ".kicad_sch"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(dump(doc) + "\n")
    for old in ("mcu", "comm"):
        p = os.path.join(OUT, old + ".kicad_sch")
        if os.path.exists(p):
            os.remove(p)

    # root: power | ctrl | bridge in a row; shared nets wired straight across
    shape = {pg: {n: sh for n, _, _, _, sh in PORTS.get(pg, [])} for pg, _ in SHEETS}
    left = [n for n in shape["power"] if n in shape["ctrl"]]
    right = [n for n in shape["bridge"] if n in shape["ctrl"]]
    W, y0 = 50.8, 40.64
    px, cx, bx = 25.4, 101.6, 177.8
    h = GRID * (max(len(left), len(right)) + 3)
    pins = {"power": [], "ctrl": [], "bridge": []}
    wires = []
    for i, n in enumerate(left):
        py = y0 + GRID * (i + 2)
        pins["power"].append((n, shape["power"][n], px + W, py, True))
        pins["ctrl"].append((n, shape["ctrl"][n], cx, py, False))
        wires.append(wire_item(px + W, py, cx, py))
    for i, n in enumerate(right):
        py = y0 + GRID * (i + 2)
        pins["ctrl"].append((n, shape["ctrl"][n], cx + W, py, True))
        pins["bridge"].append((n, shape["bridge"][n], bx, py, False))
        wires.append(wire_item(cx + W, py, bx, py))
    titles = dict(SHEETS)
    syms = [sheet_symbol(x, y0, W, h, titles[pg], pg, sus[pg], root_uuid, k + 2, pins[pg])
            for k, (pg, x) in enumerate([("power", px), ("ctrl", cx), ("bridge", bx)])]
    root = [Sym("kicad_sch"), [Sym("version"), Sym("20231120")],
            [Sym("generator"), "eeschema"], [Sym("generator_version"), "8.0"],
            [Sym("uuid"), root_uuid], [Sym("paper"), "A4"],
            [Sym("title_block"), [Sym("title"), "固いパンケーキ モータードライバ"],
             [Sym("comment"), 1, "tools/gen_sch.py で生成"]],
            [Sym("lib_symbols")]] + syms + wires + [
            [Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]]]
    with open(os.path.join(OUT, PROJECT + ".kicad_sch"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(dump(root) + "\n")
    pro = os.path.join(OUT, PROJECT + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", encoding="utf-8") as f:
            f.write('{\n  "meta": {\n    "filename": "%s.kicad_pro",\n    "version": 1\n  }\n}\n'
                    % PROJECT)
    lib = [Sym("kicad_symbol_lib"), [Sym("version"), Sym("20231120")],
           [Sym("generator"), "gen_sch"]]
    for name, build in CUSTOM.items():
        lib.append(build(name))
    with open(os.path.join(OUT, "pancake.kicad_sym"), "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(lib) + "\n")
    with open(os.path.join(OUT, "sym-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "pancake")(type "KiCad")'
                '(uri "${KIPRJMOD}/pancake.kicad_sym")(options "")(descr "固いパンケーキ用"))\n)\n')
    with open(os.path.join(OUT, "fp-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "pancake")(type "KiCad")'
                '(uri "${KIPRJMOD}/pancake.pretty")(options "")(descr "固いパンケーキ用"))\n)\n')
    print("written to", OUT)
    return 1 if bad else 0


if __name__ == "__main__":
    # 配線結果が set の順序 (文字列ハッシュ) に依存するので、毎回同じ結果になるよう固定する
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        sys.exit(subprocess.call([sys.executable] + sys.argv))
    sys.exit(main())

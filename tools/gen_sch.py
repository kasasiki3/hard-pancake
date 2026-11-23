"""固いパンケーキ: KiCad回路図ジェネレータ。

部品と接続(ネット)をここに書き、ピン先端にスタブ配線とラベルを付けた
.kicad_sch 一式を kicad/ に出力する。配置は自動の流し込みなので、
見た目は KiCad 上で整える前提。

実行: python tools/gen_sch.py
"""
import math
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexp import Sym, dump, find, first, parse  # noqa: E402

KILIB = "C:/Program Files/KiCad/10.0/share/kicad/symbols/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kicad")
PROJECT = "pancake"
POWER_NETS = {"GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V",
              "+12V": "power:+12V", "VBUS": "power:VBUS"}
NC = None
GRID = 2.54


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
    top = h / 2
    top = math.ceil(top / GRID) * GRID

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


CUSTOM = {
    "DRV8300D_RGE": make_ic("DRV8300D_RGE", "U", [
        ("22", "INHA", "input"), ("1", "INLA", "input"), ("23", "INHB", "input"),
        ("2", "INLB", "input"), ("24", "INHC", "input"), ("3", "INLC", "input"), None,
        ("4", "GVDD", "power_in"), ("5", "MODE", "input"), ("21", "DT", "input"),
        ("7", "NC", "no_connect"), ("8", "NC", "no_connect"), ("6", "GND", "power_in"),
        ("25", "PAD", "passive")], [
        ("20", "BSTA", "passive"), ("19", "GHA", "output"), ("18", "SHA", "passive"),
        ("11", "GLA", "output"), ("17", "BSTB", "passive"), ("16", "GHB", "output"),
        ("15", "SHB", "passive"), ("10", "GLB", "output"), ("14", "BSTC", "passive"),
        ("13", "GHC", "output"), ("12", "SHC", "passive"), ("9", "GLC", "output")], 17.78),
    "LMR51625": make_ic("LMR51625", "U", [
        ("3", "VIN", "power_in"), ("2", "EN", "input"), ("4", "GND", "power_in")], [
        ("6", "CB", "passive"), ("5", "SW", "output"), ("1", "FB", "input")]),
    "RT9013-33": make_ic("RT9013-33", "U", [
        ("1", "VIN", "power_in"), ("3", "EN", "input"), ("2", "GND", "power_in")], [
        ("5", "VOUT", "power_out"), ("4", "NC", "no_connect")]),
    "TCAN1044V": make_ic("TCAN1044V", "U", [
        ("3", "VCC", "power_in"), ("5", "VIO", "power_in"), ("1", "TXD", "input"),
        ("4", "RXD", "output"), ("8", "STB", "input"), ("2", "GND", "power_in")], [
        ("7", "CANH", "bidirectional"), ("6", "CANL", "bidirectional")]),
}

# ---------------------------------------------------------------- design
FP = {
    "R0402": "Resistor_SMD:R_0402_1005Metric", "R0603": "Resistor_SMD:R_0603_1608Metric",
    "R2512": "Resistor_SMD:R_2512_6332Metric",
    "C0402": "Capacitor_SMD:C_0402_1005Metric", "C0603": "Capacitor_SMD:C_0603_1608Metric",
    "C0805": "Capacitor_SMD:C_0805_2012Metric", "C1206": "Capacitor_SMD:C_1206_3216Metric",
    "C1210": "Capacitor_SMD:C_1210_3225Metric", "CP10": "Capacitor_SMD:CP_Elec_10x10.5",
    "SMB": "Diode_SMD:D_SMB", "LED0603": "LED_SMD:LED_0603_1608Metric",
    "SOT23": "Package_TO_SOT_SMD:SOT-23", "SOT23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT23-6": "Package_TO_SOT_SMD:SOT-23-6", "SOIC8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "XTAL3225": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
}

PAGES = {}   # page -> list of comps
_counts = {}


CUR_BLOCK = ["?"]


def block(name):
    CUR_BLOCK[0] = name


def comp(page, prefix, lib_id, value, nets, fp=None, mpn=None, in_bom=True, rot=0):
    _counts[prefix] = _counts.get(prefix, 0) + 1
    ref = "%s%d" % (prefix, _counts[prefix])
    PAGES.setdefault(page, []).append(dict(ref=ref, lib=lib_id, value=value, nets=nets,
                                           fp=FP.get(fp, fp), mpn=mpn, in_bom=in_bom,
                                           rot=rot, block=CUR_BLOCK[0]))
    return ref


def _rot2(a, b):
    """Series parts (both ends signal) lie horizontal; shunts to a rail stand vertical."""
    return 90 if a not in POWER_NETS and b not in POWER_NETS else 0


def R(page, value, a, b, fp="R0402"):
    return comp(page, "R", "Device:R", value, {"1": a, "2": b}, fp, rot=_rot2(a, b))


def C(page, value, a, b, fp="C0402"):
    return comp(page, "C", "Device:C", value, {"1": a, "2": b}, fp, rot=_rot2(a, b))


def flag(page, net):
    comp(page, "#FLG", "power:PWR_FLAG", "PWR_FLAG", {"1": net}, in_bom=False)


# ---- 電源
P = "power"
block("電源入力・保護")
comp(P, "J", "Connector_Generic:Conn_01x02", "電源入力(未選定)", {"1": "VBUS", "2": "GND"})
flag(P, "VBUS")
flag(P, "GND")
flag(P, "+5V")
comp(P, "D", "Device:D_TVS", "SMBJ30A", {"1": "VBUS", "2": "GND"}, "SMB")
for _ in range(2):
    comp(P, "C", "Device:C_Polarized", "220uF 50V", {"1": "VBUS", "2": "GND"}, "CP10",
         "JVJ50V220M10x10")
block("12V ゲート駆動電源 (TPS7A4101)")
comp(P, "U", "Regulator_Linear:TPS7A4101DGN", "TPS7A4101DGNR",
     {"8": "VBUS", "5": "VBUS", "1": "+12V", "2": "FB_12V", "4": "GND", "9": "GND",
      "3": NC, "6": NC, "7": NC})
R(P, "91k", "+12V", "FB_12V")
R(P, "10k", "FB_12V", "GND")
C(P, "10nF", "+12V", "FB_12V")
C(P, "1uF 100V", "VBUS", "GND", "C0805")
C(P, "10uF 25V", "+12V", "GND", "C0805")
block("5V 降圧 (LMR51625)")
comp(P, "U", "pancake:LMR51625", "LMR51625YDDCR",
     {"3": "VBUS", "2": "VBUS", "4": "GND", "6": "CB_5V", "5": "SW_5V", "1": "FB_5V"}, "SOT23-6")
C(P, "100nF 50V", "CB_5V", "SW_5V")
comp(P, "L", "Device:L", "4.7uH", {"1": "SW_5V", "2": "+5V"}, None, "MWSC0630H4R7MT")
R(P, "53.6k", "+5V", "FB_5V")
R(P, "10.2k", "FB_5V", "GND")
C(P, "2.2uF 100V", "VBUS", "GND", "C1210")
C(P, "2.2uF 100V", "VBUS", "GND", "C1210")
C(P, "100nF 100V", "VBUS", "GND", "C0603")
C(P, "22uF 16V", "+5V", "GND", "C1206")
block("3.3V LDO (RT9013)")
comp(P, "U", "pancake:RT9013-33", "RT9013-33GB",
     {"1": "+5V", "3": "+5V", "2": "GND", "5": "+3V3", "4": NC}, "SOT23-5")
C(P, "1uF 25V", "+5V", "GND", "C0603")
C(P, "1uF 25V", "+3V3", "GND", "C0603")
block("電圧・温度検出")
R(P, "100k", "VBUS", "VBUS_SENSE")
R(P, "5.6k", "VBUS_SENSE", "GND")
C(P, "10nF", "VBUS_SENSE", "GND")
R(P, "10k", "+3V3", "NTC_SENSE")
comp(P, "TH", "Device:Thermistor_NTC", "10k NTC", {"1": "NTC_SENSE", "2": "GND"}, "R0603",
     "NCP18XH103F03RB")

# ---- パワー段
B = "bridge"
block("ゲートドライバ (DRV8300)")
drv = {"22": "PWM_AH", "1": "PWM_AL", "23": "PWM_BH", "2": "PWM_BL", "24": "PWM_CH",
       "3": "PWM_CL", "4": "+12V", "5": NC, "21": NC, "7": NC, "8": NC, "6": "GND",
       "25": "GND"}
for ph, (bst, gh, sh, gl) in zip("ABC", [("20", "19", "18", "11"), ("17", "16", "15", "10"),
                                       ("14", "13", "12", "9")]):
    drv.update({bst: "BST_" + ph, gh: "GH_" + ph, sh: "PHASE_" + ph, gl: "GL_" + ph})
comp(B, "U", "pancake:DRV8300D_RGE", "DRV8300DRGER", drv)
C(B, "10uF 25V", "+12V", "GND", "C0805")
C(B, "100nF 50V", "+12V", "GND")
for ph in "ABC":
    block("%s相 ハーフブリッジ" % ph)
    C(B, "1uF 25V", "BST_" + ph, "PHASE_" + ph, "C0603")
    R(B, "3.3", "GH_" + ph, "GATE_%sH" % ph, "R0603")
    R(B, "3.3", "GL_" + ph, "GATE_%sL" % ph, "R0603")
    comp(B, "Q", "Transistor_FET:NTMFS016N06CT1G", "NTMFS5C628NLT1G",
         {"4": "GATE_%sH" % ph, "5": "VBUS", "1": "PHASE_" + ph, "2": "PHASE_" + ph,
          "3": "PHASE_" + ph})
    comp(B, "Q", "Transistor_FET:NTMFS016N06CT1G", "NTMFS5C628NLT1G",
         {"4": "GATE_%sL" % ph, "5": "PHASE_" + ph, "1": "SHUNT_" + ph, "2": "SHUNT_" + ph,
          "3": "SHUNT_" + ph})
    comp(B, "R", "Device:R", "0.5m", {"1": "SHUNT_" + ph, "2": "GND"}, "R2512",
         "RLM25FEGMR50M")
    C(B, "100nF 100V", "VBUS", "GND", "C0603")
    C(B, "2.2uF 100V", "VBUS", "GND", "C1210")
    comp(B, "J", "Connector_Generic:Conn_01x01", "モーター%s(未選定)" % ph, {"1": "PHASE_" + ph})

# ---- MCU
M = "mcu"
block("MCU")
mcu = {"1": "+3V3", "2": "ENC1_Z", "3": NC, "4": NC, "5": "OSC_IN", "6": "OSC_OUT",
       "7": "NRST", "8": "VBUS_SENSE", "9": "ISENSE_A", "10": NC, "11": NC, "12": "ENC2_B",
       "13": "LED2", "14": "ENC2_A", "15": "ISENSE_B", "16": "ISENSE_C", "17": NC, "18": NC,
       "19": "GND", "20": "+3V3", "21": "+3V3", "22": "ENC2_Z", "23": "GND", "24": "+3V3",
       "25": "NTC_SENSE", "26": "CAN_STB", "27": "PWM_AL", "28": "PWM_BL", "29": "PWM_CL",
       "30": "PWM_AH", "31": "PWM_BH", "32": "PWM_CH", "33": "CAN_RX", "34": "CAN_TX",
       "35": "GND", "36": "+3V3", "37": "SWDIO", "38": "SWCLK", "39": "ENC1_CS",
       "40": "ENC1_SCK", "41": "ENC1_MISO", "42": "ENC1_MOSI", "43": "ENC1_A", "44": "ENC1_B",
       "45": "BOOT0", "46": "LED1", "47": "GND", "48": "+3V3"}
comp(M, "U", "MCU_ST_STM32G4:STM32G431CBTx", "STM32G431CBT6", mcu)
block("クロック・リセット・BOOT0")
comp(M, "Y", "Device:Crystal_GND24", "8MHz", {"1": "OSC_IN", "3": "OSC_OUT", "2": "GND",
                                              "4": "GND"}, "XTAL3225", "TX32258M4FBDD2T")
C(M, "15pF", "OSC_IN", "GND")
C(M, "15pF", "OSC_OUT", "GND")
C(M, "100nF", "NRST", "GND")
R(M, "10k", "BOOT0", "GND")
block("パスコン (VDD×3, VDDA, VREF+)")
for _ in range(3):
    C(M, "100nF", "+3V3", "GND")          # VDD x3
C(M, "4.7uF 10V", "+3V3", "GND", "C0603")
C(M, "100nF", "+3V3", "GND")              # VDDA
C(M, "1uF 25V", "+3V3", "GND", "C0603")   # VDDA
C(M, "100nF", "+3V3", "GND")              # VREF+
block("電流検出オフセット")
for ph in "ABC":                          # 電流検出オフセット
    R(M, "1k", "SHUNT_" + ph, "ISENSE_" + ph)
    R(M, "62k", "+3V3", "ISENSE_" + ph)
block("LED・SWD")
for n in ("1", "2"):
    R(M, "1k", "LED" + n, "LED%s_A" % n)
    comp(M, "D", "Device:LED", "LED", {"2": "LED%s_A" % n, "1": "GND"}, "LED0603")
comp(M, "J", "Connector_Generic:Conn_01x05", "SWD(未選定)",
     {"1": "+3V3", "2": "SWDIO", "3": "SWCLK", "4": "NRST", "5": "GND"})

# ---- CAN・エンコーダ
K = "comm"
block("CANトランシーバ")
comp(K, "U", "pancake:TCAN1044V", "TCAN1044VDRQ1",
     {"3": "+5V", "5": "+3V3", "1": "CAN_TX", "4": "CAN_RX", "8": "CAN_STB", "2": "GND",
      "7": "CANH", "6": "CANL"}, "SOIC8")
C(K, "100nF", "+5V", "GND")
C(K, "100nF", "+3V3", "GND")
block("CAN保護・スプリット終端")
comp(K, "D", "Power_Protection:NUP2105L", "ESDCAN24-2BLY",
     {"1": "CANH", "2": "CANL", "3": "GND"}, "SOT23")
comp(K, "JP", "Jumper:SolderJumper_2_Open", "終端ON", {"1": "CANH", "2": "CANH_T"},
     in_bom=False)
R(K, "60.4", "CANH_T", "CAN_SPLIT")
R(K, "60.4", "CAN_SPLIT", "CANL")
C(K, "4.7nF", "CAN_SPLIT", "GND")
block("CANコネクタ RJ45×2 (数珠つなぎ)")
for _ in range(2):
    comp(K, "J", "Connector:RJ45", "RJ45", {"1": "CANH", "2": "CANL", "3": "GND", "7": "GND",
                                            "4": NC, "5": NC, "6": NC, "8": NC},
         None, "R-RJ45R08P-A004")
enc = ["ENC1_A", "ENC1_B", "ENC1_Z", "ENC1_CS", "ENC1_SCK", "ENC1_MISO", "ENC1_MOSI",
       "ENC2_A", "ENC2_B", "ENC2_Z"]
block("エンコーダ 直列抵抗")
for s in enc:
    R(K, "100", s, s + "_C")
block("エンコーダ ESD保護")
groups = [enc[0:4], enc[4:8], enc[8:10] + [None, None]]
for g in groups:
    nets = {"5": "+3V3", "2": "GND"}
    for pin, s in zip(("1", "3", "4", "6"), g):
        nets[pin] = s + "_C" if s else NC
    comp(K, "U", "Power_Protection:USBLC6-4SC6", "USBLC6-4SC6", nets, None, "TPUSBLC6-4SC6")
block("エンコーダコネクタ")
comp(K, "J", "Connector_Generic:Conn_01x09", "エンコーダ1 ABZ+SPI(未選定)",
     {"1": "+3V3", "2": "GND", "3": "ENC1_A_C", "4": "ENC1_B_C", "5": "ENC1_Z_C",
      "6": "ENC1_CS_C", "7": "ENC1_SCK_C", "8": "ENC1_MISO_C", "9": "ENC1_MOSI_C"})
comp(K, "J", "Connector_Generic:Conn_01x05", "エンコーダ2 ABZ(未選定)",
     {"1": "+3V3", "2": "GND", "3": "ENC2_A_C", "4": "ENC2_B_C", "5": "ENC2_Z_C"})

SHEETS = [("power", "電源"), ("bridge", "パワー段"), ("mcu", "MCU"), ("comm", "CAN・エンコーダ")]

# ---------------------------------------------------------------- layout & emit


def snap(v):
    return round(v / GRID) * GRID


def outward(angle):
    a = math.radians(angle + 180)
    return round(math.cos(a)), -round(math.sin(a))


def label_len(net):
    return 3.0 + 1.05 * len(net)


def place_pins(pins, rot):
    """Pins transformed by symbol rotation: (num, name, type, sx, sy, angle) with sx,sy
    offsets in schematic coordinates (y down)."""
    r = math.radians(rot)
    out = []
    for num, name, typ, px, py, ang in pins:
        rx = px * math.cos(r) - py * math.sin(r)
        ry = px * math.sin(r) + py * math.cos(r)
        out.append((num, name, typ, round(rx, 4), round(-ry, 4), (ang + rot) % 360))
    return out


def comp_bbox(c, pins):
    xs = [p[3] for p in pins] + [0]
    ys = [p[4] for p in pins] + [0]
    minx, maxx, miny, maxy = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
    for p in pins:
        net = c["nets"].get(p[0])
        if not net:
            continue
        dx, dy = outward(p[5])
        ext = 2.54 + (6.5 if net in POWER_NETS else label_len(net))
        minx = min(minx, p[3] + dx * ext - (1.5 if dx == 0 else 0))
        maxx = max(maxx, p[3] + dx * ext + (1.5 if dx == 0 else 0))
        miny = min(miny, p[4] + dy * ext)
        maxy = max(maxy, p[4] + dy * ext)
    # room for reference/value text
    if len(pins) == 2 and all(abs(p[3]) < 0.01 for p in pins):       # vertical 2-pin
        maxx = max(maxx, 12)
    elif len(pins) == 2:                                               # horizontal 2-pin
        miny = min(miny, -6)
        maxy = max(maxy, 5)
    else:
        miny = min(miny, min(p[4] for p in pins) - 9)
    return minx, miny, maxx, maxy


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


def power_item(net, x, y, dx, dy, libs, path):
    """Power symbol at (x, y) whose body points away from the pin (dx, dy)."""
    plib = POWER_NETS[net]
    libs.setdefault(plib, libsym(plib))
    if net == "GND":
        rot = {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}[(dx, dy)]
    else:
        rot = {(0, -1): 0, (0, 1): 180, (1, 0): 270, (-1, 0): 90}[(dx, dy)]
    _counts["#PWR"] = _counts.get("#PWR", 0) + 1
    pref = "#PWR%03d" % _counts["#PWR"]
    vx, vy = x + dx * 5.5, y + dy * 4.5
    return [Sym("symbol"), [Sym("lib_id"), plib], [Sym("at"), x, y, rot],
            [Sym("unit"), 1], [Sym("exclude_from_sim"), Sym("no")],
            [Sym("in_bom"), Sym("no")], [Sym("on_board"), Sym("yes")],
            [Sym("dnp"), Sym("no")], [Sym("uuid"), uid()],
            _prop("Reference", pref, x, y, True),
            _prop("Value", net, vx, vy, net == "GND"),
            _prop("Footprint", "", x, y, True),
            _prop("Datasheet", "", x, y, True),
            [Sym("pin"), "1", [Sym("uuid"), uid()]],
            [Sym("instances"), [Sym("project"), PROJECT,
                                [Sym("path"), path, [Sym("reference"), pref],
                                 [Sym("unit"), 1]]]]]


def junction_item(x, y):
    return [Sym("junction"), [Sym("at"), x, y], [Sym("diameter"), 0],
            [Sym("color"), 0, 0, 0, 0], [Sym("uuid"), uid()]]


def label_item(net, x, y, dx, dy):
    ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
    just = "left" if ang in (0, 90) else "right"
    return [Sym("global_label"), net, [Sym("shape"), Sym("passive")],
            [Sym("at"), x, y, ang], [Sym("fields_autoplaced"), Sym("yes")],
            [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
             [Sym("justify"), Sym(just)]],
            [Sym("uuid"), uid()],
            [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0],
             [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
              [Sym("hide"), Sym("yes")]]]]


def emit_comp(c, sym, pins, X, Y, libs, path, items):
    is_power = c["lib"].startswith("power:")
    ref = c["ref"]
    rot = c["rot"]
    if len(pins) == 2 and all(abs(p[3]) < 0.01 for p in pins):
        rx, ry, vx, vy, just = X + 2.54, Y - 1.27, X + 2.54, Y + 1.27, "left"
    elif len(pins) == 2:
        rx, ry, vx, vy, just = X, Y - 3.0, X, Y + 3.3, None
    else:
        top = min(p[4] for p in pins)
        right = max(p[3] for p in pins)
        rx, ry, vx, vy, just = X + right + 2.54, Y + top - 4.0, X + right + 2.54, Y + top - 1.6, "left"

    def tp(name, val, x, y, hide=False):
        pr = _prop(name, val, x, y, hide)
        pr[3][3] = rot
        if just:
            pr[4].append([Sym("justify"), Sym(just)])
        return pr

    s = [Sym("symbol"), [Sym("lib_id"), c["lib"]], [Sym("at"), X, Y, rot], [Sym("unit"), 1],
         [Sym("exclude_from_sim"), Sym("no")],
         [Sym("in_bom"), Sym("yes" if c["in_bom"] else "no")],
         [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")], [Sym("uuid"), uid()],
         tp("Reference", ref, rx, ry, is_power),
         tp("Value", c["value"], vx, vy, is_power)]
    fpv = c["fp"]
    if fpv is None:
        fpv = next((p[2] for p in find(sym, "property") if p[1] == "Footprint"), "")
    s.append(_prop("Footprint", fpv, X, Y, True))
    s.append(_prop("Datasheet", "~", X, Y, True))
    if c["mpn"]:
        s.append(_prop("MPN", c["mpn"], X, Y, True))
    for p in pins:
        s.append([Sym("pin"), p[0], [Sym("uuid"), uid()]])
    s.append([Sym("instances"), [Sym("project"), PROJECT,
                                 [Sym("path"), path, [Sym("reference"), ref],
                                  [Sym("unit"), 1]]]])
    items.append(s)

    # stubs
    ends = []          # (net, ex, ey, dx, dy)
    done = set()
    for p in pins:
        px, py = X + p[3], Y + p[4]
        key = (round(px, 3), round(py, 3))
        net = c["nets"].get(p[0], "__unset__")
        if key in done:
            continue
        done.add(key)
        if net == "__unset__" or net is None:
            if p[2] != "no_connect":
                items.append([Sym("no_connect"), [Sym("at"), px, py], [Sym("uuid"), uid()]])
            continue
        dx, dy = outward(p[5])
        ex, ey = px + dx * 2.54, py + dy * 2.54
        items.append(wire_item(px, py, ex, ey))
        ends.append((net, ex, ey, dx, dy))

    # merge same power net on the same side into one bus with one symbol
    handled = set()
    for i, (net, ex, ey, dx, dy) in enumerate(ends):
        if i in handled or net not in POWER_NETS:
            continue
        grp = [j for j, e in enumerate(ends) if e[0] == net and e[3] == dx and e[4] == dy
               and (abs(e[2] - ey) < 0.01 if dy else abs(e[1] - ex) < 0.01)]
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
                    items.append(wire_item(lo, ey, hi, ey))
                    inner = [e[1] for e in pts if lo < e[1] < hi]
                    items.extend(junction_item(v, ey) for v in inner)
                    items.append(power_item(net, lo, ey, dx, dy,
                                            libs, path))
                else:
                    items.append(wire_item(ex, lo, ex, hi))
                    inner = [e[2] for e in pts if lo < e[2] < hi]
                    items.extend(junction_item(ex, v) for v in inner)
                    items.append(power_item(net, ex, hi if net == "GND" else lo, dx, dy,
                                            libs, path))
                continue
        handled.add(i)
        items.append(power_item(net, ex, ey, dx, dy, libs, path))
    for net, ex, ey, dx, dy in ends:
        if net not in POWER_NETS:
            items.append(label_item(net, ex, ey, dx, dy))


def build_sheet(page, root_uuid, sheet_uuid):
    comps = PAGES[page]
    libs = {}
    items = []
    path = "/%s/%s" % (root_uuid, sheet_uuid)
    pnum = [i for i, (n, _) in enumerate(SHEETS) if n == page][0] + 2

    # group into blocks, keep order
    blocks = []
    for c in comps:
        if not blocks or blocks[-1][0] != c["block"]:
            blocks.append((c["block"], []))
        sym = libs.setdefault(c["lib"], libsym(c["lib"]))
        raw = pins_of(sym)
        missing = set(c["nets"]) - {p[0] for p in raw}
        assert not missing, (c["ref"], missing)
        pins = place_pins(raw, c["rot"])
        blocks[-1][1].append((c, sym, pins, comp_bbox(c, pins)))

    # lay out each block: members in rows, max block width
    MAXW = 185
    laid = []
    for name, members in blocks:
        rows, row, w = [], [], 0
        for m in members:
            bw = m[3][2] - m[3][0] + 4
            if row and w + bw > MAXW:
                rows.append(row)
                row, w = [], 0
            row.append(m)
            w += bw
        rows.append(row)
        placed, y, bw_max = [], 10.0, 0
        for row in rows:
            x = 4.0
            top = min(m[3][1] for m in row)
            bot = max(m[3][3] for m in row)
            for m in row:
                X = x - m[3][0]
                Y = y - top
                placed.append((m, X, Y))
                x += m[3][2] - m[3][0] + 4
            bw_max = max(bw_max, x)
            y += bot - top + 4
        laid.append((name, placed, bw_max + 2, y + 2))

    # arrange blocks on the page in rows
    page_w = 395
    bx, by, rowh = 15.0, 15.0, 0.0
    for name, placed, bw, bh in laid:
        if bx + bw > page_w and bx > 15:
            bx, by, rowh = 15.0, by + rowh + 8, 0.0
        ox, oy = snap(bx), snap(by)
        items.append(rect_item(ox, oy, ox + bw, oy + bh))
        items.append(text_item(name, ox + 1.5, oy + 5))
        for (c, sym, pins, bb), X, Y in placed:
            emit_comp(c, sym, pins, snap(ox + X), snap(oy + Y), libs, path, items)
        bx += bw + 8
        rowh = max(rowh, bh)
    paper = "A3" if by + rowh < 275 else "A2"
    doc = [Sym("kicad_sch"), [Sym("version"), Sym("20231120")],
           [Sym("generator"), "eeschema"], [Sym("generator_version"), "8.0"],
           [Sym("uuid"), sheet_file_uuid[page]], [Sym("paper"), paper],
           [Sym("lib_symbols")] + list(libs.values())] + items
    return doc, pnum


sheet_file_uuid = {n: uid() for n, _ in SHEETS}


def main():
    os.makedirs(OUT, exist_ok=True)
    root_uuid = uid()
    sheet_syms = []
    for i, (fname, title) in enumerate(SHEETS):
        su = uid()
        doc, pnum = build_sheet(fname, root_uuid, su)
        with open(os.path.join(OUT, fname + ".kicad_sch"), "w", encoding="utf-8", newline="\n") as f:
            f.write(dump(doc) + "\n")
        x, y = 30 + i * 60, 40
        sheet_syms.append([Sym("sheet"), [Sym("at"), x, y], [Sym("size"), 40, 20],
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
                            [Sym("at"), x, y + 20.6, 0],
                            [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
                             [Sym("justify"), Sym("left"), Sym("top")]]],
                           [Sym("instances"), [Sym("project"), PROJECT,
                                               [Sym("path"), "/" + root_uuid,
                                                [Sym("page"), str(pnum)]]]]])
    root = [Sym("kicad_sch"), [Sym("version"), Sym("20231120")],
            [Sym("generator"), "eeschema"], [Sym("generator_version"), "8.0"],
            [Sym("uuid"), root_uuid], [Sym("paper"), "A4"],
            [Sym("title_block"), [Sym("title"), "固いパンケーキ モータードライバ"],
             [Sym("comment"), 1, "tools/gen_sch.py で生成。配置は自動のため KiCad で整える"]],
            [Sym("lib_symbols")]] + sheet_syms + [
            [Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]]]
    with open(os.path.join(OUT, PROJECT + ".kicad_sch"), "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(root) + "\n")
    pro = os.path.join(OUT, PROJECT + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", encoding="utf-8") as f:
            f.write('{\n  "meta": {\n    "filename": "%s.kicad_pro",\n    "version": 1\n  }\n}\n'
                    % PROJECT)
    # project symbol library for the custom parts
    lib = [Sym("kicad_symbol_lib"), [Sym("version"), Sym("20231120")],
           [Sym("generator"), "gen_sch"]]
    for name, build in CUSTOM.items():
        s = build(name)
        lib.append(s)
    with open(os.path.join(OUT, "pancake.kicad_sym"), "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(lib) + "\n")
    with open(os.path.join(OUT, "sym-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "pancake")(type "KiCad")'
                '(uri "${KIPRJMOD}/pancake.kicad_sym")(options "")(descr "固いパンケーキ用"))\n)\n')
    print("written to", OUT)


if __name__ == "__main__":
    main()

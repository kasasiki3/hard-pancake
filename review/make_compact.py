import xml.etree.ElementTree as ET, sys, collections
r = ET.parse(sys.argv[1]).getroot()
out = []
comps = {}
for c in r.find("components"):
    ref = c.get("ref"); val = c.findtext("value"); fp = c.findtext("footprint") or ""
    props = {p.get("name"): p.get("value") for p in c.findall("property")}
    dnp = "DNP" if ("dnp" in props or props.get("DNP")) else ""
    lcsc = props.get("LCSC") or props.get("LCSC Part") or ""
    comps[ref] = (val, fp, dnp, lcsc, c.findtext("libsource") )
pins = collections.defaultdict(list)
nets = []
for n in r.find("nets"):
    name = n.get("name"); nodes = [(x.get("ref"), x.get("pin"), x.get("pinfunction") or "") for x in n.findall("node")]
    nets.append((name, nodes))
    for ref, pin, fn in nodes: pins[ref].append((pin, fn, name))
out.append("# 部品（Ref | 値 | フットプリント | DNP | LCSC）")
key = lambda s: (''.join(ch for ch in s if ch.isalpha()), int(''.join(ch for ch in s if ch.isdigit()) or 0))
for ref in sorted(comps, key=key):
    v, fp, d, l, _ = comps[ref]
    out.append(f"{ref} | {v} | {fp.split(':')[-1]} | {d} | {l}")
    for pin, fn, name in sorted(pins[ref], key=lambda t: (len(t[0]), t[0])):
        out.append(f"    {pin}{'('+fn+')' if fn else ''} -> {name}")
out.append("\n# ネット（ネット名: 接続先）")
for name, nodes in sorted(nets):
    out.append(f"{name}: " + ", ".join(f"{a}.{b}" for a, b, _ in nodes))
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(out))

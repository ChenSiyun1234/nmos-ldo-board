"""Write hardware/nmos-ldo-board.kicad_sch.

Symbols are copied from the KiCad symbol libraries (derived symbols are
flattened the same way KiCad stores them in a schematic). Parts are placed by
hand-chosen coordinates in functional sections; wires are split at every T and
junctions are added, so KiCad's connectivity matches the intended netlist.
The intended pin-to-net map is saved next to the schematic so the exported
KiCad netlist can be checked against it (see check_netlist.py).

    python scripts/build_schematic.py
Set KICAD_SYMBOL_DIR if the KiCad symbol libraries are not found.
"""
import glob
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sexpr import Sym, dump, find, find_all, parse  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "hardware", "nmos-ldo-board.kicad_sch")
PROJECT = "nmos-ldo-board"


def symbol_dir():
    env = os.environ.get("KICAD_SYMBOL_DIR")
    cands = [env] if env else []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), "/usr/share/kicad",
                 "/Applications/KiCad/KiCad.app/Contents/SharedSupport"):
        cands += sorted(glob.glob(os.path.join(base, "KiCad", "*", "share", "kicad", "symbols")), reverse=True)
        cands.append(os.path.join(base, "symbols"))
    for c in cands:
        if c and os.path.isdir(c):
            return c
    raise SystemExit("KiCad symbol libraries not found; set KICAD_SYMBOL_DIR")


SYMDIR = symbol_dir()
_LIBS = {}


def _lib(name):
    if name not in _LIBS:
        with open(os.path.join(SYMDIR, name + ".kicad_sym"), encoding="utf-8") as f:
            tree = parse(f.read())[0]
        _LIBS[name] = {x[1]: x for x in find_all(tree, "symbol")}
    return _LIBS[name]


def flat_symbol(lib, name):
    """Library symbol as KiCad stores it inside a schematic."""
    syms = _lib(lib)
    node = syms[name]
    ext = find(node, "extends")
    if ext is None:
        out = [Sym("symbol"), f"{lib}:{name}"] + [x for x in node[2:]]
        return out
    parent = flat_symbol(lib, ext[1])
    # inherited properties first (child values override), then child-only ones
    child_props = {p[1]: p for p in find_all(node, "property")}
    props = []
    for pp in find_all(parent, "property"):
        props.append(child_props.pop(pp[1], pp))
    props += list(child_props.values())
    out = [Sym("symbol"), f"{lib}:{name}"]
    parent_name = ext[1]
    for x in parent[2:]:
        if isinstance(x, list) and x and x[0] == "property":
            continue
        if isinstance(x, list) and x and x[0] == "symbol":
            y = list(x)
            y[1] = y[1].replace(parent_name + "_", name + "_", 1) if y[1].startswith(parent_name) else y[1]
            # nested parents keep their own unit names; rename any prefix
            if not y[1].startswith(name + "_"):
                y[1] = name + "_" + y[1].split("_", 1)[1] if "_" in y[1] else y[1]
            out.append(y)
            continue
        out.append(x)
    # properties go right after the flags, before the unit symbols
    first_unit = next(i for i, x in enumerate(out) if isinstance(x, list) and x and x[0] == "symbol")
    out = out[:first_unit] + props + out[first_unit:]
    return out


def lib_pins(lib, name):
    node = flat_symbol(lib, name)
    pins = {}

    def walk(n):
        for x in n:
            if isinstance(x, list) and x:
                if x[0] == "pin":
                    at = find(x, "at")
                    num = find(x, "number")[1]
                    pins[num] = (float(at[1]), float(at[2]))
                else:
                    walk(x)
    walk(node)
    return pins


_UUID_NS = uuid.UUID("6f1c2a52-6a0e-4bb4-9a8e-2d3b8f1f5a10")
_uuid_n = [0]


def U():
    """Deterministic UUIDs so a rebuild gives the same file."""
    _uuid_n[0] += 1
    return str(uuid.uuid5(_UUID_NS, f"nmos-ldo-board-{_uuid_n[0]}"))


# ---------------------------------------------------------------- the model
ROOT_UUID = U()
items = []          # top level schematic items
wires = []          # (p1, p2)
labels = []         # (name, p, angle)
pin_points = []     # (p, ref, pin)
lib_used = {}       # lib_id -> (lib, name)
intended = {}       # ref -> {pin: net}
components = []     # for the BOM consistency check
pwr_count = {"#PWR": 0, "#FLG": 0}


def R2(x):
    return round(x * 100) / 100


def tf(px, py, rot, mirror):
    if mirror == "y":
        px = -px
    elif mirror == "x":
        py = -py
    return {0: (px, -py), 90: (-py, -px), 180: (-px, py), 270: (py, px)}[rot]


def prop(name, value, x, y, hide=False, angle=0, justify=None, size=1.27):
    eff = [Sym("effects"), [Sym("font"), [Sym("size"), size, size]]]
    if justify:
        eff.append([Sym("justify")] + [Sym(j) for j in justify.split()])
    p = [Sym("property"), name, value, [Sym("at"), R2(x), R2(y), angle]]
    if hide:
        p.append([Sym("hide"), Sym("yes")])
    p.append(eff)
    return p


def place(ref, lib, name, x, y, rot=0, mirror=None, value=None, footprint="", mpn="", mfr="",
          datasheet=None, nets=None, ref_at=None, val_at=None, in_bom=True, desc=None, fields_vis=True):
    """Place a symbol; nets maps pin number -> net name (for the check)."""
    lib_id = f"{lib}:{name}"
    lib_used[lib_id] = (lib, name)
    flat = flat_symbol(lib, name)
    lp = {}
    for p in find_all(flat, "property"):
        lp[p[1]] = p[2]
    pins = lib_pins(lib, name)
    pos = {}
    for num, (px, py) in pins.items():
        dx, dy = tf(px, py, rot, mirror)
        pos[num] = (R2(x + dx), R2(y + dy))
        if not ref.startswith("#"):
            pin_points.append((pos[num], ref, num))
    value = value if value is not None else lp.get("Value", name)
    ds = datasheet if datasheet is not None else lp.get("Datasheet", "")
    description = desc if desc is not None else lp.get("Description", "")
    # field placement
    horizontal = rot in (90, 270)
    if ref_at is None:
        ref_at = (x + 2.54, y - 1.27, "left") if not horizontal else (x, y - 2.54, "")
    if val_at is None:
        val_at = (x + 2.54, y + 1.27, "left") if not horizontal else (x, y + 2.54, "")
    node = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), R2(x), R2(y), rot]]
    if mirror:
        node.append([Sym("mirror"), Sym(mirror)])
    node += [[Sym("unit"), 1], [Sym("exclude_from_sim"), Sym("no")],
             [Sym("in_bom"), Sym("yes" if in_bom else "no")], [Sym("on_board"), Sym("yes")],
             [Sym("dnp"), Sym("no")], [Sym("uuid"), U()]]
    rj = ref_at[2] if len(ref_at) > 2 else ""
    vj = val_at[2] if len(val_at) > 2 else ""
    hide_ref = ref.startswith("#")
    # KiCad draws field text relative to the symbol orientation, so a symbol
    # turned by 90 degrees needs 90 degree fields to read horizontally
    fa = 90 if rot in (90, 270) else 0
    node.append(prop("Reference", ref, ref_at[0], ref_at[1], hide=hide_ref, justify=rj or None, angle=fa))
    node.append(prop("Value", value, val_at[0], val_at[1], hide=not fields_vis, justify=vj or None, angle=fa))
    node.append(prop("Footprint", footprint, x, y, hide=True))
    node.append(prop("Datasheet", ds, x, y, hide=True))
    node.append(prop("Description", description, x, y, hide=True))
    if mpn:
        node.append(prop("MPN", mpn, x, y, hide=True))
        node.append(prop("Manufacturer", mfr, x, y, hide=True))
    for num in pins:
        node.append([Sym("pin"), num, [Sym("uuid"), U()]])
    node.append([Sym("instances"), [Sym("project"), PROJECT,
                                    [Sym("path"), "/" + ROOT_UUID, [Sym("reference"), ref], [Sym("unit"), 1]]]])
    items.append(node)
    if nets is not None and not ref.startswith("#"):
        intended[ref] = dict(nets)
    if not ref.startswith("#"):
        components.append(dict(ref=ref, value=value, footprint=footprint, mpn=mpn, mfr=mfr))
    return pos


def power(kind, x, y, rot=0):
    """kind: GND, +5V or PWR_FLAG. Returns the pin point."""
    pre = "#FLG" if kind == "PWR_FLAG" else "#PWR"
    pwr_count[pre] += 1
    ref = f"{pre}{pwr_count[pre]:02d}"
    if kind == "GND":
        va = (x, y + 3.81, "")
    elif kind == "+5V":
        va = (x, y - 3.81, "")
    else:
        va = (x, y - 3.81, "")
    if rot == 90:
        va = (x - 5.08, y, "")
    place(ref, "power", kind, x, y, rot=rot, ref_at=(x, y - 6.35, ""), val_at=va)
    return (R2(x), R2(y))


def W(*pts):
    """Polyline of wire segments through the given points."""
    for a, b in zip(pts[:-1], pts[1:]):
        a = (R2(a[0]), R2(a[1]))
        b = (R2(b[0]), R2(b[1]))
        if a == b:
            continue
        assert a[0] == b[0] or a[1] == b[1], f"wire not straight {a} {b}"
        wires.append((a, b))


def label(name, x, y, angle=0):
    labels.append((name, (R2(x), R2(y)), angle))


def noconnect(x, y):
    items.append([Sym("no_connect"), [Sym("at"), R2(x), R2(y)], [Sym("uuid"), U()]])


def text(s, x, y, size=1.27, bold=False, justify="left top"):
    font = [Sym("font"), [Sym("size"), size, size]]
    if bold:
        font += [[Sym("thickness"), round(size * 0.2, 3)], [Sym("bold"), Sym("yes")]]
    items.append([Sym("text"), s, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), R2(x), R2(y), 0],
                  [Sym("effects"), font, [Sym("justify")] + [Sym(j) for j in justify.split()]],
                  [Sym("uuid"), U()]])


def section(title, x1, y1, x2, y2):
    items.append([Sym("rectangle"), [Sym("start"), x1, y1], [Sym("end"), x2, y2],
                  [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("dash")],
                   [Sym("color"), 120, 120, 120, 1]],
                  [Sym("fill"), [Sym("type"), Sym("none")]], [Sym("uuid"), U()]])
    text(title, x1 + 2.54, y1 + 5.08, size=2.0, bold=True, justify="left bottom")


# ================================================================ parts
FP_R = "Resistor_SMD:R_0603_1608Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_POLY = "Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D"
FP_TP = "TestPoint:TestPoint_Keystone_5005-5009_Compact"
MUR, YAG, KEM, TI = "Murata", "Yageo", "KEMET", "Texas Instruments"


def res(ref, x, y, value, mpn, nets, rot=0, **kw):
    return place(ref, "Device", "R", x, y, rot=rot, value=value, footprint=FP_R, mpn=mpn, mfr=YAG,
                 nets=nets, desc=f"Resistor {value}, 0603", **kw)


def cap(ref, x, y, value, fp, mpn, nets, rot=0, polar=False, **kw):
    return place(ref, "Device", "C_Polarized" if polar else "C", x, y, rot=rot, value=value, footprint=fp,
                 mpn=mpn, mfr=KEM if polar else MUR, nets=nets,
                 desc=("Polymer tantalum capacitor " if polar else "Ceramic capacitor ") + value, **kw)


def tp(ref, x, y, net, colour, mpn):
    return place(ref, "Connector", "TestPoint", x, y, value=net, footprint=FP_TP, mpn=mpn,
                 mfr="Keystone Electronics", nets={"1": net}, desc=f"Test point, {colour}",
                 ref_at=(x - 1.27, y - 4.32, "right"), val_at=(x + 1.27, y - 4.32, "left"))


# ---- section frames
section("Input", 15.24, 22.86, 76.2, 96.52)
section("Pass device", 76.2, 22.86, 101.6, 96.52)
section("Output, preload, discharge and Kelvin sense", 101.6, 22.86, 261.62, 96.52)
section("Power flags, test points and mechanical", 266.7, 22.86, 406.4, 96.52)
section("Error amplifier and compensation", 15.24, 104.14, 165.1, 198.12)
section("Reference and soft start", 170.18, 104.14, 292.1, 198.12)
section("Design summary", 297.18, 104.14, 406.4, 151.13)
section("Connectors", 297.18, 156.21, 406.4, 198.12)
text("J1  pin 1 GND, pin 2 VIN (1.5 V to 2.0 V)" + chr(10) +
     "J2  pin 1 VOUT (1.000 V, 0 to 1 A), pin 2 GND" + chr(10) +
     "J3  pin 1 GND, pin 2 EN (open or high = on), pin 3 +5V bias" + chr(10) +
     "All three are Phoenix Contact MKDS 1,5 screw terminals, 5.08 mm pitch.", 299.72, 163.83)
section("Bias input, enable and VIN undervoltage lockout", 15.24, 205.74, 238.76, 278.13)

# ---- input
p = place("J1", "Connector", "Screw_Terminal_01x02", 27.94, 53.34, rot=180, value="VIN 1.5-2.0 V",
          footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
          mpn="1715721", mfr="Phoenix Contact", nets={"1": "GND", "2": "VIN"},
          ref_at=(25.4, 45.72, ""), val_at=(25.4, 59.69, ""), desc="Screw terminal, 2 pole, 5.08 mm")
W(p["2"], (83.82, 50.8))
W(p["1"], (38.1, 53.34), (38.1, 58.42))
power("GND", 38.1, 58.42)
tp("TP1", 43.18, 50.8, "VIN", "red", "5005")
cap("C1", 48.26, 54.61, "330uF 6.3V", FP_POLY, "T520D337M006ATE015", {"1": "VIN", "2": "GND"}, polar=True)
power("GND", 48.26, 58.42)
cap("C2", 63.5, 54.61, "47uF 6.3V", FP_C1206, "GRM31CR60J476ME19L", {"1": "VIN", "2": "GND"})
power("GND", 63.5, 58.42)
label("VIN", 71.12, 50.8)

# ---- pass device
q = place("Q1", "Transistor_FET", "Q_NMOS_GDS", 88.9, 53.34, rot=90, value="IRLR024N",
          footprint="Package_TO_SOT_SMD:TO-252-2", mpn="IRLR024NTRPBF", mfr="Infineon", datasheet="",
          nets={"1": "GATE", "2": "VIN", "3": "VOUT"}, ref_at=(88.9, 41.91, ""), val_at=(88.9, 44.45, ""),
          desc="N-channel logic level MOSFET, 55 V, 65 mohm, DPAK")
W(q["1"], (88.9, 66.04))
label("GATE", 88.9, 66.04)
text("Drain tab on the VIN copper,\nsource lead to the VOUT copper", 78.74, 76.2)

# ---- output
W(q["3"], (233.68, 50.8))
label("VOUT", 101.6, 50.8)
cap("C3", 111.76, 54.61, "330uF 6.3V", FP_POLY, "T520D337M006ATE015", {"1": "VOUT", "2": "GND"}, polar=True)
power("GND", 111.76, 58.42)
for ref, x in (("C4", 127.0), ("C5", 142.24), ("C6", 157.48)):
    cap(ref, x, 54.61, "47uF 6.3V", FP_C1206, "GRM31CR60J476ME19L", {"1": "VOUT", "2": "GND"})
    power("GND", x, 58.42)
res("R1", 172.72, 54.61, "200", "RC0603FR-07200RL", {"1": "VOUT", "2": "GND"})
power("GND", 172.72, 58.42)
r = res("R12", 187.96, 54.61, "22", "RC0603FR-0722RL", {"1": "VOUT", "2": "DCHG"})
qd = place("Q4", "Transistor_FET", "BSS138", 185.42, 68.58, value="BSS138",
           footprint="Package_TO_SOT_SMD:SOT-23", mpn="BSS138", mfr="onsemi",
           nets={"1": "EN_N", "2": "GND", "3": "DCHG"}, ref_at=(191.77, 67.31, "left"),
           val_at=(191.77, 69.85, "left"))
W(r["2"], qd["3"])
label("DCHG", 187.96, 60.96)
W(qd["2"], (187.96, 76.2))
power("GND", 187.96, 76.2)
W(qd["1"], (175.26, 68.58))
label("EN_N", 175.26, 68.58, 180)
text("Preload R1: 5 mA minimum load.\nQ4 and R12 discharge the output when EN is low.", 106.68, 81.28)
cap("C7", 205.74, 54.61, "0.1uF", FP_C0603, "GRM188R71C104KA01D", {"1": "VOUT", "2": "GND"})
power("GND", 205.74, 58.42)
tp("TP2", 213.36, 50.8, "VOUT", "red", "5005")
j2 = place("J2", "Connector", "Screw_Terminal_01x02", 238.76, 50.8, value="VOUT 1.0 V 1 A",
           footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
           mpn="1715721", mfr="Phoenix Contact", nets={"1": "VOUT", "2": "GND"},
           ref_at=(243.84, 49.53, "left"), val_at=(243.84, 52.07, "left"), desc="Screw terminal, 2 pole, 5.08 mm")
nt1 = place("NT1", "Device", "NetTie_2", 223.52, 48.26, rot=90, value="NetTie",
            footprint="NetTie:NetTie-2_SMD_Pad0.5mm", nets={"1": "VOUT", "2": "VOUT_S"},
            ref_at=(227.33, 46.99, ""), val_at=(227.33, 46.99, ""), fields_vis=False,
            in_bom=False, desc="Net tie, Kelvin sense of VOUT at J2")
W(nt1["2"], (223.52, 38.1), (213.36, 38.1))
label("VOUT_S", 213.36, 38.1, 180)
W(j2["2"], (228.6, 53.34), (228.6, 58.42))
power("GND", 228.6, 58.42)
nt2 = place("NT2", "Device", "NetTie_2", 231.14, 55.88, rot=270, value="NetTie",
            footprint="NetTie:NetTie-2_SMD_Pad0.5mm", nets={"1": "GND", "2": "GND_S"},
            ref_at=(234.95, 57.15, ""), val_at=(234.95, 57.15, ""), fields_vis=False,
            in_bom=False, desc="Net tie, Kelvin sense of GND at J2")
W(nt2["2"], (231.14, 66.04), (213.36, 66.04))
label("GND_S", 213.36, 66.04, 180)
text("Kelvin sense: NT1 and NT2 sit on the J2 pads,\nso the feedback divider sees the voltage\nat the load terminals.",
     212.09, 76.2)

# ---- power flags, ground test points, mechanical
W((279.4, 45.72), (287.02, 45.72))
power("PWR_FLAG", 279.4, 45.72)
power("GND", 287.02, 45.72)
W((302.26, 45.72), (312.42, 45.72))
power("PWR_FLAG", 302.26, 45.72)
power("+5V", 312.42, 45.72)
W((327.66, 45.72), (335.28, 45.72))
power("PWR_FLAG", 327.66, 45.72)
label("GND_S", 335.28, 45.72, 0)
for ref, x in (("TP8", 360.68), ("TP9", 375.92)):
    tp(ref, x, 45.72, "GND", "black", "5006")
    W((x, 45.72), (x, 50.8))
    power("GND", x, 50.8)
for i, x in enumerate((289.56, 304.8, 320.04, 335.28), start=1):
    place(f"H{i}", "Mechanical", "MountingHole", x, 71.12, value="M3",
          footprint="MountingHole:MountingHole_3.2mm_M3", in_bom=False, ref_at=(x, 66.04, ""),
          val_at=(x, 76.2, ""), desc="Mounting hole M3, no copper")
for i, x in enumerate((355.6, 370.84, 386.08), start=1):
    place(f"FID{i}", "Mechanical", "Fiducial", x, 71.12, value="Fiducial",
          footprint="Fiducial:Fiducial_1mm_Mask2mm", in_bom=False, ref_at=(x, 66.04, ""),
          val_at=(x, 76.2, ""), desc="Fiducial, 1 mm copper, 2 mm mask opening")
text("Test points: Keystone 5005 red (VIN, VOUT, +5V), 5007 white (GATE, VSET, VREF, EN_INT),\n"
     "5006 black (GND, GND_S).", 271.78, 85.09)

# ---- error amplifier and compensation
u1 = place("U1", "Amplifier_Operational", "OPA365xxDBV", 101.6, 139.7, value="OPA365",
           footprint="Package_TO_SOT_SMD:SOT-23-5", mpn="OPA365AIDBVR", mfr=TI,
           nets={"1": "EAOUT", "2": "GND", "3": "VSET", "4": "FB", "5": "+5V"},
           ref_at=(104.14, 132.08, "left"), val_at=(104.14, 134.62, "left"))
W(u1["5"], (99.06, 127.0))
power("+5V", 99.06, 127.0)
W(u1["2"], (99.06, 152.4))
power("GND", 99.06, 152.4)
W(u1["3"], (88.9, 137.16))
label("VSET", 88.9, 137.16, 180)
W(u1["4"], (81.28, 142.24))
r2 = res("R2", 68.58, 142.24, "2.55k 0.1%", "RT0603BRD072K55L", {"1": "VOUT_S", "2": "FB"}, rot=90,
         ref_at=(68.58, 139.7, ""), val_at=(68.58, 144.78, ""))
W(r2["2"], (81.28, 142.24))
W(r2["1"], (58.42, 142.24))
label("VOUT_S", 58.42, 142.24, 180)
r3 = res("R3", 76.2, 151.13, "10.2k 0.1%", "RT0603BRD0710K2L", {"1": "FB", "2": "GND_S"},
         ref_at=(73.66, 149.86, "right"), val_at=(73.66, 152.4, "right"))
W(r3["1"], (76.2, 142.24))
W(r3["2"], (76.2, 157.48))
label("GND_S", 76.2, 157.48, 270)
W((81.28, 142.24), (81.28, 175.26))
label("FB", 81.28, 158.75, 0)
c9 = cap("C9", 91.44, 165.1, "1nF C0G", FP_C0603, "GRM1885C1H102JA01D", {"1": "FB", "2": "COMP"}, rot=90,
         ref_at=(91.44, 161.29, ""), val_at=(91.44, 168.91, ""))
W((81.28, 165.1), c9["1"])
r4 = res("R4", 109.22, 165.1, "127k", "RC0603FR-07127KL", {"1": "COMP", "2": "EAOUT"}, rot=90,
         ref_at=(109.22, 162.56, ""), val_at=(109.22, 167.64, ""))
W(c9["2"], r4["1"])
label("COMP", 97.79, 165.1)
W(r4["2"], (116.84, 165.1))
c10 = cap("C10", 99.06, 175.26, "3.3pF C0G", FP_C0603, "GRM1885C1H3R3CA01D", {"1": "FB", "2": "EAOUT"},
          rot=90, ref_at=(99.06, 171.45, ""), val_at=(99.06, 179.07, ""))
W((81.28, 175.26), c10["1"])
W(c10["2"], (116.84, 175.26))
W(u1["1"], (116.84, 139.7), (116.84, 175.26))
label("EAOUT", 116.84, 152.4)
r5 = res("R5", 124.46, 139.7, "47", "RC0603FR-0747RL", {"1": "EAOUT", "2": "GATE"}, rot=90,
         ref_at=(124.46, 137.16, ""), val_at=(124.46, 142.24, ""))
W((116.84, 139.7), r5["1"])
W(r5["2"], (144.78, 139.7))
r6 = res("R6", 134.62, 147.32, "100k", "RC0603FR-07100KL", {"1": "GATE", "2": "GND"})
W(r6["1"], (134.62, 139.7))
W(r6["2"], (134.62, 153.67))
power("GND", 134.62, 153.67)
tp("TP3", 139.7, 139.7, "GATE", "white", "5007")
label("GATE", 144.78, 139.7)
c8 = cap("C8", 124.46, 121.92, "0.1uF", FP_C0603, "GRM188R71C104KA01D", {"1": "+5V", "2": "GND"})
W(c8["1"], (124.46, 116.84))
power("+5V", 124.46, 116.84)
W(c8["2"], (124.46, 127.0))
power("GND", 124.46, 127.0)
text("PI compensation: Kp = R4/R2 = 50, zero 1/(2 pi R4 C9) = 1.25 kHz,\n"
     "pole 1/(2 pi R4 C10) = 380 kHz. R5 isolates U1 from about 2 nF of gate\n"
     "capacitance in the model. D1 and R13 (enable block) pull FB up when the regulator is off.", 20.32, 184.15)

# ---- reference and soft start
u2 = place("U2", "Reference_Voltage", "REF3012", 195.58, 142.24, value="REF3012",
           footprint="Package_TO_SOT_SMD:SOT-23", mpn="REF3012AIDBZR", mfr=TI,
           nets={"1": "+5V", "2": "VREF", "3": "GND_S"}, ref_at=(198.12, 133.35, "left"),
           val_at=(198.12, 135.89, "left"), desc="1.25 V voltage reference, 0.2 % initial accuracy, SOT-23-3")
W(u2["1"], (193.04, 125.73))
power("+5V", 193.04, 125.73)
c11 = cap("C11", 182.88, 134.62, "0.1uF", FP_C0603, "GRM188R71C104KA01D", {"1": "+5V", "2": "GND_S"},
          ref_at=(180.34, 133.35, "right"), val_at=(180.34, 135.89, "right"))
W(c11["1"], (182.88, 125.73))
power("+5V", 182.88, 125.73)
W(c11["2"], (182.88, 160.02), (259.08, 160.02))
W(u2["3"], (193.04, 160.02))
label("GND_S", 187.96, 160.02)
W(u2["2"], (219.71, 142.24))
label("VREF", 205.74, 142.24)
tp("TP5", 213.36, 142.24, "VREF", "white", "5007")
r7 = res("R7", 223.52, 142.24, "5.62k 0.1%", "RT0603BRD075K62L", {"1": "VREF", "2": "VSET"}, rot=90,
         ref_at=(223.52, 139.7, ""), val_at=(223.52, 144.78, ""))
W(r7["2"], (279.4, 142.24))
r8 = res("R8", 233.68, 149.86, "10k 0.1%", "RT0603BRD0710KL", {"1": "VSET", "2": "GND_S"},
         ref_at=(231.14, 148.59, "right"), val_at=(231.14, 151.13, "right"))
W(r8["1"], (233.68, 142.24))
W(r8["2"], (233.68, 160.02))
c12 = cap("C12", 243.84, 149.86, "0.47uF", FP_C0603, "GRM188R71C474KA88D", {"1": "VSET", "2": "GND_S"})
W(c12["1"], (243.84, 142.24))
W(c12["2"], (243.84, 160.02))
q3 = place("Q3", "Transistor_FET", "BSS138", 261.62, 147.32, mirror="y", value="BSS138",
           footprint="Package_TO_SOT_SMD:SOT-23", mpn="BSS138", mfr="onsemi",
           nets={"1": "EN_N", "2": "GND_S", "3": "VSET"}, ref_at=(264.16, 153.67, "left"),
           val_at=(264.16, 156.21, "left"))
W(q3["2"], (259.08, 160.02))
W(q3["1"], (271.78, 147.32))
label("EN_N", 271.78, 147.32)
tp("TP4", 269.24, 142.24, "VSET", "white", "5007")
label("VSET", 279.4, 142.24)
tp("TP10", 213.36, 160.02, "GND_S", "black", "5006")
text("VSET = 1.25 V x R8/(R7+R8) = 0.800 V\n"
     "VOUT = VSET x (1 + R2/R3) = 1.000 V\n"
     "Soft start and reference filter: tau = (R7 || R8) x C12 = 1.69 ms\n"
     "Q3 empties C12 while EN_N is high, so every start is a soft start.\n"
     "U2, C11, R3, R8, C12 and Q3 return to GND_S, the quiet ground\n"
     "tied to J2 by NT2.", 175.26, 170.18)

# ---- design summary
text("Input 1.5 V to 2.0 V (nominal 1.8 V), output 1.000 V, 0 to 1 A.\n"
     "The 5 V bias powers U1, U2 and U3 and gives the NMOS follower\n"
     "its gate drive headroom: about 3.2 V on the gate at 1 A and up\n"
     "to 4.98 V near dropout.\n"
     "Q1 dissipates up to 1.0 W at VIN 2.0 V and 1 A.\n"
     "Output capacitors: one 330 uF polymer and three 47 uF X5R.\n"
     "Simulated results and the design math are in README.md.", 299.72, 111.76)

# ---- bias input, enable, UVLO
j3 = place("J3", "Connector", "Screw_Terminal_01x03", 27.94, 236.22, rot=180, value="BIAS 5 V / EN",
           footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal",
           mpn="1715734", mfr="Phoenix Contact", nets={"1": "GND", "2": "EN", "3": "+5V"},
           ref_at=(25.4, 228.6, ""), val_at=(25.4, 245.11, ""), desc="Screw terminal, 3 pole, 5.08 mm")
W(j3["3"], (38.1, 233.68), (38.1, 220.98), (71.12, 220.98))
power("+5V", 71.12, 220.98)
cap("C13", 48.26, 224.79, "10uF 16V", FP_C0805, "GRM21BR61C106KE15L", {"1": "+5V", "2": "GND"})
power("GND", 48.26, 228.6)
tp("TP6", 60.96, 220.98, "+5V", "red", "5005")
W(j3["1"], (38.1, 238.76), (38.1, 243.84))
power("GND", 38.1, 243.84)
r10 = res("R10", 96.52, 236.22, "4.7k", "RC0603FR-074K7L", {"1": "EN", "2": "EN_INT"}, rot=90,
          ref_at=(96.52, 233.68, ""), val_at=(96.52, 238.76, ""))
W(j3["2"], r10["1"])
label("EN", 45.72, 236.22)
W(r10["2"], (149.86, 236.22))
label("EN_INT", 127.0, 236.22)
r9 = res("R9", 119.38, 228.6, "100k", "RC0603FR-07100KL", {"1": "+5V", "2": "EN_INT"},
         ref_at=(116.84, 227.33, "right"), val_at=(116.84, 229.87, "right"))
W(r9["1"], (119.38, 222.25))
power("+5V", 119.38, 222.25)
W(r9["2"], (119.38, 236.22))
tp("TP7", 139.7, 236.22, "EN_INT", "white", "5007")
c14 = cap("C14", 86.36, 222.25, "0.1uF", FP_C0603, "GRM188R71C104KA01D", {"1": "+5V", "2": "GND"})
W(c14["1"], (86.36, 215.9))
power("+5V", 86.36, 215.9)
power("GND", 86.36, 226.06)
u3 = place("U3", "Power_Supervisor", "TPS3808DBV", 109.22, 256.54, value="TPS3808G01",
           footprint="Package_TO_SOT_SMD:SOT-23-6", mpn="TPS3808G01DBVR", mfr=TI,
           nets={"1": "EN_INT", "2": "GND", "3": "+5V", "4": None, "5": "UV_SENSE", "6": "+5V"},
           ref_at=(104.14, 267.97, "right"), val_at=(104.14, 270.51, "right"))
W(u3["6"], (109.22, 243.84))
power("+5V", 109.22, 243.84)
W(u3["2"], (109.22, 266.7))
power("GND", 109.22, 266.7)
W(u3["1"], (124.46, 256.54), (124.46, 236.22))
W(u3["3"], (96.52, 256.54), (96.52, 262.89), (91.44, 262.89))
power("+5V", 91.44, 262.89)
noconnect(*u3["4"])
W(u3["5"], (78.74, 254.0))
label("UV_SENSE", 83.82, 254.0)
r14 = res("R14", 78.74, 247.65, "23.2k", "RC0603FR-0723K2L", {"1": "VIN", "2": "UV_SENSE"},
          ref_at=(76.2, 246.38, "right"), val_at=(76.2, 248.92, "right"))
W(r14["1"], (78.74, 241.3))
label("VIN", 78.74, 241.3)
W(r14["2"], (78.74, 254.0))
r15 = res("R15", 78.74, 260.35, "10k", "RC0603FR-0710KL", {"1": "UV_SENSE", "2": "GND"},
          ref_at=(76.2, 259.08, "right"), val_at=(76.2, 261.62, "right"))
W(r15["1"], (78.74, 254.0))
power("GND", 78.74, 264.16)
q2 = place("Q2", "Transistor_FET", "BSS138", 154.94, 236.22, value="BSS138",
           footprint="Package_TO_SOT_SMD:SOT-23", mpn="BSS138", mfr="onsemi",
           nets={"1": "EN_INT", "2": "GND", "3": "EN_N"}, ref_at=(160.02, 237.49, "left"),
           val_at=(160.02, 240.03, "left"))
W(q2["2"], (157.48, 243.84))
power("GND", 157.48, 243.84)
r11 = res("R11", 157.48, 222.25, "10k", "RC0603FR-0710KL", {"1": "+5V", "2": "EN_N"},
          ref_at=(154.94, 220.98, "right"), val_at=(154.94, 223.52, "right"))
W(r11["1"], (157.48, 215.9))
power("+5V", 157.48, 215.9)
W(r11["2"], q2["3"])
W((157.48, 228.6), (168.91, 228.6))
label("EN_N", 160.02, 228.6)
d1 = place("D1", "Diode", "1N4148W", 172.72, 228.6, rot=180, value="1N4148W",
           footprint="Diode_SMD:D_SOD-123", mpn="1N4148W-7-F", mfr="Diodes Incorporated",
           nets={"1": "INJ", "2": "EN_N"}, ref_at=(172.72, 224.79, ""), val_at=(172.72, 232.41, ""),
           desc="Switching diode, 100 V, 300 mA, SOD-123")
r13 = res("R13", 190.5, 228.6, "100k", "RC0603FR-07100KL", {"1": "INJ", "2": "FB"}, rot=90,
          ref_at=(190.5, 226.06, ""), val_at=(190.5, 231.14, ""))
W(d1["1"], r13["1"])
label("INJ", 179.07, 228.6)
W(r13["2"], (200.66, 228.6))
label("FB", 200.66, 228.6)
text("UVLO: U3 holds EN_INT low until VIN rises past about 1.37 V\n"
     "(trip point 0.405 V x (1 + R14/R15) = 1.345 V plus 1.5 % hysteresis),\n"
     "then waits 20 ms, 12 to 28 ms (CT open). It trips again below 1.345 V.\n"
     "EN low or VIN low: Q2 turns off and EN_N goes high.\n"
     "Q3 empties C12, D1 and R13 pull FB up so U1 drives the\n"
     "gate low, and Q4 discharges VOUT.\n"
     "EN can be left open or pulled low by open drain logic.", 162.56, 248.92)

# ================================================================ wiring
def split_wires():
    pts = set()
    for a, b in wires:
        pts.add(a)
        pts.add(b)
    for p_, _, _ in pin_points:
        pts.add(p_)
    for _, p_, _ in labels:
        pts.add(p_)
    out = []
    for a, b in wires:
        inner = []
        for p_ in pts:
            if p_ in (a, b):
                continue
            if a[0] == b[0] == p_[0] and min(a[1], b[1]) < p_[1] < max(a[1], b[1]):
                inner.append(p_)
            elif a[1] == b[1] == p_[1] and min(a[0], b[0]) < p_[0] < max(a[0], b[0]):
                inner.append(p_)
        seq = sorted([a, b] + inner, key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
        out += list(zip(seq[:-1], seq[1:]))
    return out


def all_power_points():
    pts = []
    for node in items:
        if node[0] == "symbol" and find(node, "lib_id")[1].startswith("power:"):
            at = find(node, "at")
            pts.append((R2(at[1]), R2(at[2])))
    return pts


segs = split_wires()
for a, b in segs:
    items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), a[0], a[1]], [Sym("xy"), b[0], b[1]]],
                  [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], [Sym("uuid"), U()]])
deg = {}
for a, b in segs:
    deg[a] = deg.get(a, 0) + 1
    deg[b] = deg.get(b, 0) + 1
for p_, _, _ in pin_points:
    if p_ in deg:
        deg[p_] += 1
for p_ in all_power_points():
    if p_ in deg:
        deg[p_] += 1
for p_, n in deg.items():
    if n >= 3:
        items.append([Sym("junction"), [Sym("at"), p_[0], p_[1]], [Sym("diameter"), 0],
                      [Sym("color"), 0, 0, 0, 0], [Sym("uuid"), U()]])
for name, p_, angle in labels:
    just = "right bottom" if angle in (180, 270) else "left bottom"
    items.append([Sym("label"), name, [Sym("at"), p_[0], p_[1], angle],
                  [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
                   [Sym("justify")] + [Sym(j) for j in just.split()]], [Sym("uuid"), U()]])

# ================================================================ write
lib_syms = [flat_symbol(lib, name) for lib_id, (lib, name) in sorted(lib_used.items())]
doc = [Sym("kicad_sch"), [Sym("version"), 20260306], [Sym("generator"), "eeschema"],
       [Sym("generator_version"), "10.0"], [Sym("uuid"), ROOT_UUID], [Sym("paper"), "A3"],
       [Sym("title_block"), [Sym("title"), "NMOS LDO board, 1.0 V at 1 A"], [Sym("date"), "2026-10-24"],
        [Sym("rev"), "A"], [Sym("company"), "Siyun Chen"],
        [Sym("comment"), 1, "Discrete NMOS low dropout regulator for a low voltage core rail"],
        [Sym("comment"), 2, "VIN 1.5-2.0 V, VOUT 1.000 V, 0-1 A, 5 V bias, Kelvin sense at J2"]],
       [Sym("lib_symbols")] + lib_syms] + items + [
    [Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]],
    [Sym("embedded_fonts"), Sym("no")]]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write(dump(doc) + "\n")
with open(os.path.join(ROOT, "hardware", "intended_nets.json"), "w") as f:
    json.dump(intended, f, indent=1, sort_keys=True)
print(f"wrote {OUT}: {len(components)} parts, {len(segs)} wire segments")

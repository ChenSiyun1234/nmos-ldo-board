"""Build hardware/nmos-ldo-board.kicad_pcb with KiCad's pcbnew Python module.

Run with the Python that ships with KiCad, after the netlist has been exported:
    kicad-cli sch export netlist --format kicadsexpr -o hardware/nmos-ldo-board.net hardware/nmos-ldo-board.kicad_sch
    <KiCad python> scripts/build_pcb.py
Set KICAD_FOOTPRINT_DIR if the KiCad footprint libraries are not found.
"""
import glob
import json
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sexpr import find, find_all, parse  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
HW = os.path.join(ROOT, "hardware")
NETLIST = os.path.join(HW, "nmos-ldo-board.net")
PCB = os.path.join(HW, "nmos-ldo-board.kicad_pcb")

X0, Y0 = 100.0, 100.0          # board top left corner
W, H = 54.0, 42.0              # board size, mm
CORNER_R = 1.0


def fp_dir():
    env = os.environ.get("KICAD_FOOTPRINT_DIR")
    cands = [env] if env else []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), "/usr/share/kicad",
                 "/Applications/KiCad/KiCad.app/Contents/SharedSupport"):
        cands += sorted(glob.glob(os.path.join(base, "KiCad", "*", "share", "kicad", "footprints")),
                        reverse=True)
        cands.append(os.path.join(base, "footprints"))
    for c in cands:
        if c and os.path.isdir(c):
            return c
    raise SystemExit("KiCad footprint libraries not found; set KICAD_FOOTPRINT_DIR")


FPDIR = fp_dir()


def mm(v):
    return pcbnew.FromMM(v)


def P(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


# ------------------------------------------------------------------ placement
# ref: (x, y, rotation in degrees, side) ; positions are footprint origins
PLACE = {
    # mounting holes and fiducials
    "H1": (104.0, 104.0, 0, "F"), "H2": (150.0, 104.0, 0, "F"),
    "H3": (104.0, 138.0, 0, "F"), "H4": (150.0, 138.0, 0, "F"),
    "FID1": (110.2, 101.8, 0, "F"), "FID2": (144.2, 101.8, 0, "F"), "FID3": (147.2, 129.0, 0, "F"),
    # power path: J1 -> C1, C2 -> Q1 -> C3..C6 -> J2 (Kelvin net ties on the bottom side)
    "J1": (105.54, 110.92, 270, "F"),
    "C1": (113.8, 112.9, 90, "F"),
    "C2": (117.5, 110.6, 90, "F"),
    "Q1": (123.5, 115.6, 180, "F"),
    "C3": (132.6, 112.9, 90, "F"),
    "C4": (136.25, 114.525, 90, "F"), "C5": (138.85, 114.525, 90, "F"), "C6": (141.45, 114.525, 90, "F"),
    "J2": (148.46, 116.0, 90, "F"),
    "NT1": (145.5, 116.0, 180, "B"), "NT2": (145.5, 110.92, 180, "B"),
    # test points
    "TP8": (114.2, 104.2, 0, "F"), "TP9": (140.2, 104.2, 0, "F"),
    "TP1": (113.4, 119.7, 0, "F"), "TP2": (147.0, 123.0, 0, "F"),
    "TP3": (125.4, 124.6, 0, "F"),
    "TP4": (152.0, 125.2, 0, "F"), "TP10": (152.0, 131.6, 0, "F"), "TP5": (132.8, 139.8, 0, "F"),
    "TP6": (128.6, 137.4, 0, "F"), "TP7": (102.6, 131.4, 0, "F"),
    # bias input, enable and UVLO
    "J3": (111.84, 136.46, 0, "F"),
    "C13": (126.2, 132.6, 90, "F"),
    "Q2": (103.0, 124.2, 180, "F"), "R11": (102.0, 127.8, 90, "F"),
    "R10": (105.4, 127.6, 90, "F"), "R9": (107.4, 127.6, 90, "F"),
    "U3": (110.4, 125.6, 0, "F"), "C14": (113.3, 123.3, 270, "F"),
    "R14": (115.4, 123.4, 270, "F"), "R15": (115.4, 127.4, 270, "F"),
    # error amplifier and compensation
    "U1": (132.0, 125.6, 0, "F"),
    "R5": (129.6, 121.6, 90, "F"), "R6": (127.0, 120.8, 180, "F"), "C8": (134.8, 122.8, 0, "F"),
    "R3": (136.4, 126.55, 0, "F"), "R2": (136.4, 128.2, 180, "F"),
    "C9": (133.3, 129.0, 180, "F"), "R4": (130.0, 129.0, 180, "F"), "C10": (131.6, 130.8, 180, "F"),
    "R13": (134.7, 130.8, 180, "F"), "D1": (138.7, 130.8, 0, "F"),
    # output extras: preload, discharge, connector decoupling
    "R1": (136.6, 120.4, 270, "F"), "R12": (141.2, 120.6, 270, "F"), "Q4": (141.2, 124.2, 90, "F"),
    "C7": (143.8, 121.0, 270, "F"),
    # reference and soft start (quiet GND_S area)
    "Q3": (143.2, 133.2, 0, "F"), "U2": (138.4, 136.6, 0, "F"), "C11": (135.4, 136.2, 90, "F"),
    "R7": (142.0, 138.4, 0, "F"), "R8": (145.0, 136.6, 90, "F"), "C12": (145.0, 140.0, 270, "F"),
}


def load_netlist():
    with open(NETLIST, encoding="utf-8") as f:
        tree = parse(f.read())[0]
    comps = {}
    for comp in find_all(find(tree, "components"), "comp"):
        ref = find(comp, "ref")[1]
        fields = {}
        fl = find(comp, "fields")
        if fl:
            for fld in find_all(fl, "field"):
                fields[find(fld, "name")[1]] = fld[2] if len(fld) > 2 else ""
        comps[ref] = dict(value=find(comp, "value")[1], footprint=find(comp, "footprint")[1],
                          tstamp=find(comp, "tstamps")[1], fields=fields)
    nets = {}
    for net in find_all(find(tree, "nets"), "net"):
        name = find(net, "name")[1]
        nets[name] = [(find(n, "ref")[1], find(n, "pin")[1]) for n in find_all(net, "node")]
    return comps, nets


def add_outline(board):
    """Rectangle with rounded corners on Edge.Cuts."""
    r = CORNER_R
    x1, y1, x2, y2 = X0, Y0, X0 + W, Y0 + H
    segs = [((x1 + r, y1), (x2 - r, y1)), ((x2, y1 + r), (x2, y2 - r)),
            ((x2 - r, y2), (x1 + r, y2)), ((x1, y2 - r), (x1, y1 + r))]
    for a, b in segs:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a))
        s.SetEnd(P(*b))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)
    k = r * (1 - math.sqrt(0.5))
    corners = (((x1, y1 + r), (x1 + k, y1 + k), (x1 + r, y1)),
               ((x2 - r, y1), (x2 - k, y1 + k), (x2, y1 + r)),
               ((x2, y2 - r), (x2 - k, y2 - k), (x2 - r, y2)),
               ((x1 + r, y2), (x1 + k, y2 - k), (x1, y2 - r)))
    for st, mid, en in corners:
        a = pcbnew.PCB_SHAPE(board)
        a.SetShape(pcbnew.SHAPE_T_ARC)
        a.SetArcGeometry(P(*st), P(*mid), P(*en))
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetWidth(mm(0.1))
        board.Add(a)


def place_footprints(board, comps, nets):
    netinfo = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pin_net = {}
    for name, nodes in nets.items():
        for ref, pin in nodes:
            pin_net[(ref, pin)] = name
    fps = {}
    for ref, c in sorted(comps.items()):
        lib, name = c["footprint"].split(":", 1)
        fp = pcbnew.FootprintLoad(os.path.join(FPDIR, lib + ".pretty"), name)
        if fp is None:
            raise SystemExit(f"footprint {c['footprint']} not found")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["tstamp"]))
        fp.SetSheetname("Root")
        fp.SetSheetfile("nmos-ldo-board.kicad_sch")
        ds = c["fields"].get("Datasheet", "")
        if ds and ds != "~":
            fp.GetField("Datasheet").SetText(ds) if fp.GetField("Datasheet") else fp.SetField("Datasheet", ds)
        for k in ("MPN", "Manufacturer", "Description"):
            v = c["fields"].get(k)
            if v:
                fp.SetField(k, v)
                fld = fp.GetField(k)
                if fld is not None:
                    fld.SetVisible(False)
                    fld.SetLayer(pcbnew.F_Fab)
        board.Add(fp)
        x, y, rot, side = PLACE[ref]
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(P(x, y))
        for pad in fp.Pads():
            num = pad.GetNumber()
            if not num:
                continue
            net = pin_net.get((ref, num))
            if net:
                pad.SetNet(netinfo[net])
        fps[ref] = fp
    return fps, netinfo


def dump_geometry(board, path):
    out = {"board": [X0, Y0, W, H], "fps": {}}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        layer = pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_CrtYd
        cy = fp.GetCourtyard(layer)
        bb = None
        if cy.OutlineCount():
            b = cy.BBox()
            bb = [b.GetX() / 1e6, b.GetY() / 1e6, b.GetWidth() / 1e6, b.GetHeight() / 1e6]
        pads = []
        for p in fp.Pads():
            if not p.GetNumber():
                continue
            bbp = p.GetBoundingBox()
            pads.append(dict(num=p.GetNumber(), net=p.GetNetname(), x=p.GetPosition().x / 1e6,
                             y=p.GetPosition().y / 1e6, bb=[bbp.GetX() / 1e6, bbp.GetY() / 1e6,
                                                          bbp.GetWidth() / 1e6, bbp.GetHeight() / 1e6]))
        out["fps"][ref] = dict(courtyard=bb, pads=pads, side="B" if fp.GetLayer() == pcbnew.B_Cu else "F",
                               value=fp.GetValue())
    with open(path, "w") as f:
        json.dump(out, f, indent=1)


def courtyard_overlaps(board):
    """List pairs of footprints on the same side whose courtyards overlap."""
    items = []
    for fp in board.GetFootprints():
        side = pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_CrtYd
        cy = fp.GetCourtyard(side)
        if cy.OutlineCount():
            items.append((fp.GetReference(), side, cy))
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, sa, ca = items[i]
            b, sb, cb = items[j]
            if sa != sb:
                continue
            inter = ca.CloneDropTriangulation()
            inter.BooleanIntersection(cb)
            if inter.OutlineCount() and inter.Area() > 1:
                out.append((a, b, inter.Area() / 1e12))
    return out


def main():
    comps, nets = load_netlist()
    missing = sorted(set(comps) - set(PLACE))
    if missing:
        raise SystemExit(f"no placement for {missing}")
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    tb = board.GetTitleBlock()
    tb.SetTitle("NMOS LDO board, 1.0 V at 1 A")
    tb.SetDate("2026-10-24")
    tb.SetRevision("A")
    tb.SetCompany("Siyun Chen")
    add_outline(board)
    fps, netinfo = place_footprints(board, comps, nets)
    dump_geometry(board, os.path.join(HW, "placement_geometry.json"))
    for a, b, area in courtyard_overlaps(board):
        print(f"COURTYARD OVERLAP {a} {b} {area:.3f} mm2")
    if "--place-only" in sys.argv:
        board.Save(PCB)
        print("placement saved")
        return
    import route  # noqa: F401  (routing, zones, silkscreen; see route.py)
    route.apply(board, fps, netinfo)
    board.Save(PCB)
    add_stackup(PCB)
    print("board saved (fill zones with: kicad-cli pcb drc --refill-zones --save-board)", PCB)


STACKUP = """		(stackup
			(layer "F.SilkS" (type "Top Silk Screen") (color "White"))
			(layer "F.Paste" (type "Top Solder Paste"))
			(layer "F.Mask" (type "Top Solder Mask") (color "Green") (thickness 0.01))
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "prepreg") (thickness 0.2104) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
			(layer "In1.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 2" (type "core") (thickness 1.02) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
			(layer "In2.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 3" (type "prepreg") (thickness 0.2104) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
			(layer "B.Cu" (type "copper") (thickness 0.035))
			(layer "B.Mask" (type "Bottom Solder Mask") (color "Green") (thickness 0.01))
			(layer "B.Paste" (type "Bottom Solder Paste"))
			(layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))
			(copper_finish "ENIG")
			(dielectric_constraints no)
		)
"""


def add_stackup(path):
    """4 layer, 1.6 mm, 1 oz copper on every layer; inner layers marked as planes."""
    tab, nl = chr(9), chr(10)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if "(stackup" not in text:
        text = text.replace(tab + "(setup" + nl, tab + "(setup" + nl + STACKUP, 1)
    text = text.replace('(4 "In1.Cu" signal)', '(4 "In1.Cu" power)')
    text = text.replace('(6 "In2.Cu" signal)', '(6 "In2.Cu" power)')
    with open(path, "w", encoding="utf-8", newline=nl) as f:
        f.write(text)


if __name__ == "__main__":
    main()

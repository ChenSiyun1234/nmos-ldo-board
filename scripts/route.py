"""Copper for the NMOS LDO board: tracks, vias, zones, keepouts and silkscreen.

Coordinates are in mm on the board (top left corner of the outline at 100, 100).
Layer plan:
  F.Cu   VIN and VOUT power pours, quiet GND_S pour under the reference,
         local signal routing, GND fill
  In1.Cu solid GND plane
  In2.Cu solid GND plane
  B.Cu   VIN copper under Q1 for heat spreading (tied to the tab by thermal
         vias), the Kelvin sense pair, the EN_N trunk, two +5V jumpers, GND fill
"""
import pcbnew

F, B = pcbnew.F_Cu, pcbnew.B_Cu
IN1, IN2 = pcbnew.In1_Cu, pcbnew.In2_Cu
X0, Y0, W, H = 100.0, 100.0, 54.0, 42.0


def mm(v):
    return pcbnew.FromMM(v)


def P(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class Copper:
    def __init__(self, board, netinfo):
        self.b = board
        self.nets = netinfo

    def net(self, name):
        return self.nets[name]

    def track(self, net, layer, width, pts):
        for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
            if (x1, y1) == (x2, y2):
                continue
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(P(x1, y1))
            t.SetEnd(P(x2, y2))
            t.SetWidth(mm(width))
            t.SetLayer(layer)
            t.SetNet(self.net(net))
            self.b.Add(t)

    def via(self, net, x, y, drill=0.3, size=0.6, tent=True):
        v = pcbnew.PCB_VIA(self.b)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(F, B)
        v.SetPosition(P(x, y))
        v.SetDrill(mm(drill))
        v.SetWidth(mm(size))
        v.SetNet(self.net(net))
        if tent:
            try:
                v.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
                v.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
            except AttributeError:
                pass
        self.b.Add(v)

    def zone(self, net, layer, pts, priority=0, clearance=0.25, min_width=0.25,
             thermal_gap=0.3, spoke=0.4, connection=None, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(net))
        # build the outline inside the zone's own polygon: SetOutline() would
        # take ownership of a Python-owned object and crash later
        outline = z.Outline()
        outline.NewOutline()
        for x, y in pts:
            outline.Append(mm(x), mm(y))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_width))
        z.SetThermalReliefGap(mm(thermal_gap))
        z.SetThermalReliefSpokeWidth(mm(spoke))
        z.SetPadConnection(connection if connection is not None else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if name:
            z.SetZoneName(name)
        self.b.Add(z)
        return z

    def keepout(self, layers, pts, tracks=False, vias=False, pour=True, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        outline = z.Outline()
        outline.NewOutline()
        for x, y in pts:
            outline.Append(mm(x), mm(y))
        z.SetDoNotAllowZoneFills(pour)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        if name:
            z.SetZoneName(name)
        self.b.Add(z)

    def text(self, s, x, y, size=1.0, layer=pcbnew.F_SilkS, bold=False, angle=0, just="center"):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetLayer(layer)
        t.SetPosition(P(x, y))
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(max(0.12, size * (0.2 if bold else 0.15))))
        if angle:
            t.SetTextAngleDegrees(angle)
        if just == "left":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        elif just == "right":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT)
        if layer in (pcbnew.B_SilkS, pcbnew.B_Cu):
            t.SetMirrored(True)
        self.b.Add(t)


def circle_pts(cx, cy, r, n=24):
    import math
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def routes(c):
    S, PWR = 0.25, 0.4
    # ------------------------------------------------------------ gate drive
    c.track("/GATE", F, 0.3, [(128.54, 117.88), (128.54, 120.0)])
    c.track("/GATE", F, 0.3, [(128.54, 120.0), (129.3, 120.76), (129.6, 120.775)])
    c.track("/GATE", F, 0.3, [(128.54, 120.0), (127.825, 120.715), (127.825, 120.8)])
    c.track("/GATE", F, 0.3, [(127.825, 120.8), (127.825, 122.2), (126.0, 124.0), (125.4, 124.6)])
    # error amplifier output: up to R5, down to R4 and C10 through the bottom layer
    c.track("/EAOUT", F, S, [(130.863, 124.65), (129.6, 123.387), (129.6, 122.425)])
    c.track("/EAOUT", F, S, [(130.863, 124.65), (128.8, 124.65)])
    c.via("/EAOUT", 128.8, 124.65)
    c.track("/EAOUT", B, S, [(128.8, 124.65), (128.8, 128.4)])
    c.via("/EAOUT", 128.8, 128.4)
    c.track("/EAOUT", F, S, [(128.8, 128.4), (129.175, 128.775), (129.175, 129.0)])
    c.track("/EAOUT", F, S, [(129.175, 129.0), (129.175, 129.9), (130.075, 130.8), (130.825, 130.8)])
    c.track("/COMP", F, S, [(132.525, 129.0), (130.825, 129.0)])
    # feedback node
    c.track("/FB", F, S, [(133.137, 126.55), (135.575, 126.55)])
    c.track("/FB", F, S, [(135.575, 126.55), (135.575, 128.2)])
    c.track("/FB", F, S, [(135.575, 128.2), (134.775, 129.0), (134.075, 129.0)])
    c.track("/FB", F, S, [(134.075, 129.0), (134.075, 130.8)])
    c.track("/FB", F, S, [(132.375, 130.8), (133.875, 130.8)])
    c.track("/INJ", F, S, [(135.525, 130.8), (137.05, 130.8)])
    # ------------------------------------------------------------ Kelvin sense
    c.track("/VOUT", B, 0.3, [(148.46, 116.0), (146.0, 116.0)])
    c.track("GND", B, 0.3, [(148.46, 110.92), (146.0, 110.92)])
    c.track("/VOUT_S", B, S, [(145.0, 116.0), (145.0, 120.25), (138.2, 127.05), (138.2, 128.2)])
    c.via("/VOUT_S", 138.2, 128.2)
    c.track("/VOUT_S", F, S, [(138.2, 128.2), (137.225, 128.2)])
    c.track("/GND_S", B, S, [(145.0, 110.92), (144.4, 111.52), (144.4, 120.0), (139.6, 124.8), (138.9, 124.8)])
    c.via("/GND_S", 138.9, 124.8)
    c.track("/GND_S", F, S, [(138.9, 124.8), (137.225, 126.475), (137.225, 126.55)])
    c.track("/GND_S", B, S, [(138.9, 124.8), (137.0, 124.8), (137.0, 133.6)])
    c.via("/GND_S", 137.0, 133.6)
    c.track("/GND_S", B, S, [(137.0, 133.6), (149.2, 133.6), (150.8, 132.0), (152.0, 131.6)])
    # ------------------------------------------------------------ enable logic
    c.track("/EN_N", F, S, [(102.062, 124.2), (102.0, 124.262), (102.0, 126.975)])
    c.track("/EN_N", F, S, [(102.062, 124.2), (102.0, 124.138), (102.0, 123.0)])
    c.via("/EN_N", 102.0, 123.0)
    c.track("/EN_N", B, S, [(102.0, 123.0), (103.0, 122.0), (139.9, 122.0)])
    c.via("/EN_N", 139.9, 122.0)
    c.track("/EN_N", F, S, [(139.9, 122.0), (139.9, 124.0), (140.25, 124.35), (140.25, 125.138)])
    c.track("/EN_N", F, S, [(140.25, 125.138), (140.25, 130.6), (140.35, 130.7), (140.35, 130.8)])
    c.track("/EN_N", F, S, [(140.35, 130.8), (141.8, 132.25), (142.262, 132.25)])
    c.track("/DCHG", F, PWR, [(141.2, 121.425), (141.2, 123.263)])
    c.track("/EN_INT", F, S, [(109.263, 124.65), (108.0, 124.65), (107.4, 125.25), (107.4, 126.775)])
    c.track("/EN_INT", F, S, [(105.4, 126.775), (107.4, 126.775)])
    c.track("/EN_INT", F, S, [(103.938, 125.15), (104.7, 125.15), (105.4, 125.85), (105.4, 126.775)])
    c.track("/EN_INT", F, S, [(104.7, 125.15), (104.2, 125.65), (104.2, 130.0), (102.8, 131.4), (102.6, 131.4)])
    c.track("/EN", F, S, [(116.92, 136.46), (116.92, 131.8), (105.4, 131.8), (105.4, 128.425)])
    c.track("/UV_SENSE", F, S, [(111.537, 125.6), (115.4, 125.6)])
    c.track("/UV_SENSE", F, S, [(115.4, 124.225), (115.4, 126.575)])
    c.track("/VIN", F, S, [(115.4, 122.575), (115.4, 121.5)])
    # ------------------------------------------------------------ +5V
    c.track("+5V", F, PWR, [(122.0, 136.46), (122.0, 134.3), (134.2, 134.3), (134.2, 136.975), (135.4, 136.975)])
    c.track("+5V", F, PWR, [(135.4, 136.975), (136.3, 136.975), (136.3, 135.65), (137.463, 135.65)])
    c.track("+5V", F, PWR, [(126.2, 134.3), (126.2, 133.55)])
    c.track("+5V", F, PWR, [(128.6, 134.3), (128.6, 137.4)])
    c.track("+5V", F, PWR, [(122.0, 134.3), (122.0, 130.4), (106.5, 130.4)])
    c.track("+5V", F, PWR, [(107.4, 130.4), (107.4, 128.425)])
    c.track("+5V", F, S, [(109.263, 126.55), (108.6, 127.213), (108.6, 130.4)])
    c.track("+5V", F, S, [(102.0, 128.625), (102.0, 129.4)])
    c.via("+5V", 102.0, 129.4)
    c.track("+5V", B, S, [(102.0, 129.4), (106.5, 129.4)])
    c.via("+5V", 106.5, 129.4)
    c.track("+5V", F, S, [(106.5, 129.4), (106.5, 130.4)])
    c.track("+5V", F, S, [(111.537, 124.65), (112.1, 124.087), (112.1, 122.525), (113.3, 122.525)])
    c.via("+5V", 112.1, 123.3)
    # drops onto the +5V bus left of J3 pin 1, so the GND pin name above J3 stays clear
    c.track("+5V", B, S, [(112.1, 123.3), (112.1, 128.3), (110.0, 130.4), (108.6, 130.4)])
    c.via("+5V", 108.6, 130.4)
    c.via("+5V", 133.4, 134.3)
    c.track("+5V", B, S, [(133.4, 134.3), (133.4, 123.5)])
    c.via("+5V", 133.4, 123.5)
    c.track("+5V", F, S, [(133.4, 123.5), (134.025, 123.5), (134.025, 122.8)])
    c.track("+5V", F, S, [(133.4, 123.5), (133.137, 123.763), (133.137, 124.65)])
    # ------------------------------------------------------------ reference
    c.track("/VSET", F, S, [(130.863, 126.55), (127.8, 126.55), (127.8, 132.4), (139.6, 132.4),
                            (140.4, 133.2), (144.137, 133.2)])
    c.track("/VSET", F, S, [(144.137, 133.2), (145.9, 133.2), (145.9, 137.425), (145.0, 137.425)])
    c.track("/VSET", F, S, [(145.0, 137.425), (145.0, 139.225)])
    c.track("/VSET", F, S, [(142.825, 138.4), (144.2, 138.4), (145.0, 139.2)])
    c.track("/VSET", F, S, [(145.9, 133.2), (148.6, 130.5), (148.6, 126.6), (150.0, 125.2), (152.0, 125.2)])
    c.track("/VREF", F, S, [(137.463, 137.55), (137.463, 138.4), (141.175, 138.4)])
    c.track("/VREF", F, S, [(137.463, 138.4), (134.6, 138.4), (133.2, 139.8), (132.8, 139.8)])
    # ------------------------------------------------------------ GND vias
    gnd_vias = [
        # input capacitors and J1
        (113.0, 107.9), (114.6, 107.9), (117.5, 108.0), (108.6, 109.4), (108.6, 112.4),
        # output capacitors and J2
        (131.8, 107.9), (133.4, 107.9), (136.25, 111.9), (138.85, 111.9), (141.45, 111.9), (144.0, 108.6),
        # control parts
        (105.0, 123.25), (110.4, 123.4), (114.3, 124.2), (115.4, 129.1), (129.9, 125.6), (125.5, 120.1),
        (136.4, 122.9), (135.7, 121.2), (143.0, 125.8), (144.9, 121.775), (125.2, 131.65),
        # stitching along the top strip and the edges, kept clear of the board title
        (118.6, 102.0), (132.2, 102.0), (135.6, 102.0), (130.5, 104.6), (133.9, 104.6),
        (129.4, 107.6), (136.8, 107.6),
        (107.6, 122.8), (101.4, 109.0), (152.6, 113.6), (152.6, 118.6), (120.0, 140.9), (124.4, 140.4),
        (130.6, 135.6), (147.6, 140.9), (118.6, 128.0), (120.6, 126.0), (124.2, 128.4),
    ]
    for x, y in gnd_vias:
        c.via("GND", x, y)
    c.track("GND", F, PWR, [(113.0, 107.9), (113.8, 108.7), (113.8, 109.78)])
    c.track("GND", F, PWR, [(114.6, 107.9), (113.8, 108.7)])
    c.track("GND", F, PWR, [(117.5, 108.0), (117.5, 109.125)])
    c.track("GND", F, S, [(103.938, 123.25), (105.0, 123.25)])
    c.track("GND", F, S, [(109.263, 125.6), (110.4, 125.6), (110.4, 123.4)])
    c.track("GND", F, S, [(113.3, 124.075), (113.425, 124.2), (114.3, 124.2)])
    c.track("GND", F, S, [(115.4, 128.225), (115.4, 129.1)])
    c.track("GND", F, S, [(130.863, 125.6), (129.9, 125.6)])
    c.track("GND", F, S, [(126.175, 120.8), (125.5, 120.125), (125.5, 120.1)])
    c.track("GND", F, S, [(135.575, 122.8), (136.3, 122.8), (136.4, 122.9)])
    c.track("GND", F, S, [(136.6, 121.225), (135.7, 121.225), (135.7, 121.2)])
    c.track("GND", F, S, [(142.15, 125.138), (142.15, 125.6), (142.35, 125.8), (143.0, 125.8)])
    c.track("GND", F, S, [(143.8, 121.775), (144.9, 121.775)])
    c.track("GND", F, S, [(126.2, 131.65), (125.2, 131.65)])
    # ------------------------------------------------------------ Q1 thermal vias (VIN)
    for x in (119.84, 121.04, 122.24, 123.44, 124.64):
        for y in (113.45, 114.6, 115.75, 116.9, 118.05):
            c.via("/VIN", x, y)
    for x in (119.6, 121.2, 122.8, 124.4, 126.0):
        c.via("/VIN", x, 111.7)
    for x, y in ((110.0, 118.2), (111.2, 115.0), (116.6, 116.9), (116.6, 118.6), (110.0, 120.9), (104.6, 121.2)):
        c.via("/VIN", x, y)
    # VOUT stitching to share current with the bottom layer is not used; the
    # bottom layer under the output stays GND for the sense pair


def zones(c):
    edge = [(X0 + 0.3, Y0 + 0.3), (X0 + W - 0.3, Y0 + 0.3), (X0 + W - 0.3, Y0 + H - 0.3), (X0 + 0.3, Y0 + H - 0.3)]
    # inner ground planes
    c.zone("GND", IN1, edge, priority=0, name="GND plane 1")
    c.zone("GND", IN2, edge, priority=0, name="GND plane 2")
    # top layer: power pours over a GND fill
    c.zone("GND", F, edge, priority=0, name="GND top fill")
    vin_f = [(101.2, 113.5), (115.9, 113.5), (115.9, 111.1), (126.5, 111.1), (126.5, 119.4), (116.6, 119.4),
             (116.6, 121.9), (101.2, 121.9)]
    c.zone("/VIN", F, vin_f, priority=3, clearance=0.3, connection=pcbnew.ZONE_CONNECTION_FULL, name="VIN top")
    vout_f = [(127.0, 112.3), (130.3, 112.3), (130.3, 114.4), (150.6, 114.4), (150.6, 117.7), (148.9, 117.7),
              (148.9, 124.8), (145.3, 124.8), (145.3, 120.45), (130.6, 120.45), (130.6, 115.4), (127.0, 115.4)]
    c.zone("/VOUT", F, vout_f, priority=3, clearance=0.3, connection=pcbnew.ZONE_CONNECTION_FULL, name="VOUT top")
    gnds = [(134.5, 132.9), (146.3, 132.9), (146.3, 141.4), (134.5, 141.4)]
    c.zone("/GND_S", F, gnds, priority=4, clearance=0.25, connection=pcbnew.ZONE_CONNECTION_FULL,
           name="GND_S quiet ground")
    # bottom layer: VIN heat spreader under Q1, GND everywhere else
    c.zone("GND", B, edge, priority=0, name="GND bottom fill")
    vin_b = [(101.2, 106.8), (127.4, 106.8), (127.4, 121.4), (101.2, 121.4)]
    c.zone("/VIN", B, vin_b, priority=3, clearance=0.3, connection=pcbnew.ZONE_CONNECTION_FULL, name="VIN bottom")
    # keepouts: mounting holes (all copper), and no pour around the Kelvin stubs
    allcu = [F, IN1, IN2, B]
    for hx, hy in ((104.0, 104.0), (150.0, 104.0), (104.0, 138.0), (150.0, 138.0)):
        c.keepout(allcu, circle_pts(hx, hy, 3.3), tracks=True, vias=True, pour=True, name="mounting hole")
    c.keepout([B], [(143.9, 108.2), (151.0, 108.2), (151.0, 117.6), (143.9, 117.6)], pour=True, name="Kelvin stubs")


BOARD_BOX = (X0 + 0.35, Y0 + 0.35, X0 + W - 0.35, Y0 + H - 0.35)


def _box(item, grow=0.0):
    b = item.GetBoundingBox()
    return (b.GetX() / 1e6 - grow, b.GetY() / 1e6 - grow,
            (b.GetX() + b.GetWidth()) / 1e6 + grow, (b.GetY() + b.GetHeight()) / 1e6 + grow)


def _stroke_box(text, grow=0.0):
    b = text.GetEffectiveTextShape().BBox()
    return (b.GetX() / 1e6 - grow, b.GetY() / 1e6 - grow,
            (b.GetX() + b.GetWidth()) / 1e6 + grow, (b.GetY() + b.GetHeight()) / 1e6 + grow)


def _hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class SilkPlacer:
    """Places silkscreen text where it clears pads, other silk and the edge."""

    def __init__(self, board, side=pcbnew.F_SilkS):
        self.board = board
        self.side = side
        cu = pcbnew.F_Cu if side == pcbnew.F_SilkS else pcbnew.B_Cu
        self.obst = []
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.IsOnLayer(cu):
                    self.obst.append(_box(pad, 0.15))
            for g in fp.GraphicalItems():
                if g.GetLayer() == side and g.GetClass() != "PCB_TEXT":
                    self.obst.append(_box(g, 0.1))
            if fp.GetReference().startswith("H"):
                # keep silk out from under an M3 screw head and washer
                hx, hy = fp.GetPosition().x / 1e6, fp.GetPosition().y / 1e6
                self.obst.append((hx - 2.9, hy - 2.9, hx + 2.9, hy + 2.9))
        # vias are tented, but their drill would still cut through printed text
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                self.obst.append(_box(t, 0.15))
        self.placed = []

    def free(self, box):
        if box[0] < BOARD_BOX[0] or box[1] < BOARD_BOX[1] or box[2] > BOARD_BOX[2] or box[3] > BOARD_BOX[3]:
            return False
        return not any(_hit(box, o) for o in self.obst + self.placed)

    def place(self, item, anchor, sides=("top", "bottom", "left", "right"), angles=(0, 90), gap=0.15,
              shifts=(0.0, -0.8, 0.8, -1.6, 1.6), tight=False):
        """tight=True measures the text by its strokes instead of KiCad's text box,
        used only as a last try for a crowded reference."""
        box = _stroke_box if tight else _box
        for ang in angles:
            item.SetTextAngleDegrees(ang)
            for side in sides:
                for sh in shifts:
                    item.SetPosition(P(0, 0))
                    bb = box(item)
                    w, h = bb[2] - bb[0], bb[3] - bb[1]
                    cx, cy = (anchor[0] + anchor[2]) / 2, (anchor[1] + anchor[3]) / 2
                    if side == "top":
                        x, y = cx + sh, anchor[1] - gap - h / 2
                    elif side == "bottom":
                        x, y = cx + sh, anchor[3] + gap + h / 2
                    elif side == "left":
                        x, y = anchor[0] - gap - w / 2, cy + sh
                    else:
                        x, y = anchor[2] + gap + w / 2, cy + sh
                    item.SetPosition(P(x, y))
                    bb2 = box(item, 0.1) if tight else box(item)
                    if self.free(bb2):
                        self.placed.append(box(item, 0.05))
                        return True
        return False

    def fixed(self, item):
        self.placed.append(_box(item, 0.05))


def silkscreen(c, board):
    sp = SilkPlacer(board)
    # board name, in the ground strip between the input and output, left of C3
    # so the capacitor body does not hide it in an angled view
    for txt, y, size, bold in (("NMOS LDO", 101.9, 1.3, True), ("1.0 V  1 A", 103.7, 1.0, False),
                               ("REV A  2026", 105.4, 0.8, False)):
        c.text(txt, 124.2, y, size=size, bold=bold)
    for t in [d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT"]:
        sp.fixed(t)

    def label(txt, anchor, size=0.8, sides=("top", "bottom", "left", "right"), angles=(0,),
              shifts=(0.0, -0.8, 0.8, -1.6, 1.6, 3.0, -3.0, 4.5, -4.5)):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(0.15))
        board.Add(t)
        if not (sp.place(t, anchor, sides=sides, angles=angles, shifts=shifts) or
                sp.place(t, anchor, sides=sides, angles=angles, shifts=shifts, tight=True)):
            print("silk: no room for", txt)
            board.Remove(t)

    fp = {f.GetReference(): f for f in board.GetFootprints()}

    def padbox(ref, num):
        for p in fp[ref].Pads():
            if p.GetNumber() == num:
                return _box(p)

    def crt(ref):
        cy = fp[ref].GetCourtyard(pcbnew.F_CrtYd).BBox()
        return (cy.GetX() / 1e6, cy.GetY() / 1e6, (cy.GetX() + cy.GetWidth()) / 1e6,
                (cy.GetY() + cy.GetHeight()) / 1e6)

    # connector pin names just outside the terminal blocks, taken from the pad nets
    pin_names = {"GND": "GND", "/VIN": "VIN 1.5-2V", "/VOUT": "VOUT 1V", "/EN": "EN", "+5V": "+5V"}
    for ref in ("J1", "J2"):
        cb = crt(ref)
        top, bottom = sorted(fp[ref].Pads(), key=lambda q: q.GetPosition().y)
        bx = padbox(ref, bottom.GetNumber())
        label(pin_names[top.GetNetname()], (cb[0], cb[1], cb[2], cb[1]), sides=("top",))
        # the lower pin name sits under the block, centred on that screw
        label(pin_names[bottom.GetNetname()], (bx[0] - 2.0, cb[3], bx[2] + 2.0, cb[3]), sides=("bottom",))
    j3 = crt("J3")
    for pad in fp["J3"].Pads():
        b = padbox("J3", pad.GetNumber())
        label(pin_names[pad.GetNetname()], (b[0], j3[1] - 0.3, b[2], j3[1] - 0.3), sides=("top",))
    # test point names are their net names; TP8 and TP9 put theirs above the loop so
    # they do not line up with the GND names of J1 and J2, TP1 beside its loop
    tp_sides = {"TP8": ("top", "left", "right", "bottom"), "TP9": ("top", "left", "right", "bottom"),
                "TP1": ("right", "bottom", "left", "top")}
    for ref in sorted((r for r in fp if r.startswith("TP")), key=lambda r: int(r[2:])):
        name = fp[ref].Pads()[0].GetNetname().lstrip("/")
        label(name, crt(ref), sides=tp_sides.get(ref, ("bottom", "top", "left", "right")))
    # reference designators: 0.8 mm text next to the part, hidden where there is no room
    # connectors and ICs first, then the crowded compensation parts, then the rest
    crowded = ("C9", "R13", "C10", "R4", "R2", "R3")
    order = sorted(fp, key=lambda r: (r[0] not in "JUQ", r not in crowded,
                                      crowded.index(r) if r in crowded else 0, r))
    for ref in order:
        f = fp[ref]
        t = f.Reference()
        if ref.startswith(("H", "FID", "NT", "TP")):
            t.SetVisible(False)
            continue
        t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        t.SetTextThickness(mm(0.13))
        if ref.startswith("J"):
            # terminal blocks: beside the body, never in the row of pin names and never on
            # the body itself; with no room left the pin names identify the connector
            sides = ("left", "right", "bottom") if ref == "J3" else ("left", "right")
            ok = sp.place(t, crt(ref), sides=sides, angles=(90, 0), shifts=(0.0, -0.8, 0.8, -1.6, 1.6))
        elif ref == "C7":
            # keep C7's name on the far side from the VOUT pin name of J2
            ok = sp.place(t, crt(ref), sides=("bottom", "left"), angles=(0, 90), shifts=(0.0, 0.4, -0.4, 0.8, -0.8),
                          tight=True)
        else:
            ok = sp.place(t, crt(ref), angles=(0, 90), shifts=(0.0, -0.4, 0.4, -0.8, 0.8, -1.2, 1.2, -1.6, 1.6, -2.4, 2.4))
            if not ok:
                ok = sp.place(t, crt(ref), angles=(0, 90), shifts=(0.0, -0.4, 0.4, -0.8, 0.8, -1.2, 1.2, -1.6, 1.6, -2.4, 2.4),
                              tight=True)
        if not ok:
            t.SetVisible(False)
            print("silk: reference hidden for", ref)
    # bottom side notes, placed on copper with no vias under them
    for txt, x, y, size in (("NMOS LDO  REV A", 113.0, 140.4, 1.0), ("Q1 HEAT SPREADER  VIN", 118.0, 110.5, 0.8),
                            ("KELVIN SENSE PAIR", 140.4, 118.6, 0.8)):
        c.text(txt, x, y, size=size, layer=pcbnew.B_SilkS)
    check_silk_over_holes(board)


def check_silk_over_holes(board):
    """Report any silkscreen text that a via or plated hole would drill through."""
    holes = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            holes.append((t.GetPosition().x / 1e6, t.GetPosition().y / 1e6, t.GetDrillValue() / 2e6 + 0.1))
    for f in board.GetFootprints():
        for pad in f.Pads():
            if pad.GetDrillSize().x > 0:
                holes.append((pad.GetPosition().x / 1e6, pad.GetPosition().y / 1e6, pad.GetDrillSize().x / 2e6 + 0.1))
    texts = [d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT"]
    for f in board.GetFootprints():
        texts += [f.Reference()] if f.Reference().IsVisible() else []
    bad = 0
    for t in texts:
        if t.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        b = _stroke_box(t, 0.0)
        for hx, hy, r in holes:
            if b[0] - r < hx < b[2] + r and b[1] - r < hy < b[3] + r:
                print(f"silk: hole at ({hx:.2f}, {hy:.2f}) under text {t.GetText()!r}")
                bad += 1
    print(f"silk: {bad} texts over holes")


def apply(board, fps, netinfo):
    c = Copper(board, netinfo)
    routes(c)
    zones(c)
    silkscreen(c, board)


def fill_zones(path):
    """Reload the saved board so connectivity and settings are complete, then fill."""
    board = pcbnew.LoadBoard(path)
    board.BuildConnectivity()
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(path)
    return board

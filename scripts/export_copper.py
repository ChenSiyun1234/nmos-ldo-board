"""Rasterise the copper of each layer of the finished board for the thermal
model in sim/thermal.py. Run with KiCad's Python after the zones are filled.

Writes, under results/thermal/:
    copper_<layer>.png   white = copper, 20 px per mm
    vias.csv             every plated hole: x, y, drill, net
    board_info.json      board outline, Q1 tab pad, unplated holes, part and pad outlines
"""
import csv
import json
import os

import pcbnew
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PCB = os.path.join(ROOT, "hardware", "nmos-ldo-board.kicad_pcb")
OUT = os.path.join(ROOT, "results", "thermal")
PPM = 20                      # pixels per mm
X0, Y0, W, H = 100.0, 100.0, 54.0, 42.0
LAYERS = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}


def px(pt):
    return ((pt.x / 1e6 - X0) * PPM, (pt.y / 1e6 - Y0) * PPM)


def draw_polyset(draw, ps):
    for i in range(ps.OutlineCount()):
        outline = ps.Outline(i)
        pts = [px(outline.CPoint(k)) for k in range(outline.PointCount())]
        if len(pts) > 2:
            draw.polygon(pts, fill=255)
        for h in range(ps.HoleCount(i)):
            hole = ps.Hole(i, h)
            hp = [px(hole.CPoint(k)) for k in range(hole.PointCount())]
            if len(hp) > 2:
                draw.polygon(hp, fill=0)


def shape(item, layer):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
    return ps


def mm_box(bb):
    return [round(bb.GetX() / 1e6, 3), round(bb.GetY() / 1e6, 3),
            round((bb.GetX() + bb.GetWidth()) / 1e6, 3), round((bb.GetY() + bb.GetHeight()) / 1e6, 3)]


def main():
    os.makedirs(OUT, exist_ok=True)
    board = pcbnew.LoadBoard(PCB)
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    for name, layer in LAYERS.items():
        img = Image.new("L", (int(W * PPM), int(H * PPM)), 0)
        draw = ImageDraw.Draw(img)
        for z in board.Zones():
            if z.GetIsRuleArea() or not z.IsOnLayer(layer):
                continue
            if z.HasFilledPolysForLayer(layer):
                draw_polyset(draw, z.GetFilledPolysList(layer))
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA" or t.GetLayer() != layer:
                continue
            draw_polyset(draw, shape(t, layer))
        for v in vias:
            if v.FlashLayer(layer):
                draw_polyset(draw, shape(v, layer))
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    continue
                if pad.IsOnLayer(layer) and pad.FlashLayer(layer):
                    draw_polyset(draw, shape(pad, layer))
        img.save(os.path.join(OUT, f"copper_{name.replace('.', '_')}.png"))

    npth = []
    with open(os.path.join(OUT, "vias.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["x_mm", "y_mm", "drill_mm", "net"])
        for v in vias:
            w.writerow([v.GetPosition().x / 1e6, v.GetPosition().y / 1e6, v.GetDrillValue() / 1e6,
                        v.GetNetname()])
        # plated through-hole pads conduct between layers too
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                d = pad.GetDrillSize().x / 1e6
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                    w.writerow([pad.GetPosition().x / 1e6, pad.GetPosition().y / 1e6, d, pad.GetNetname()])
                elif pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH and d > 0:
                    npth.append([pad.GetPosition().x / 1e6, pad.GetPosition().y / 1e6, d])

    parts = {}
    for fp in board.GetFootprints():
        pads = list(fp.Pads())
        if not pads:
            continue
        boxes = [mm_box(p.GetBoundingBox()) for p in pads]
        parts[fp.GetReference()] = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                    max(b[2] for b in boxes), max(b[3] for b in boxes)]
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                continue
            layers = [n for n, l in LAYERS.items() if pad.IsOnLayer(l) and pad.FlashLayer(l)]
            pads.append([fp.GetReference(), pad.GetNumber(), pad.GetNetname()] + mm_box(pad.GetBoundingBox())
                        + [layers])
    q1 = board.FindFootprintByReference("Q1")
    tab = [p for p in q1.Pads() if p.GetNumber() == "2"][0]
    info = {"ppm": PPM, "board": [X0, Y0, W, H], "q1_tab": mm_box(tab.GetBoundingBox()),
            "npth": npth, "parts": parts, "pads": pads}
    with open(os.path.join(OUT, "board_info.json"), "w") as f:
        json.dump(info, f, indent=1)
    print("copper rasters written to", OUT)


if __name__ == "__main__":
    main()

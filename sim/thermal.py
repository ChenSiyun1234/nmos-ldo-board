"""Steady state thermal model of the routed board at the worst case Q1 loss.

Inputs, written from the routed board by scripts/export_copper.py:
    results/thermal/copper_<layer>.png   copper of each layer, 20 px per mm
    results/thermal/vias.csv             plated holes: x, y, drill, net
    results/thermal/board_info.json      outline, Q1 tab pad, unplated holes, part outlines
Input from the circuit simulation (the "dc" part of run_all.py):
    results/data/power.json              Q1 loss at VIN 2.0 V and 1 A, bias and preload power

Method
    One node per 0.25 mm cell on each of the four copper layers. The in plane
    conductance between two cells is built from the 0.05 mm raster: pixels in
    series along the path, rows in parallel across it. A clearance gap between
    two pours therefore stays a gap and does not get smeared into copper.
    Neighbouring layers are joined through the dielectric and through the
    copper barrel of every plated hole. Both faces lose heat to still air.
    The Q1 junction is one extra node tied to the tab pad through RthJC.

Numbers used
    IRLR024N datasheet: RthJC 3.3 K/W max, TJ max 175 C.
    Stackup from the board file: four 35 um copper layers, 0.2104 mm prepreg,
    1.02 mm core.
    Assumed: copper 385 W/m K, FR4 0.8 W/m K in plane and 0.3 W/m K through
    the board, 20 um barrel plating.
    Surface: board flat in still air. Flat plate natural convection gives about
    8 W/m2 K on the top face and 4 W/m2 K under the board at a 20 to 30 K rise,
    and radiation from solder mask with emissivity 0.9 adds about 6 W/m2 K on
    each face. That is 14 and 10 W/m2 K. A second case cuts both by 35 %.
    Left out, which makes the result pessimistic: heat leaving through the
    component bodies, the terminal blocks and the board edges.
"""
import csv
import json
import os
import sys
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RES = os.path.abspath(os.path.join(HERE, "..", "results"))
TH = os.path.join(RES, "thermal")
DATA = os.path.join(RES, "data")

K_CU = 385.0                  # W/m K
K_FR4_XY = 0.8                # W/m K, in the plane of the board
K_FR4_Z = 0.3                 # W/m K, through the board
T_CU = 35e-6                  # m, every copper layer
T_DIEL = [0.2104e-3, 1.02e-3, 0.2104e-3]   # m, prepreg, core, prepreg
T_PLATE = 20e-6               # m, plated hole wall
RTH_JC = 3.3                  # K/W, IRLR024N junction to case
TJ_MAX = 175.0                # C
TJ_LIMIT = 125.0              # C, design limit used for the target
CELL_MM = 0.25
LAYERS = ["F_Cu", "In1_Cu", "In2_Cu", "B_Cu"]
CASES = [("still air", 14.0, 10.0), ("35 % less cooling", 9.1, 6.5)]
TA = 25.0
CORNER_R_MM = 1.0


def load_inputs():
    with open(os.path.join(TH, "board_info.json")) as f:
        info = json.load(f)
    cu = [np.asarray(Image.open(os.path.join(TH, f"copper_{n}.png")), dtype=float) / 255.0 for n in LAYERS]
    with open(os.path.join(TH, "vias.csv")) as f:
        vias = [(float(r["x_mm"]), float(r["y_mm"]), float(r["drill_mm"]), r["net"]) for r in csv.DictReader(f)]
    with open(os.path.join(DATA, "power.json")) as f:
        power = json.load(f)
    return info, cu, vias, power


def solid_mask(info, shape):
    """1 where there is board material: inside the rounded outline, outside unplated holes."""
    ppm = info["ppm"]
    x0, y0, w, h = info["board"]
    fy, fx = shape
    xs = (np.arange(fx) + 0.5) / ppm
    ys = (np.arange(fy) + 0.5) / ppm
    X, Y = np.meshgrid(xs, ys)
    m = np.ones(shape)
    r = CORNER_R_MM
    for cx, cy, ex, ey in ((r, r, 0, 0), (w - r, r, w, 0), (r, h - r, 0, h), (w - r, h - r, w, h)):
        in_square = (np.abs(X - ex) < r) & (np.abs(Y - ey) < r)
        m[in_square & ((X - cx) ** 2 + (Y - cy) ** 2 > r * r)] = 0.0
    for hx, hy, d in info.get("npth", []):
        m[(X - (hx - x0)) ** 2 + (Y - (hy - y0)) ** 2 < (d / 2) ** 2] = 0.0
    return m


def build(info, cu, vias, h_top, h_bot):
    ppm = info["ppm"]
    x0, y0 = info["board"][0], info["board"][1]
    n = int(round(CELL_MM * ppm))
    fy, fx = cu[0].shape
    ny, nx = fy // n, fx // n
    cell = CELL_MM * 1e-3
    area = cell * cell
    solid = solid_mask(info, cu[0].shape)
    solid_c = solid.reshape(ny, n, nx, n).mean(axis=(1, 3))
    share = [T_DIEL[0] / 2, (T_DIEL[0] + T_DIEL[1]) / 2, (T_DIEL[1] + T_DIEL[2]) / 2, T_DIEL[2] / 2]
    nn = ny * nx
    N = 4 * nn + 1
    J = 4 * nn                      # junction node
    idx = np.arange(nn).reshape(ny, nx)
    rows, cols, vals = [], [], []

    def couple(a, b, g):
        a = np.ravel(a)
        b = np.ravel(b)
        g = np.ravel(g)
        rows.extend([a, b, a, b])
        cols.extend([a, b, b, a])
        vals.extend([g, g, -g, -g])

    c0 = np.arange(nx - 1) * n + n // 2
    r0 = np.arange(ny - 1) * n + n // 2
    for l in range(4):
        ks = (K_CU * T_CU * cu[l] + K_FR4_XY * share[l]) * solid      # W/K per square
        inv = 1.0 / np.maximum(ks, 1e-12)
        # neighbours along x
        R = 0.5 * inv[:, c0] + 0.5 * inv[:, c0 + n]
        for k in range(1, n):
            R = R + inv[:, c0 + k]
        gx = (1.0 / R).reshape(ny, n, nx - 1).sum(axis=1)
        couple(l * nn + idx[:, :-1], l * nn + idx[:, 1:], gx)
        # neighbours along y
        R = 0.5 * inv[r0, :] + 0.5 * inv[r0 + n, :]
        for k in range(1, n):
            R = R + inv[r0 + k, :]
        gy = (1.0 / R).reshape(ny - 1, nx, n).sum(axis=2)
        couple(l * nn + idx[:-1, :], l * nn + idx[1:, :], gy)
    # through the dielectric
    for l in range(3):
        gz = K_FR4_Z * area * solid_c / T_DIEL[l]
        couple(l * nn + idx, (l + 1) * nn + idx, gz)
    # plated hole barrels
    nvia = 0
    for x, y, d, _net in vias:
        i = int((y - y0) / CELL_MM)
        j = int((x - x0) / CELL_MM)
        if not (0 <= i < ny and 0 <= j < nx):
            continue
        a_barrel = np.pi * T_PLATE * (d * 1e-3 - T_PLATE)        # d is in mm
        for l in range(3):
            couple([l * nn + idx[i, j]], [(l + 1) * nn + idx[i, j]], [K_CU * a_barrel / (T_DIEL[l] + T_CU)])
        nvia += 1
    # junction to the tab pad, spread over the copper under the tab
    tx0, ty0, tx1, ty1 = info["q1_tab"]
    yc = y0 + (np.arange(ny) + 0.5) * CELL_MM
    xc = x0 + (np.arange(nx) + 0.5) * CELL_MM
    Xc, Yc = np.meshgrid(xc, yc)
    cu_c = cu[0].reshape(ny, n, nx, n).mean(axis=(1, 3))
    tab = (Xc > tx0) & (Xc < tx1) & (Yc > ty0) & (Yc < ty1)
    w = np.where(tab, cu_c, 0.0)
    w = w / w.sum()
    sel = np.nonzero(w.ravel())[0]
    couple(np.full(len(sel), J), sel, w.ravel()[sel] / RTH_JC)
    A = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N)).tocsc()
    # faces to ambient
    conv = np.zeros(N)
    conv[0:nn] = h_top * area * solid_c.ravel()
    conv[3 * nn:4 * nn] = h_bot * area * solid_c.ravel()
    A = A + sp.diags(conv)
    grid = dict(n=n, ny=ny, nx=nx, nn=nn, J=J, xc=xc, yc=yc, Xc=Xc, Yc=Yc, nvia=nvia, tab_cells=int(tab.sum()),
                solid=solid_c)
    return A.tocsc(), grid


def part_cells(info, grid, ref):
    bx0, by0, bx1, by1 = info["parts"][ref]
    m = (grid["Xc"] >= bx0) & (grid["Xc"] <= bx1) & (grid["Yc"] >= by0) & (grid["Yc"] <= by1)
    return np.nonzero(m.ravel())[0]


def solve(info, cu, vias, power, h_top, h_bot):
    A, g = build(info, cu, vias, h_top, h_bot)
    lu = spla.splu(A, permc_spec="MMD_AT_PLUS_A")
    N = A.shape[0]
    b_q1 = np.zeros(N)
    b_q1[g["J"]] = 1.0                                  # 1 W in the junction
    b_other = np.zeros(N)
    for ref, p in (("U1", power["bias_W"]), ("R1", power["preload_W"])):
        c = part_cells(info, g, ref)
        b_other[c] += p / len(c)
    t_unit = lu.solve(b_q1)
    t_other = lu.solve(b_other)
    rise = power["q1_W"] * t_unit + t_other
    return rise, t_unit, g


def plot(info, rise, g, power, tj):
    import plotstyle as ps
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle
    plt = ps.plt
    nn, ny, nx = g["nn"], g["ny"], g["nx"]
    top = TA + rise[:nn].reshape(ny, nx)
    bot = TA + rise[3 * nn:4 * nn].reshape(ny, nx)
    void = g["solid"] < 0.5
    top_m = np.ma.masked_where(void, top)
    bot_m = np.ma.masked_where(void, bot)
    cmap = LinearSegmentedColormap.from_list("heat", ["#fdf3ec", "#f6b48f", "#eb6834", "#a8401a", "#5c220c"])
    cmap.set_bad(ps.SURFACE)
    vmin = float(np.floor(min(top_m.min(), bot_m.min())))
    vmax = float(np.ceil(max(top_m.max(), bot_m.max())))
    x0, y0, w, h = info["board"]
    fig, axs = plt.subplots(1, 2, figsize=(10.4, 3.9), gridspec_kw=dict(wspace=0.06))
    levels = np.arange(np.ceil(vmin / 2) * 2, vmax, 2)
    for ax, data, title in ((axs[0], top_m, "Top layer"), (axs[1], bot_m, "Bottom layer, seen through the board")):
        im = ax.imshow(data, extent=(0, w, h, 0), cmap=cmap, vmin=vmin, vmax=vmax, interpolation="bilinear")
        cs = ax.contour(g["xc"] - x0, g["yc"] - y0, data, levels=levels, colors=ps.INK, linewidths=0.45,
                        alpha=0.55)
        ax.clabel(cs, fmt="%d", fontsize=7, inline=True, colors=ps.INK)
        ax.set_title(title)
        ax.set_xlim(0, w)
        ax.set_ylim(h, 0)
        ax.set_aspect("equal")
        ax.grid(False)
        ax.set_xlabel("x (mm)")
        for sp_ in ax.spines.values():
            sp_.set_visible(False)
    axs[0].set_ylabel("y (mm)")
    axs[1].set_yticklabels([])
    for ref in ("Q1", "C1", "C3", "J1", "J2", "U1"):
        bx0, by0, bx1, by1 = info["parts"][ref]
        axs[0].add_patch(Rectangle((bx0 - x0, by0 - y0), bx1 - bx0, by1 - by0, fill=False, ec=ps.INK, lw=0.7))
        axs[0].annotate(ref, ((bx0 + bx1) / 2 - x0, by1 - y0 + 0.4), ha="center", va="top", fontsize=7.8,
                        color=ps.INK)
    cb = fig.colorbar(im, ax=axs, shrink=0.9, pad=0.015)
    cb.set_label("Temperature (°C)", color=ps.INK2)
    cb.outline.set_visible(False)
    axs[0].text(0.0, 1.13, f"Board temperature with {power['q1_W']:.2f} W in Q1 at 25 °C still air, simulated. "
                f"Q1 junction {tj:.0f} °C", transform=axs[0].transAxes, ha="left", va="bottom", fontsize=10.5,
                fontweight="semibold", color=ps.INK)
    bx0, by0, bx1, by1 = info["parts"]["Q1"]
    axs[1].add_patch(Rectangle((bx0 - x0, by0 - y0), bx1 - bx0, by1 - by0, fill=False, ec=ps.INK, lw=0.7,
                               ls=(0, (3, 2))))
    axs[1].annotate("Q1 above", ((bx0 + bx1) / 2 - x0, by1 - y0 + 0.4), ha="center", va="top", fontsize=7.8,
                    color=ps.INK)
    ps.save(fig, os.path.join(RES, "thermal_map.png"))
    for name, data in (("thermal_top_layer.csv", top), ("thermal_bottom_layer.csv", bot)):
        with open(os.path.join(DATA, name), "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["y_mm/x_mm"] + [f"{v - x0:.3f}" for v in g["xc"]])
            for i in range(ny):
                wr.writerow([f"{g['yc'][i] - y0:.3f}"] + [f"{v:.2f}" for v in data[i]])


def main(metric):
    t0 = time.time()
    info, cu, vias, power = load_inputs()
    print(f"  Q1 {power['q1_W']:.3f} W, bias {power['bias_W'] * 1e3:.1f} mW, preload {power['preload_W'] * 1e3:.1f} mW")
    out = {}
    for label, ht, hb in CASES:
        rise, t_unit, g = solve(info, cu, vias, power, ht, hb)
        nn = g["nn"]
        tj = TA + rise[g["J"]]
        caps = {ref: TA + rise[part_cells(info, g, ref)].max() for ref in ("C1", "C3")}
        out[label] = dict(tj=tj, rja=t_unit[g["J"]], tboard=TA + rise[:nn].max(), caps=caps, rise=rise, g=g)
        print(f"  {label}: h {ht}/{hb} W/m2K, Tj {tj:.1f} C, RthJA {t_unit[g['J']]:.1f} K/W, "
              f"board max {TA + rise[:nn].max():.1f} C, C1 {caps['C1']:.1f} C, C3 {caps['C3']:.1f} C, "
              f"{g['nvia']} plated holes, {g['tab_cells']} tab cells")
    a, b = out["still air"], out["35 % less cooling"]
    p = power["q1_W"]
    metric("Thermal", "Q1 junction temperature", f"{p:.2f} W, 25 C still air", f"<= {TJ_LIMIT:.0f} C", a["tj"],
           "C", a["tj"] <= TJ_LIMIT, "{:.0f}")
    metric("Thermal", "Q1 junction temperature", f"{p:.2f} W, 25 C, 35 % less surface cooling",
           f"<= {TJ_LIMIT:.0f} C", b["tj"], "C", b["tj"] <= TJ_LIMIT, "{:.0f}")
    metric("Thermal", "Junction to ambient, Q1 on this board", "still air / 35 % less cooling", "report",
           f"{a['rja']:.0f} / {b['rja']:.0f}", "K/W")
    hot = max(a["caps"], key=a["caps"].get)
    metric("Thermal", "Hottest polymer capacitor", f"{hot}, 25 C still air", "<= 105 C rating",
           a["caps"][hot], "C", a["caps"][hot] <= 105.0, "{:.0f}")
    ta_max = TJ_LIMIT - (b["tj"] - TA)
    metric("Thermal", "Highest ambient for TJ 125 C", "35 % less surface cooling", "report", ta_max, "C", None,
           "{:.0f}")
    # what the vias at the Q1 tab are worth: the same board with them left out
    tx0, ty0, tx1, ty1 = info["q1_tab"]
    at_tab = [v for v in vias if v[3] == "/VIN" and v[2] < 0.5 and tx0 - 0.6 <= v[0] <= tx1 + 0.6
              and ty0 - 1.5 <= v[1] <= ty1 + 0.2]
    rest = [v for v in vias if v not in at_tab]
    ht, hb = CASES[0][1], CASES[0][2]
    rise_nv, _, g_nv = solve(info, cu, rest, power, ht, hb)
    tj_nv = TA + rise_nv[g_nv["J"]]
    print(f"  without the {len(at_tab)} vias at the Q1 tab: Tj {tj_nv:.1f} C")
    metric("Thermal", "Q1 junction temperature, tab vias left out",
           f"same board without the {len(at_tab)} vias at the Q1 tab, 25 C still air", "report", tj_nv, "C",
           None, "{:.0f}")
    plot(info, a["rise"], a["g"], power, a["tj"])
    print(f"  thermal model solved in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    def _m(*args, **kw):
        print(args)
    main(_m)

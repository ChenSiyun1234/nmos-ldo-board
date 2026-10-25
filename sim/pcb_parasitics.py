"""DC resistance of the high current copper, computed from the routed board.

Uses the same copper rasters as sim/thermal.py (written by
scripts/export_copper.py). Each copper layer becomes a resistor grid on a
0.25 mm pitch built from the 0.05 mm raster, so clearance gaps between nets
stay open. Plated holes join the layers through their barrels. A pad is a
terminal that touches every cell under it.

Prints the resistance of each path in the board netlist and writes
results/data/pcb_resistance.csv. The values in sim/netlists/ldo_board.cir
(rpcb_in, rpcb_q, rpcb_out, rpcb_gnd) are rounded up from these.

    python sim/pcb_parasitics.py
"""
import csv
import os
import sys

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import thermal as th  # noqa: E402

SIGMA_CU = 5.8e7          # S/m at 25 C
LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def network(info, cu, vias):
    ppm = info["ppm"]
    x0, y0 = info["board"][0], info["board"][1]
    n = int(round(th.CELL_MM * ppm))
    fy, fx = cu[0].shape
    ny, nx = fy // n, fx // n
    nn = ny * nx
    idx = np.arange(nn).reshape(ny, nx)
    rows, cols, vals = [], [], []

    def couple(a, b, g):
        a, b, g = np.ravel(a), np.ravel(b), np.ravel(g)
        rows.extend([a, b, a, b])
        cols.extend([a, b, b, a])
        vals.extend([g, g, -g, -g])

    c0 = np.arange(nx - 1) * n + n // 2
    r0 = np.arange(ny - 1) * n + n // 2
    for l in range(4):
        gs = SIGMA_CU * th.T_CU * cu[l]                 # S per square
        inv = 1.0 / np.maximum(gs, 1e-9)
        R = 0.5 * inv[:, c0] + 0.5 * inv[:, c0 + n]
        for k in range(1, n):
            R = R + inv[:, c0 + k]
        couple(l * nn + idx[:, :-1], l * nn + idx[:, 1:], (1.0 / R).reshape(ny, n, nx - 1).sum(axis=1))
        R = 0.5 * inv[r0, :] + 0.5 * inv[r0 + n, :]
        for k in range(1, n):
            R = R + inv[r0 + k, :]
        couple(l * nn + idx[:-1, :], l * nn + idx[1:, :], (1.0 / R).reshape(ny - 1, nx, n).sum(axis=2))
    for x, y, d, _net in vias:
        i, j = int((y - y0) / th.CELL_MM), int((x - x0) / th.CELL_MM)
        a = np.pi * th.T_PLATE * (d * 1e-3 - th.T_PLATE)
        for l in range(3):
            couple([l * nn + idx[i, j]], [(l + 1) * nn + idx[i, j]], [SIGMA_CU * a / (th.T_DIEL[l] + th.T_CU)])
    G = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                      shape=(4 * nn, 4 * nn)).tocsr()
    return G, dict(n=n, ny=ny, nx=nx, nn=nn, idx=idx, x0=x0, y0=y0)


def pad_nodes(info, g, ref, num):
    for p in info["pads"]:
        if p[0] == ref and p[1] == num:
            bx0, by0, bx1, by1, layers = p[3], p[4], p[5], p[6], p[7]
            yc = g["y0"] + (np.arange(g["ny"]) + 0.5) * th.CELL_MM
            xc = g["x0"] + (np.arange(g["nx"]) + 0.5) * th.CELL_MM
            X, Y = np.meshgrid(xc, yc)
            m = ((X > bx0) & (X < bx1) & (Y > by0) & (Y < by1)).ravel()
            cells = np.nonzero(m)[0]
            out = [LAYERS.index(L) * g["nn"] + cells for L in layers]
            return np.concatenate(out)
    raise KeyError(f"{ref} pad {num}")


def resistance(G, a_nodes, b_nodes):
    """Two terminal resistance: terminal A is one extra node joined to its
    cells with a very large conductance, B likewise, then 1 A from A to B."""
    N = G.shape[0]
    big = 1e6
    extra_r, extra_c, extra_v = [], [], []
    for t, nodes in ((N, a_nodes), (N + 1, b_nodes)):
        for k in nodes:
            extra_r += [t, k, t, k]
            extra_c += [t, k, k, t]
            extra_v += [big, big, -big, -big]
    M = sp.coo_matrix((extra_v, (extra_r, extra_c)), shape=(N + 2, N + 2)).tocsr()
    A = sp.bmat([[G, None], [None, sp.csr_matrix((2, 2))]]).tocsr() + M
    A = A + sp.eye(N + 2) * 1e-9                  # floating copper islands
    # ground terminal B
    keep = np.r_[0:N + 1]
    A = A[keep][:, keep].tocsc()
    b = np.zeros(N + 1)
    b[N] = 1.0
    v = spla.spsolve(A, b)
    return float(v[N])


PATHS = [
    # name, netlist parameter, (ref, pad) from, (ref, pad) to
    ("VIN: J1 pin 2 to the Q1 tab", "rpcb_in", ("J1", "2"), ("Q1", "2")),
    ("VOUT: Q1 source to C3", "rpcb_q", ("Q1", "3"), ("C3", "1")),
    ("VOUT: Q1 source to J2 pin 1", "", ("Q1", "3"), ("J2", "1")),
    ("GND: J2 pin 2 to J1 pin 1", "", ("J2", "2"), ("J1", "1")),
]


def main():
    info, cu, vias, _power = th.load_inputs()
    G, g = network(info, cu, vias)
    res = {}
    for name, _par, a, b in PATHS:
        res[name] = resistance(G, pad_nodes(info, g, *a), pad_nodes(info, g, *b))
    r_q = res["VOUT: Q1 source to C3"]
    r_out = res["VOUT: Q1 source to J2 pin 1"] - r_q
    r_gnd = res["GND: J2 pin 2 to J1 pin 1"]
    rows = [(k, f"{v * 1e3:.3f}") for k, v in res.items()]
    rows.append(("VOUT: C3 to J2 pin 1 (difference)", f"{r_out * 1e3:.3f}"))
    os.makedirs(th.DATA, exist_ok=True)
    with open(os.path.join(th.DATA, "pcb_resistance.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "resistance_mohm"])
        w.writerows(rows)
    for k, v in rows:
        print(f"  {k:40s} {v:>8s} mohm")
    print(f"  netlist values to use: rpcb_in >= {res['VIN: J1 pin 2 to the Q1 tab'] * 1e3:.2f}, "
          f"rpcb_q >= {r_q * 1e3:.2f}, rpcb_out >= {r_out * 1e3:.2f}, rpcb_gnd >= {r_gnd / 2 * 1e3:.2f} mohm")


if __name__ == "__main__":
    main()

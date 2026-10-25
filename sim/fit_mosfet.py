"""Fit an ngspice VDMOS model of the IRLR024N pass device to datasheet numbers.

Datasheet values used (Infineon IRLR024N, 25 C table values):
  VGS(th)  1.0 V min / 2.0 V max at VDS = VGS, ID = 250 uA  -> nominal model uses 1.5 V
  RDS(on)  0.065 ohm max at VGS = 10 V, ID = 10 A
           0.080 ohm max at VGS = 5 V,  ID = 10 A
           0.110 ohm max at VGS = 4 V,  ID = 9 A
  Ciss 480 pF, Coss 130 pF, Crss 61 pF at VGS = 0, VDS = 25 V, 1 MHz
  Qg 15 nC, Qgs 3.7 nC, Qgd 8.5 nC (max); the datasheet tests at ID = 11 A,
           VDS = 44 V, VGS = 5 V, this gate charge bench uses ID = 10 A
  gfs 8.3 S min at VDS = 25 V; the datasheet tests at ID = 11 A, this check
           uses ID = 10 A (used only as a check)

Assumptions that are not on the datasheet are listed in ASSUMED below.
The fitted .model card is written to models/irlr024n.lib and every target is
compared with what the fitted model gives in ../results/model_check_irlr024n.csv.
"""
import csv
import os
import sys

import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ngspice_shared as ng  # noqa: E402

WORK = os.path.join(HERE, "netlists", "generated")
os.makedirs(WORK, exist_ok=True)
RESULTS = os.path.join(HERE, "..", "results")
os.makedirs(RESULTS, exist_ok=True)

VTH_NOM = 1.5          # middle of the 1.0 V to 2.0 V datasheet range
RDS_POINTS = [(10.0, 10.0, 0.065), (5.0, 10.0, 0.080), (4.0, 9.0, 0.110)]
CISS, COSS, CRSS = 480e-12, 130e-12, 61e-12
QG_MAX, QGS_MAX, QGD_MAX = 15e-9, 3.7e-9, 8.5e-9
GFS_MIN = 8.3

ASSUMED = {
    "rs": 0.005,        # source bond wire and lead, ohm
    "lambda": 0.003,    # channel length modulation, 1/V (keeps the gate charge plateau flat)
    "ksubthres": 0.1,   # weak inversion smoothing, gives about 115 mV/decade
    "vj": 0.8,          # body diode junction potential
    "m": 0.5,           # body diode grading coefficient
    "cgdmin": 15e-12,   # high voltage floor of Cgd
    "is": 1e-10, "n": 1.1, "rb": 0.03,   # body diode, gives about 1.2 V at 10 A
    "bv": 60, "ibv": 250e-6,
}


def model_card(p, name="IRLR024N"):
    return (f".model {name} VDMOS(vto={p['vto']:.9g} kp={p['kp']:.9g} theta={p['theta']:.9g} "
            f"lambda={p['lambda']:.9g} rd={p['rd']:.9g} rs={p['rs']:.9g} "
            f"ksubthres={p['ksubthres']:.9g} mtriode={p.get('mtriode', 1.0):.9g} "
            f"cgs={p['cgs']:.9g} cgdmin={p['cgdmin']:.9g} cgdmax={p['cgdmax']:.9g} a={p['a']:.9g} "
            f"cjo={p['cjo']:.9g} vj={p['vj']:.9g} m={p['m']:.9g} is={p['is']:.9g} n={p['n']:.9g} "
            f"rb={p['rb']:.9g} bv={p['bv']:.9g} ibv={p['ibv']:.9g})")


def _run(text, tag):
    path = os.path.join(WORK, f"fit_{tag}.cir")
    with open(path, "w") as f:
        f.write(text)
    vec, _ = ng.run(path)
    return vec


def dc_measure(p):
    """Return (Id at VGS=VDS=VTH_NOM, list of RDS(on) at the datasheet points)."""
    lines = ["* IRLR024N DC fit bench", model_card(p, "QF")]
    # threshold point: drain tied to gate
    lines += [f"VTH g0 0 DC {VTH_NOM}", "M0 g0 g0 0 QF"]
    for k, (vgs, idd, _) in enumerate(RDS_POINTS, start=1):
        lines += [f"VG{k} g{k} 0 DC {vgs}", f"ID{k} 0 d{k} DC {idd}", f"M{k} d{k} g{k} 0 QF"]
    lines += [".op", ".end"]
    v = _run("\n".join(lines) + "\n", "dc")
    ith = -v["vth#branch"][0]
    rds = [v[f"d{k}"][0] / RDS_POINTS[k - 1][1] for k in range(1, len(RDS_POINTS) + 1)]
    return ith, rds


def gfs_measure(p, vds=25.0, idd=10.0):
    text = "\n".join(["* gfs bench", model_card(p, "QF"), f"VD d 0 DC {vds}", "VG g 0 DC 0",
                      "M1 d g 0 QF", ".dc VG 1 8 0.002", ".end"]) + "\n"
    v = _run(text, "gfs")
    vg = v["v-sweep"]
    i = -v["vd#branch"]
    k = np.searchsorted(i, idd)
    g = np.gradient(i, vg)
    vgs_at = np.interp(idd, i, vg)
    return float(np.interp(vgs_at, vg, g)), float(vgs_at)


def transfer_points(p, vds=0.8):
    """VGS needed for a few currents at an LDO-like VDS."""
    text = "\n".join(["* transfer bench", model_card(p, "QF"), f"VD d 0 DC {vds}", "VG g 0 DC 0",
                      "M1 d g 0 QF", ".dc VG 0.5 6 0.001", ".end"]) + "\n"
    v = _run(text, "xfer")
    vg = v["v-sweep"]
    i = -v["vd#branch"]
    g = np.gradient(i, vg)
    out = []
    for target in (1e-3, 2e-3, 10e-3, 100e-3, 1.0):
        vgs = float(np.interp(target, i, vg))
        out.append((target, vgs, float(np.interp(vgs, vg, g))))
    return out


def cap_measure(p, vds=25.0):
    text = "\n".join(["* capacitance bench", model_card(p, "QF"), "VG g 0 DC 0",
                      f"VD d 0 DC {vds} AC 1", "M1 d g 0 QF", ".ac lin 1 1meg 1meg", ".end"]) + "\n"
    v = _run(text, "crss")
    w = 2 * np.pi * 1e6
    crss = abs(v["vg#branch"][0].imag) / w
    coss = abs(v["vd#branch"][0].imag) / w
    text = "\n".join(["* ciss bench", model_card(p, "QF"), f"VD d 0 DC {vds}",
                      "VG g 0 DC 0 AC 1", "M1 d g 0 QF", ".ac lin 1 1meg 1meg", ".end"]) + "\n"
    v = _run(text, "ciss")
    ciss = abs(v["vg#branch"][0].imag) / w
    return ciss, coss, crss


def gate_charge(p, vdd=44.0, idd=10.0, ig=1e-3):
    """Datasheet style gate charge test: constant gate current, clamped
    constant-current drain load. Returns Qgs, Qgd, Qg at VGS = 5 V."""
    text = "\n".join([
        "* gate charge bench", model_card(p, "QF"),
        # drain load: a current source with compliance. It delivers ID once the
        # FET pulls the drain below VDD and gives zero current when the FET is off,
        # so the operating point is unique (same as the clamped inductive test)
        f"VDD vdd 0 DC {vdd}",
        f"BL vdd d I = {idd}*tanh(V(vdd,d)/0.1)",
        f"IG 0 g DC 0 PULSE(0 {ig} 1u 1n 1n 1 2)",
        "RGL g 0 10Meg",
        f".nodeset v(d)={vdd} v(g)=0",
        "M1 d g 0 QF",
        ".tran 10n 40u 0 10n",
        ".end"]) + "\n"
    v = _run(text, "qg")
    t = v["time"] - 1e-6
    vg = v["g"]
    vd = v["d"]
    if vd[0] < 0.95 * vdd or abs(vg[0]) > 0.05:
        raise RuntimeError("gate charge bench did not start with the FET off")
    q = np.clip(t, 0, None) * ig
    # plateau starts when the drain begins to fall; the plateau voltage is VGS
    # at half of VDD; the plateau ends when VGS climbs 0.1 V above it
    k1 = int(np.argmax(vd < 0.98 * vdd))
    kmid = int(np.argmax(vd < 0.5 * vdd))
    # slope dVGS/dQ after the plateau, taken between 4.6 V and 5.0 V
    qa = np.interp(4.6, vg[kmid:], q[kmid:])
    qb = np.interp(5.0, vg[kmid:], q[kmid:])
    slope_post = 0.4 / (qb - qa)
    dv = np.gradient(vg, q + 1e-30 * np.arange(len(q)))
    k2 = kmid + int(np.argmax(dv[kmid:] > 0.5 * slope_post))
    qgs = q[k1]
    qgd = q[k2] - q[k1]
    qg5 = float(np.interp(5.0, vg[k2:], q[k2:]))
    return qgs, qgd, qg5, (t, q, vg, vd)


def fit_dc():
    p = dict(ASSUMED)
    p.update(cgs=CISS - CRSS, cgdmax=400e-12, a=0.3, cjo=390e-12, mtriode=1.0)

    def resid(x):
        p.update(vto=x[0], kp=x[1], theta=x[2], rd=x[3])
        ith, rds = dc_measure(p)
        r = [np.log10(ith / 250e-6) * 4.0]
        r += [(rm - rt) / rt * 10.0 for rm, (_, _, rt) in zip(rds, RDS_POINTS)]
        return r

    x0 = [1.7, 6.0, 0.05, 0.02]
    sol = least_squares(resid, x0, bounds=([0.8, 0.5, 0.0, 0.0], [3.0, 60.0, 2.0, 0.06]),
                        x_scale=[0.2, 2.0, 0.05, 0.01], diff_step=1e-4)
    p.update(vto=sol.x[0], kp=sol.x[1], theta=sol.x[2], rd=sol.x[3])
    return p


def fit_caps(p):
    # junction capacitance: Coss - Crss = CJO / sqrt(1 + VDS/VJ) at 25 V
    p["cjo"] = (COSS - CRSS) * np.sqrt(1 + 25.0 / p["vj"])
    p["cgs"] = CISS - CRSS

    def resid(x):
        p.update(cgdmax=x[0] * 1e-12, a=x[1])
        _, _, crss = cap_measure(p)
        _, qgd, _, _ = gate_charge(p)
        return [(crss - CRSS) / CRSS * 5.0, (qgd - QGD_MAX) / QGD_MAX * 5.0]

    sol = least_squares(resid, [1500.0, 0.5], bounds=([80.0, 0.01], [6000.0, 5.0]),
                        x_scale=[300.0, 0.1], diff_step=1e-2, xtol=1e-6, ftol=1e-6)
    p.update(cgdmax=sol.x[0] * 1e-12, a=sol.x[1])
    return p


def main():
    p = fit_dc()
    p = fit_caps(p)
    # refit DC once more in case the caps changed nothing (they do not affect DC)
    ith, rds = dc_measure(p)
    gfs, vgs_gfs = gfs_measure(p)
    ciss, coss, crss = cap_measure(p)
    qgs, qgd, qg5, wave = gate_charge(p)
    xfer = transfer_points(p)

    card = model_card(p)
    lib = os.path.join(HERE, "models", "irlr024n.lib")
    with open(lib, "w") as f:
        f.write("* IRLR024N logic level NMOS, ngspice VDMOS model fitted by sim/fit_mosfet.py\n")
        f.write("* Fitted to datasheet table values: VGS(th) 250 uA point (set to the 1.5 V middle of\n")
        f.write("* the 1.0 V to 2.0 V range), RDS(on) max at 10 V / 5 V / 4 V, Ciss, Coss, Crss at 25 V,\n")
        f.write("* and Qgd max. Not fitted: temperature behaviour, avalanche, quasi saturation.\n")
        f.write("* Assumed (not on the datasheet): " + ", ".join(
            f"{k}={v:g}" for k, v in ASSUMED.items()) + "\n")
        f.write(card + "\n")
        # threshold corner models: shift vto so VGS(th) lands on the datasheet limits
        for tag, dv in (("VTLO", 1.0 - VTH_NOM), ("VTHI", 2.0 - VTH_NOM)):
            q = dict(p)
            q["vto"] = p["vto"] + dv
            f.write(model_card(q, f"IRLR024N_{tag}") + "\n")

    rows = [
        ("VGS(th) at 250 uA (V)", "1.0 to 2.0 (model set to 1.5)", f"{VTH_NOM:.3f}",
         f"Id at VGS=VDS={VTH_NOM} V is {ith * 1e6:.1f} uA"),
    ]
    for (vgs, idd, rt), rm in zip(RDS_POINTS, rds):
        rows.append((f"RDS(on) at VGS={vgs:g} V, ID={idd:g} A (ohm)", f"{rt:.3f} max", f"{rm:.4f}", ""))
    rows += [
        ("Ciss at VDS=25 V (pF)", "480 typ", f"{ciss * 1e12:.1f}", ""),
        ("Coss at VDS=25 V (pF)", "130 typ", f"{coss * 1e12:.1f}", ""),
        ("Crss at VDS=25 V (pF)", "61 typ", f"{crss * 1e12:.1f}", ""),
        ("Qgs (nC)", "3.7 max", f"{qgs * 1e9:.2f}", "datasheet at VDS=44 V and ID=11 A, bench at 10 A"),
        ("Qgd (nC)", "8.5 max", f"{qgd * 1e9:.2f}", "fitted, bench at 10 A"),
        ("Qg at VGS=5 V (nC)", "15 max", f"{qg5 * 1e9:.2f}", "check, bench at 10 A"),
        ("gfs at VDS=25 V (S)", "8.3 min", f"{gfs:.2f}",
         f"check at ID=10 A and VGS={vgs_gfs:.2f} V, datasheet tests at 11 A"),
    ]
    for target, vgs, gm in xfer:
        rows.append((f"VGS for ID={target * 1e3:g} mA at VDS=0.8 V (V)", "model output", f"{vgs:.3f}",
                     f"gm={gm:.4g} S"))
    out = os.path.join(RESULTS, "model_check_irlr024n.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["parameter", "datasheet", "model", "note"])
        w.writerows(rows)
    print(card)
    for r in rows:
        print(" | ".join(r))
    return p


if __name__ == "__main__":
    main()

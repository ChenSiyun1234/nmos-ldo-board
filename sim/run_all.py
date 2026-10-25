"""Run every simulation for the NMOS LDO board and write results/.

    python sim/run_all.py              # full run, refits the MOSFET model first
    python sim/run_all.py --skip-fit   # reuse sim/models/irlr024n.lib

Needs numpy, scipy, matplotlib and the ngspice shared library (the one that
ships with KiCad works; point NGSPICE_LIBRARY_PATH at it if it is not found).
"""
import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ldo_sim as L  # noqa: E402
import plotstyle as ps  # noqa: E402
from plotstyle import plt  # noqa: E402

RES = os.path.abspath(os.path.join(HERE, "..", "results"))
DATA = os.path.join(RES, "data")
os.makedirs(DATA, exist_ok=True)

METRICS = []


def metric(group, name, condition, target, value, unit, ok=None, fmt="{:.3g}"):
    """ok=None means the line is reported for information only."""
    if isinstance(value, (float, np.floating)):
        vtxt = fmt.format(value)
    else:
        vtxt = str(value)
    result = "info" if ok is None else ("meets" if ok else "misses")
    METRICS.append(dict(group=group, metric=name, condition=condition, target=target,
                        simulated=vtxt, unit=unit, result=result))
    print(f"  {name:42s} {condition:40s} {vtxt:>10s} {unit:6s} {target:18s} {result}")


def write_csv(name, header, rows):
    with open(os.path.join(DATA, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def cross_time(t, y, level, rising=True, after=0.0):
    m = t >= after
    tt, yy = t[m], y[m]
    idx = np.where((yy[:-1] < level) & (yy[1:] >= level))[0] if rising else \
        np.where((yy[:-1] > level) & (yy[1:] <= level))[0]
    if not len(idx):
        return np.nan
    k = idx[0]
    return float(tt[k] + (level - yy[k]) * (tt[k + 1] - tt[k]) / (yy[k + 1] - yy[k]))


# ======================================================================= DC
def dc_analyses():
    print("DC")
    v = L.op("dc_nominal", 0.5)
    vnom = float(v["vout_t"][0].real)
    metric("DC", "Output voltage", "VIN 1.8 V, 0.5 A", "1.000 V +/-1 %", vnom, "V",
           abs(vnom - 1.0) <= 0.01, "{:.4f}")
    i5 = float(-v["v5#branch"][0].real)
    metric("DC", "5 V bias current", "VIN 1.8 V, 0.5 A", "report", i5 * 1e3, "mA", None, "{:.2f}")
    v0 = L.op("dc_noload", 0.0)
    iq = float(-v0["vin#branch"][0].real)
    metric("DC", "VIN current at no load", "VIN 1.8 V, 0 A (includes 5 mA preload)", "report",
           iq * 1e3, "mA", None, "{:.2f}")

    # accuracy: reference 0.2 %, four 0.1 % divider resistors, 200 uV offset
    base = dict(L.DESIGN)

    def val(k):
        s = base[k]
        return float(s[:-1]) * 1e3 if s.endswith("k") else float(s)
    combos = []
    for sr, sa, sb, st, sbt, so in itertools.product((-1, 1), repeat=6):
        p = dict(referr=0.002 * sr,
                 ra=f"{val('ra') * (1 + 0.001 * sa):.6g}", rb=f"{val('rb') * (1 + 0.001 * sb):.6g}",
                 rtop=f"{val('rtop') * (1 + 0.001 * st):.6g}", rbot=f"{val('rbot') * (1 + 0.001 * sbt):.6g}",
                 vos=200e-6 * so)
        vv = L.op("dc_accuracy", 0.5, params=p)
        combos.append(float(vv["vout_t"][0].real))
    vmin, vmax = min(combos), max(combos)
    metric("DC", "Initial accuracy, worst case low", "ref 0.2 %, R 0.1 %, offset 200 uV", ">= 0.990 V",
           vmin, "V", vmin >= 0.99, "{:.4f}")
    metric("DC", "Initial accuracy, worst case high", "ref 0.2 %, R 0.1 %, offset 200 uV", "<= 1.010 V",
           vmax, "V", vmax <= 1.01, "{:.4f}")

    # load regulation
    lr = L.run("dc_load_reg", L.sources() + "\nILOAD vout_t 0 DC 0\n.dc ILOAD 0 1 0.01")
    il = lr["i-sweep"].real
    vo, vq, vc = lr["vout_t"].real, lr["xb.vout_q"].real, lr["xb.vout"].real
    dv = vo[-1] - vo[0]
    metric("DC", "Load regulation at J2 (sense point)", "0 to 1 A, VIN 1.8 V", "<= 1 mV", abs(dv) * 1e3,
           "mV", abs(dv) <= 1e-3, "{:.3f}")
    metric("DC", "Q1 source voltage rise", "0 to 1 A (copper drop the sense removes)", "report",
           (vq[-1] - vq[0]) * 1e3, "mV", None, "{:.2f}")
    write_csv("load_regulation.csv", ["iload_A", "vout_J2_V", "vout_caps_V", "q1_source_V"],
              zip(il, vo, vc, vq))

    # line regulation
    rows = []
    for iload in (0.0, 1.0):
        ln = L.run("dc_line_reg", L.sources() + f"\nILOAD vout_t 0 DC {iload}\n.dc VIN 1.5 2.0 0.01")
        vin, vo2 = ln["v-sweep"].real, ln["vout_t"].real
        d = vo2[-1] - vo2[0]
        # below the 3 decimals shown, say so instead of printing a bare 0.000
        shown = "< 0.001" if abs(d) * 1e3 < 0.0005 else abs(d) * 1e3
        metric("DC", "Line regulation", f"VIN 1.5 to 2.0 V, {iload:g} A", "<= 1 mV", shown, "mV",
               abs(d) <= 1e-3, "{:.3f}")
        rows += [(iload, a, b) for a, b in zip(vin, vo2)]
    write_csv("line_regulation.csv", ["iload_A", "vin_V", "vout_V"], rows)

    # dropout: UVLO divider opened so the sweep can go below the 1.35 V lockout
    drop_rows = []
    out = {}
    for iload in (0.5, 1.0):
        dr = L.run("dc_dropout", L.sources() + f"\nILOAD vout_t 0 DC {iload}\n.dc VIN 1.8 0.95 -0.0025",
                   params=dict(ruv_bot="1e9"))
        vin, vo3, vg = dr["v-sweep"].real, dr["vout_t"].real, dr["xb.gate"].real
        vreg = vo3[0]
        k = np.where(vo3 < 0.99 * vreg)[0][0]
        x = (0.99 * vreg - vo3[k - 1]) / (vo3[k] - vo3[k - 1])
        vin_d = vin[k - 1] + x * (vin[k] - vin[k - 1])
        vdo = vin_d - 0.99 * vreg
        out[iload] = (vin_d, vdo)
        drop_rows += [(iload, a, b, c) for a, b, c in zip(vin, vo3, vg)]
    metric("DC", "Dropout voltage", "1 A, VOUT 1 % low", "<= 200 mV", out[1.0][1] * 1e3, "mV",
           out[1.0][1] <= 0.2, "{:.0f}")
    metric("DC", "Dropout voltage", "0.5 A, VOUT 1 % low", "report", out[0.5][1] * 1e3, "mV", None, "{:.0f}")
    write_csv("dropout.csv", ["iload_A", "vin_V", "vout_V", "gate_V"], drop_rows)

    # Q1 worst case dissipation
    vw = L.op("dc_worst_power", 1.0, vin=2.0)
    pq = float((vw["xb.vin"][0] - vw["xb.vout_q"][0]).real * -vw["vin#branch"][0].real)
    metric("Thermal", "Q1 dissipation, worst case", "VIN 2.0 V, 1 A", "report", pq, "W", None, "{:.3f}")
    # heat sources for sim/thermal.py: Q1, the 5 V bias circuit and the preload resistor
    with open(os.path.join(DATA, "power.json"), "w") as f:
        json.dump({"q1_W": pq, "bias_W": 5.0 * float(-vw["v5#branch"][0].real),
                   "preload_W": float(vw["xb.vout"][0].real) ** 2 / float(L.DESIGN["rpre"])}, f, indent=1)

    # plots: dropout + load regulation
    fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.3))
    ax = axs[0]
    d = np.array(drop_rows)
    for iload, col, lab in ((1.0, ps.C1, "1 A"), (0.5, ps.C2, "0.5 A")):
        m = d[:, 0] == iload
        ax.plot(d[m, 1], d[m, 2], color=col, label=lab)
    ax.set_xlim(0.95, 1.8)
    ax.set_ylim(0.85, 1.03)
    ax.set_xlabel("VIN (V)")
    ax.set_ylabel("VOUT at J2 (V)")
    ax.set_title("Dropout, simulated")
    vd, vdo = out[1.0]
    ax.plot([vd], [0.99 * vnom], "o", ms=5, color=ps.C1, mec=ps.SURFACE, mew=1.5)
    ps.note(ax, vd + 0.03, 0.99 * vnom - 0.012, f"1 A: VOUT 1 % low at VIN {vd:.3f} V,\n"
            f"dropout {vdo * 1e3:.0f} mV")
    ps.limit_line(ax, 1.5, "VIN min 1.5 V", horizontal=False, where=0.35)
    ax.legend(loc="lower right")
    ax = axs[1]
    ax.plot(il, (vo - vo[0]) * 1e3, color=ps.C1, label="J2, the Kelvin sense point")
    ax.plot(il, (vq - vq[0]) * 1e3, color=ps.C2, label="Q1 source pad")
    ax.set_xlabel("Load current (A)")
    ax.set_ylabel("Change from no load (mV)")
    ax.set_title("Load regulation, simulated")
    ax.legend(loc="upper left")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "dropout_and_load_regulation.png"))
    return vnom


# ======================================================================= AC
def loop_analyses():
    print("Loop gain")
    loads = [0.0, 0.01, 0.1, 1.0]
    rows = []
    bode = {}
    for il in loads:
        f, t = L.loop_gain("lg_sense", il)
        m = L.margins(f, t)
        bode[il] = (f, t)
        fo, to = L.loop_gain("lg_opamp", il, where="opamp")
        mo = L.margins(fo, to)
        rows.append((il, m["fc"], m["pm"], m["gm"], mo["fc"], mo["pm"], mo["gm"]))
        lab = "0 A (5 mA preload only)" if il == 0 else f"{il:g} A"
        metric("Stability", "Crossover frequency", f"{lab}, VIN 1.8 V", "report", m["fc"] / 1e3, "kHz", None,
               "{:.1f}")
        metric("Stability", "Phase margin", f"{lab}, VIN 1.8 V", ">= 45 deg", m["pm"], "deg", m["pm"] >= 45,
               "{:.0f}")
        metric("Stability", "Gain margin", f"{lab}, VIN 1.8 V", ">= 10 dB", m["gm"], "dB", m["gm"] >= 10,
               "{:.1f}")
        write_csv(f"loop_gain_{int(il * 1000)}mA.csv", ["freq_Hz", "mag_dB", "phase_deg"],
                  zip(f, 20 * np.log10(np.abs(t)), np.degrees(np.unwrap(np.angle(t)))))
    write_csv("loop_gain_summary.csv",
              ["iload_A", "fc_Hz", "pm_deg", "gm_dB", "opamp_break_fc_Hz", "opamp_break_pm_deg",
               "opamp_break_gm_dB"], rows)
    pm_op = min(r[5] for r in rows)
    metric("Stability", "Phase margin, op-amp output break", "0 to 1 A (local compensation loop)",
           ">= 45 deg", pm_op, "deg", pm_op >= 45, "{:.0f}")

    # Bode plot
    fig, axs = plt.subplots(2, 1, figsize=(7.4, 5.4), sharex=True)
    for il, col, lab in ((0.0, ps.C1, "0 A"), (0.01, ps.C3, "10 mA"), (1.0, ps.C2, "1 A")):
        f, t = bode[il]
        ph = np.degrees(np.unwrap(np.angle(t)))
        ph -= 360 * np.round(ph[0] / 360)
        m = L.margins(f, t)
        axs[0].semilogx(f, 20 * np.log10(np.abs(t)), color=col,
                        label=f"{lab}: fc {m['fc'] / 1e3:.1f} kHz, PM {m['pm']:.0f} deg")
        axs[1].semilogx(f, ph, color=col)
        axs[1].plot([m["fc"]], [m["pm"] - 180], "o", ms=5, color=col, mec=ps.SURFACE, mew=1.5)
    axs[0].axhline(0, color=ps.AXIS, lw=0.8)
    axs[0].set_ylabel("Loop gain (dB)")
    axs[0].set_title("Loop gain at the Kelvin sense line, Middlebrook double injection, simulated")
    axs[0].legend(loc="upper right")
    axs[0].set_ylim(-60, 100)
    axs[1].axhline(-180, color=ps.AXIS, lw=0.8)
    axs[1].set_ylabel("Phase (deg)")
    axs[1].set_xlabel("Frequency (Hz)")
    axs[1].set_ylim(-280, 20)
    axs[1].set_yticks([-270, -180, -90, 0])
    ps.note(axs[1], 0.01, 0.08, "dots mark the crossover; phase margin is the gap above -180 deg",
            coords="axes fraction")
    axs[1].set_xlim(10, 5e7)
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "loop_gain_bode.png"))


def esr_sweep():
    print("ESR sweep")
    eps = ["5m", "10m", "15m", "25m", "45m"]
    ecs = ["1m", "3m", "10m"]
    rows = []
    for il in (0.0, 1.0):
        for ec in ecs:
            for ep in eps:
                f, t = L.loop_gain("lg_esr", il, params=dict(esr_poly=ep, esr_cer=ec))
                m = L.margins(f, t)
                rows.append((il, ep, ec, m["fc"], m["pm"], m["gm"]))
    write_csv("esr_sweep.csv", ["iload_A", "polymer_esr", "ceramic_esr", "fc_Hz", "pm_deg", "gm_dB"], rows)
    pmw = min(r[4] for r in rows)
    gmw = min(r[5] for r in rows)
    w = min(rows, key=lambda r: r[4])
    metric("Stability", "Worst phase margin over ESR range",
           "polymer 5-45 mohm, ceramic 1-10 mohm, 0 and 1 A", ">= 45 deg", pmw, "deg", pmw >= 45, "{:.0f}")
    metric("Stability", "Worst gain margin over ESR range",
           "polymer 5-45 mohm, ceramic 1-10 mohm, 0 and 1 A", ">= 10 dB", gmw, "dB", gmw >= 10, "{:.1f}")
    print(f"    worst PM case: {w}")

    fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.3), sharey=True)
    xs = [float(e[:-1]) for e in eps]
    for ax, il in zip(axs, (0.0, 1.0)):
        for ec, col in zip(ecs, (ps.C1, ps.C2, ps.C3)):
            ys = [r[4] for r in rows if r[0] == il and r[2] == ec]
            ax.plot(xs, ys, "-o", color=col, ms=4.5, mec=ps.SURFACE, mew=1.2,
                    label=f"ceramic ESR {ec[:-1]} mohm each")
        ps.limit_line(ax, 45, "45 deg target")
        ax.set_xlabel("Polymer capacitor ESR (mohm)")
        ax.set_title(f"Phase margin vs ESR, {'0 A' if il == 0 else '1 A'}, simulated")
        ax.set_ylim(0, 110)
    axs[0].set_ylabel("Phase margin (deg)")
    ps.note(axs[0], 0.03, 0.28, "at 0 A the three ceramic ESR curves overlap", coords="axes fraction")
    axs[1].legend(loc="lower left")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "phase_margin_vs_esr.png"))


def corners():
    print("Stability corners")
    corner_list = [
        ("nominal", {}, "IRLR024N", 1.8),
        ("VGS(th) 1.0 V", {}, "IRLR024N_VTLO", 1.8),
        ("VGS(th) 2.0 V", {}, "IRLR024N_VTHI", 1.8),
        ("VIN 1.5 V", {}, "IRLR024N", 1.5),
        ("VIN 2.0 V", {}, "IRLR024N", 2.0),
        ("polymer C -20 %", dict(c_poly="264u"), "IRLR024N", 1.8),
        ("polymer C +20 %", dict(c_poly="396u"), "IRLR024N", 1.8),
        ("ceramic C -30 %", dict(c_cer="28u"), "IRLR024N", 1.8),
        ("op-amp Ro 20 ohm", dict(ro_ea="20"), "IRLR024N", 1.8),
        ("op-amp Ro 80 ohm", dict(ro_ea="80"), "IRLR024N", 1.8),
        ("Cc and Cp +10 %", dict(cc="1.1n", cp="3.63p"), "IRLR024N", 1.8),
        ("Cc and Cp -10 %", dict(cc="0.9n", cp="2.97p"), "IRLR024N", 1.8),
    ]
    crow = []
    for name, p, q, vin in corner_list:
        for il in (0.0, 1.0):
            f, t = L.loop_gain("lg_corner", il, vin=vin, params=p, qmodel=q)
            m = L.margins(f, t)
            crow.append((name, il, m["fc"], m["pm"], m["gm"]))
    write_csv("stability_corners.csv", ["corner", "iload_A", "fc_Hz", "pm_deg", "gm_dB"], crow)
    pmc = min(r[3] for r in crow)
    gmc = min(r[4] for r in crow)
    wc = min(crow, key=lambda r: r[3])
    metric("Stability", "Worst phase margin over corners", "Vth, VIN, C tolerance, op-amp Ro, Cc/Cp",
           ">= 45 deg", pmc, "deg", pmc >= 45, "{:.0f}")
    metric("Stability", "Worst gain margin over corners", "Vth, VIN, C tolerance, op-amp Ro, Cc/Cp",
           ">= 10 dB", gmc, "dB", gmc >= 10, "{:.1f}")
    print(f"    worst corner: {wc}")


def psrr_and_zout():
    print("PSRR and output impedance")
    curves = {}
    for tag, vin, il in (("1A", 1.8, 1.0), ("10mA", 1.8, 0.01), ("1A_vin1p5", 1.5, 1.0)):
        v = L.run("ac_psrr", L.sources(vin=vin, vin_ac=1) + f"\nILOAD vout_t 0 DC {il}\n.ac dec 40 10 10meg")
        f = v["frequency"].real
        psrr = -20 * np.log10(np.abs(v["vout_t"]))
        curves[tag] = (f, psrr)
        write_csv(f"psrr_{tag}.csv", ["freq_Hz", "psrr_dB"], zip(f, psrr))
    f, p1 = curves["1A"]
    at = lambda fr, c=p1: float(np.interp(np.log10(fr), np.log10(f), c))  # noqa: E731
    metric("PSRR", "PSRR from VIN", "1 kHz, 1 A, VIN 1.8 V", ">= 60 dB", at(1e3), "dB", at(1e3) >= 60, "{:.0f}")
    metric("PSRR", "PSRR from VIN", "10 kHz, 1 A, VIN 1.8 V", ">= 40 dB", at(1e4), "dB", at(1e4) >= 40, "{:.0f}")
    metric("PSRR", "PSRR from VIN", "100 kHz, 1 A, VIN 1.8 V", ">= 30 dB", at(1e5), "dB", at(1e5) >= 30,
           "{:.0f}")
    metric("PSRR", "PSRR from VIN", "1 MHz, 1 A, VIN 1.8 V", "report", at(1e6), "dB", None, "{:.0f}")
    f15, p15 = curves["1A_vin1p5"]
    v15 = float(np.interp(np.log10(1e5), np.log10(f15), p15))
    metric("PSRR", "PSRR from VIN", "100 kHz, 1 A, VIN 1.5 V", "report", v15, "dB", None, "{:.0f}")

    band = f <= 1e6
    k = int(np.argmin(p1[band]))
    metric("PSRR", "Lowest PSRR from 10 Hz to 1 MHz", f"1 A, VIN 1.8 V, at {f[band][k] / 1e3:.0f} kHz", "report",
           float(p1[band][k]), "dB", None, "{:.0f}")

    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    for tag, col, lab, ls in (("1A", ps.C2, "1 A, VIN 1.8 V", "-"), ("1A_vin1p5", ps.C1, "1 A, VIN 1.5 V", (0, (4, 2))),
                              ("10mA", ps.C3, "10 mA, VIN 1.8 V", "-")):
        fx, px = curves[tag]
        ax.semilogx(fx, px, color=col, label=lab, ls=ls)
    ps.note(ax, 0.02, 0.08, "the two 1 A curves overlap", coords="axes fraction")
    ax.set_xlim(10, 1e7)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSRR (dB)")
    ax.set_title("Power supply rejection from VIN to J2, simulated")
    ax.legend(loc="upper right")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "psrr.png"))

    zc = {}
    for il in (0.01, 1.0):
        v = L.run("ac_zout", L.sources() + f"\nILOAD vout_t 0 DC {il} AC 1\n.ac dec 40 10 10meg")
        fz = v["frequency"].real
        z = np.abs(v["vout_t"])
        zc[il] = (fz, z)
        write_csv(f"zout_{int(il * 1000)}mA.csv", ["freq_Hz", "zout_ohm"], zip(fz, z))
    # the regulation band; above about 1 MHz the capacitor ESL sets the impedance
    zpk = max(float(np.max(zc[il][1][zc[il][0] <= 1e6])) for il in zc)
    metric("Transient", "Peak closed loop output impedance", "10 Hz to 1 MHz, 10 mA and 1 A", "report",
           zpk * 1e3, "mohm", None, "{:.1f}")
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    for il, col in ((1.0, ps.C2), (0.01, ps.C3)):
        fz, z = zc[il]
        ax.loglog(fz, z * 1e3, color=col, label="1 A" if il == 1.0 else "10 mA")
    ax.set_xlim(10, 1e7)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("|Zout| (mohm)")
    ax.set_title("Closed loop output impedance at J2, simulated")
    ax.legend(loc="upper left")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "output_impedance.png"))


# ================================================================ transients
def load_transient(vnom):
    print("Load transient")
    t_on, t_off, tstop = 100e-6, 700e-6, 1.4e-3
    res = {}
    for vin in (1.8, 1.5):
        bench = (L.sources(vin=vin, rsrc="10m", lsrc="100n") +
                 f"\nILOAD vout_t 0 DC 0.01 PWL(0 0.01 {t_on} 0.01 {t_on + 0.99e-6} 1.0 "
                 f"{t_off} 1.0 {t_off + 0.99e-6} 0.01)\n.tran 1u {tstop} 0 25n")
        v = L.run(f"tran_load_vin{int(vin * 10)}", bench)
        t, vo = v["time"], v["vout_t"]
        il = np.interp(t, [0, t_on, t_on + 0.99e-6, t_off, t_off + 0.99e-6, tstop],
                       [0.01, 0.01, 1.0, 1.0, 0.01, 0.01])
        v0 = float(np.interp(t_on - 1e-6, t, vo))
        m1 = (t > t_on) & (t < t_off)
        m2 = t > t_off
        und = float((vo[m1] - v0).min())
        ovs = float((vo[m2] - v0).max())

        def recov(mask, t0, band):
            e = np.abs(vo[mask] - v0)
            tt = t[mask]
            k = np.where(e > band)[0]
            return float(tt[k[-1]] - t0) if len(k) else 0.0
        res[vin] = dict(t=t, vo=vo, il=il, v0=v0, und=und, ovs=ovs,
                        r1=recov(m1, t_on, 1e-3), r2=recov(m2, t_off, 1e-3),
                        r5=recov(m1, t_on, 5e-3))
        write_csv(f"load_transient_vin{vin:g}.csv", ["time_s", "iload_A", "vout_V"],
                  zip(t[::4], il[::4], vo[::4]))
    r = res[1.8]
    metric("Transient", "Load step undershoot", "10 mA to 1 A in 1 us, VIN 1.8 V", ">= -30 mV (3 %)",
           r["und"] * 1e3, "mV", r["und"] >= -0.03, "{:.1f}")
    metric("Transient", "Load release overshoot", "1 A to 10 mA in 1 us, VIN 1.8 V", "<= +30 mV (3 %)",
           r["ovs"] * 1e3, "mV", r["ovs"] <= 0.03, "{:.1f}")
    metric("Transient", "Recovery to within 1 mV", "after the 10 mA to 1 A step", "report", r["r1"] * 1e6,
           "us", None, "{:.0f}")
    metric("Transient", "Recovery to within 1 mV", "after the 1 A to 10 mA step", "report", r["r2"] * 1e6,
           "us", None, "{:.0f}")
    r15 = res[1.5]
    metric("Transient", "Load step undershoot", "10 mA to 1 A in 1 us, VIN 1.5 V", ">= -30 mV (3 %)",
           r15["und"] * 1e3, "mV", r15["und"] >= -0.03, "{:.1f}")

    fig, axs = plt.subplots(2, 2, figsize=(9.6, 4.8), sharex="col",
                            gridspec_kw=dict(height_ratios=[1, 2.2]))
    t, vo, il, v0 = r["t"], r["vo"], r["il"], r["v0"]
    for col_i, (a, b, unit, scale) in enumerate(((0, tstop, "ms", 1e3), (t_on - 5e-6, t_on + 45e-6, "us", 1e6))):
        m = (t >= a) & (t <= b)
        axs[0, col_i].plot((t[m] - (0 if col_i == 0 else t_on)) * scale, il[m], color=ps.MUTED, lw=1.3)
        axs[1, col_i].plot((t[m] - (0 if col_i == 0 else t_on)) * scale, (vo[m] - v0) * 1e3, color=ps.C1)
        axs[1, col_i].plot((res[1.5]["t"][(res[1.5]["t"] >= a) & (res[1.5]["t"] <= b)] -
                            (0 if col_i == 0 else t_on)) * scale,
                           (res[1.5]["vo"][(res[1.5]["t"] >= a) & (res[1.5]["t"] <= b)] - res[1.5]["v0"]) * 1e3,
                           color=ps.C2, lw=1.2)
        axs[1, col_i].set_xlabel(f"Time ({unit})" + ("" if col_i == 0 else " after the step starts"))
        ps.limit_line(axs[1, col_i], -30, "-3 % limit", where=0.98)
        ps.limit_line(axs[1, col_i], 30, "+3 % limit", where=0.98)
        axs[1, col_i].set_ylim(-36, 36)
    axs[0, 0].set_ylabel("Load (A)")
    axs[1, 0].set_ylabel("VOUT change at J2 (mV)")
    axs[0, 0].set_title("Load step 10 mA to 1 A at 1 A/us and back, simulated")
    axs[0, 1].set_title("First 45 us of the step")
    axs[1, 0].plot([], [], color=ps.C1, label="VIN 1.8 V")
    axs[1, 0].plot([], [], color=ps.C2, label="VIN 1.5 V")
    axs[1, 0].legend(loc="lower left", bbox_to_anchor=(0.0, 0.10), ncol=2)
    ps.note(axs[1, 1], 0.98, 0.30, f"worst {r['und'] * 1e3:.1f} mV at VIN 1.8 V, the two VIN curves overlap",
            ha="right", coords="axes fraction")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "load_transient.png"))


def line_transient():
    print("Line transient")
    t1, t2, tstop = 100e-6, 600e-6, 1.1e-3
    res = {}
    for il in (1.0, 0.01):
        bench = (f"VIN vin_t gin_t DC 1.5 PWL(0 1.5 {t1} 1.5 {t1 + 10e-6} 2.0 {t2} 2.0 {t2 + 10e-6} 1.5)\n"
                 f"V5 p5v_t gb_t DC 5\nILOAD vout_t 0 DC {il}\n.tran 1u {tstop} 0 50n")
        v = L.run(f"tran_line_{int(il * 1000)}mA", bench)
        t, vo, vin = v["time"], v["vout_t"], v["vin_t"]
        v0 = float(np.interp(t1 - 1e-6, t, vo))
        res[il] = (t, vo, vin, v0)
        write_csv(f"line_transient_{int(il * 1000)}mA.csv", ["time_s", "vin_V", "vout_V"],
                  zip(t[::4], vin[::4], vo[::4]))
        dev = float(np.max(np.abs(vo[t > t1] - v0)))
        metric("Transient", "Line step deviation", f"VIN 1.5 to 2.0 V and back in 10 us, {il:g} A",
               "<= 10 mV (1 %)", dev * 1e3, "mV", dev <= 0.01, "{:.2f}")
    fig, axs = plt.subplots(2, 1, figsize=(7.4, 4.4), sharex=True, gridspec_kw=dict(height_ratios=[1, 2]))
    t, vo, vin, v0 = res[1.0]
    axs[0].plot(t * 1e3, vin, color=ps.MUTED, lw=1.3)
    axs[0].set_ylabel("VIN (V)")
    axs[0].set_title("Line step 1.5 V to 2.0 V in 10 us and back, simulated")
    for il, col, lab in ((1.0, ps.C2, "1 A"), (0.01, ps.C3, "10 mA")):
        t, vo, vin, v0 = res[il]
        axs[1].plot(t * 1e3, (vo - v0) * 1e3, color=col, label=lab)
    axs[1].set_ylabel("VOUT change at J2 (mV)")
    axs[1].set_xlabel("Time (ms)")
    axs[1].legend(loc="upper right")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "line_transient.png"))


def soft_start(vnom):
    print("Soft start, enable, sequencing")
    ten, toff, tstop = 1e-3, 16e-3, 40e-3
    res = {}
    for tag, load in (("noload", "ILOAD vout_t 0 DC 0"), ("1ohm", "RLOAD vout_t 0 1")):
        bench = (L.sources(en=f"DC 0 PWL(0 0 {ten} 0 {ten + 1e-6} 3.3 {toff} 3.3 {toff + 1e-6} 0)") +
                 f"\n{load}\n.tran 10u {tstop} 0 2u")
        v = L.run(f"tran_softstart_{tag}", bench, nodeset=L.NODESET_OFF)
        t, vo, vs, iin = v["time"], v["vout_t"], v["xb.vset"], -v["vin#branch"]
        res[tag] = (t, vo, vs, iin)
        write_csv(f"soft_start_{tag}.csv", ["time_s", "vout_V", "vset_V", "iin_A"],
                  zip(t[::5], vo[::5], vs[::5], iin[::5]))
    t, vo, vs, iin = res["noload"]
    t10 = cross_time(t, vo, 0.1 * vnom, after=ten)
    t90 = cross_time(t, vo, 0.9 * vnom, after=ten)
    t99 = cross_time(t, vo, 0.99 * vnom, after=ten)
    on = (t > ten) & (t < toff)
    vpk = float(vo[on].max())
    metric("Startup", "Soft start rise time 10 to 90 %", "EN high, no load", "1 to 10 ms", (t90 - t10) * 1e3,
           "ms", 1e-3 <= t90 - t10 <= 10e-3, "{:.2f}")
    metric("Startup", "Time from EN to 99 %", "no load", "report", (t99 - ten) * 1e3, "ms", None, "{:.1f}")
    metric("Startup", "Peak VOUT during soft start", "no load", "<= 1.010 V (1 % overshoot)", vpk, "V",
           vpk <= 1.010, "{:.4f}")
    ipk = float(iin[on].max())
    metric("Startup", "Peak input current at startup", "no load (output capacitor charging)", "<= 0.5 A",
           ipk, "A", ipk <= 0.5, "{:.2f}")
    t1, vo1, vs1, iin1 = res["1ohm"]
    on1 = (t1 > ten) & (t1 < toff)
    ipk1 = float(iin1[on1].max())
    vpk1 = float(vo1[on1].max())
    metric("Startup", "Peak input current at startup", "1 ohm load", "report", ipk1, "A", None, "{:.2f}")
    metric("Startup", "Peak VOUT during soft start", "1 ohm load", "<= 1.010 V (1 % overshoot)", vpk1, "V",
           vpk1 <= 1.010, "{:.4f}")
    t_d = cross_time(t, vo, 0.1 * vnom, rising=False, after=toff)
    metric("Startup", "Output discharge after EN low", "no load, to 10 %", "report", (t_d - toff) * 1e3, "ms",
           None, "{:.1f}")

    fig, axs = plt.subplots(2, 1, figsize=(7.4, 4.6), sharex=True, gridspec_kw=dict(height_ratios=[2, 1.2]))
    for tag, col, lab in (("noload", ps.C1, "no load"), ("1ohm", ps.C2, "1 ohm load (1 A)")):
        tt, vv, ss, ii = res[tag]
        axs[0].plot(tt * 1e3, vv, color=col, label=f"VOUT, {lab}")
        axs[1].plot(tt * 1e3, ii, color=col, label=lab)
    tt, vv, ss, ii = res["noload"]
    axs[0].plot(tt * 1e3, ss, color=ps.C3, lw=1.3, label="soft start node VSET")
    axs[0].set_ylabel("Voltage (V)")
    axs[0].set_title("Enable at 1 ms and disable at 16 ms, simulated")
    axs[0].legend(loc="upper right")
    axs[1].set_ylabel("VIN current (A)")
    axs[1].set_xlabel("Time (ms)")
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "soft_start.png"))

    # VIN arrives after the bias and EN: the UVLO holds EN low, then soft start runs
    bench = ("VIN vin_t gin_t DC 0 PWL(0 0 5m 0 6m 1.8)\nV5 p5v_t gb_t DC 5\nILOAD vout_t 0 DC 0\n"
             ".tran 20u 45m 0 10u")
    v = L.run("tran_vin_last", bench, nodeset=L.NODESET_OFF)
    t, vo, en, vin = v["time"], v["vout_t"], v["xb.en_int"], v["vin_t"]
    t_uv = cross_time(t, vin, 0.405 * (1 + 23.2 / 10.0))
    t_en = cross_time(t, en, 2.5)
    metric("Startup", "UVLO release delay after VIN good", "VIN ramps after 5 V and EN", "report",
           (t_en - t_uv) * 1e3, "ms", None, "{:.1f}")
    vpk2 = float(vo.max())
    metric("Startup", "Peak VOUT when VIN comes up last", "VIN 0 to 1.8 V in 1 ms, EN already high",
           "<= 1.010 V (1 % overshoot)", vpk2, "V", vpk2 <= 1.010, "{:.4f}")
    write_csv("startup_vin_last.csv", ["time_s", "vin_V", "en_int_V", "vout_V"],
              zip(t[::5], vin[::5], en[::5], vo[::5]))
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.plot(t * 1e3, vin, color=ps.MUTED, lw=1.3, label="VIN")
    ax.plot(t * 1e3, en / 5.0, color=ps.C3, lw=1.3, label="EN_INT / 5")
    ax.plot(t * 1e3, vo, color=ps.C1, label="VOUT")
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Voltage (V)")
    ax.set_title("VIN arriving after the 5 V bias: the UVLO waits, then soft start, simulated")
    ax.legend(loc="center left", bbox_to_anchor=(0.22, 0.55))
    fig.tight_layout()
    ps.save(fig, os.path.join(RES, "startup_vin_last.png"))


PARTS = ["models", "dc", "loop", "esr", "corners", "psrr", "load", "line", "startup", "thermal"]


def run_part(part, args):
    """One analysis group. Each group runs in its own process because the
    ngspice shared library slowly runs out of output memory over hundreds of
    runs in one process."""
    if part == "models":
        if not args.skip_fit:
            import fit_mosfet
            print("Fitting the IRLR024N model")
            fit_mosfet.main()
        import check_opamp
        print("Checking the OPA365 macromodel")
        check_opamp.main()
        return
    vnom = 1.0003
    if part == "dc":
        vnom = dc_analyses()
        with open(os.path.join(DATA, "vnom.txt"), "w") as f:
            f.write(repr(vnom))
    else:
        try:
            with open(os.path.join(DATA, "vnom.txt")) as f:
                vnom = float(f.read())
        except FileNotFoundError:
            pass
    if part == "loop":
        loop_analyses()
    elif part == "esr":
        esr_sweep()
    elif part == "corners":
        corners()
    elif part == "psrr":
        psrr_and_zout()
    elif part == "load":
        load_transient(vnom)
    elif part == "line":
        line_transient()
    elif part == "startup":
        soft_start(vnom)
    elif part == "thermal":
        try:
            import thermal
        except ImportError:
            print("thermal model not present yet, skipped")
            return
        thermal.main(metric)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fit", action="store_true", help="reuse the fitted MOSFET model")
    ap.add_argument("--part", choices=PARTS, help="run one analysis group in this process")
    args = ap.parse_args()
    if args.part:
        run_part(args.part, args)
        with open(os.path.join(DATA, f"metrics_{args.part}.json"), "w") as f:
            json.dump(METRICS, f, indent=1)
        return
    t0 = time.time()
    rows = []
    for part in PARTS:
        cmd = [sys.executable, os.path.abspath(__file__), "--part", part]
        if args.skip_fit:
            cmd.append("--skip-fit")
        print(f"==== {part}", flush=True)
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit(f"part {part} failed")
        with open(os.path.join(DATA, f"metrics_{part}.json")) as f:
            rows += json.load(f)
    path = os.path.join(RES, "metrics.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "metric", "condition", "target", "simulated", "unit",
                                          "result"])
        w.writeheader()
        w.writerows(rows)
    miss = [m for m in rows if m["result"] == "misses"]
    shown = os.path.relpath(path, os.path.dirname(RES)).replace(os.sep, "/")
    print(f"\n{len(rows)} metrics written to {shown}; {len(miss)} miss their target")
    for m in miss:
        print("   MISS:", m)
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

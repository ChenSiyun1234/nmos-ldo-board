"""Testbenches for the NMOS LDO board. Every netlist that runs is written to
sim/netlists/generated/ first, so each result can be traced to a file."""
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ngspice_shared as ng  # noqa: E402

GEN = os.path.join(HERE, "netlists", "generated")
os.makedirs(GEN, exist_ok=True)
MODELS = os.path.join(HERE, "models").replace("\\", "/")
BOARD = os.path.join(HERE, "netlists", "ldo_board.cir")

# Final component values (same as the schematic). Changing a value here
# changes every simulation.
DESIGN = dict(
    rtop="2.55k", rbot="10.2k", ra="5.62k", rb="10k", css="0.47u",
    rc="127k", cc="1n", cp="3.3p", riso="47", rgpd="100k", rpre="200",
)

NOMINAL_VIN = 1.8


def _board_text(qmodel="IRLR024N"):
    with open(BOARD) as f:
        text = f.read()
    if qmodel != "IRLR024N":
        text = re.sub(r"^(MQ1 \S+ \S+ \S+) IRLR024N$", rf"\1 {qmodel}", text, flags=re.M)
    return text


def _params(over):
    p = dict(DESIGN)
    p.update(over or {})
    return " ".join(f"{k}={v}" for k, v in p.items())


# Starting guesses for the DC operating point. The loop has more than 100 dB
# of DC gain through an exponential device, so Newton needs a nearby start.
NODESET_ON = (".nodeset v(xb.gate)=2.7 v(xb.eaout)=2.7 v(xb.eaout_u)=2.7 v(vout_t)=1.0 "
              "v(xb.vout)=1.0 v(xb.fb)=0.8 v(xb.vset)=0.8 v(xb.en_int)=5 v(xb.en_n)=0")
NODESET_OFF = (".nodeset v(xb.gate)=0 v(xb.eaout)=0 v(xb.eaout_u)=0 v(vout_t)=0 "
               "v(xb.vout)=0 v(xb.vset)=0 v(xb.en_int)=0 v(xb.en_n)=5")


# Only these vectors are stored. Saving every node of a long transient runs
# the shared library out of output memory.
SAVE = (".save vout_t vin_t xb.vin xb.vout xb.vout_q xb.gate xb.eaout xb.eaout_u xb.vset xb.fb "
        "xb.fb_top xb.vref xb.en_int xb.en_n xb.uv_sense vin#branch v5#branch "
        "v.xb.vlb#branch v.xb.vlb2#branch")


def build(name, bench, params=None, qmodel="IRLR024N", options="", nodeset=NODESET_ON):
    """Write a complete netlist: models, board subcircuit, bench, analysis."""
    # model paths relative to the generated netlist, so the files carry no machine path
    rel = os.path.relpath(MODELS, GEN).replace("\\", "/")
    lines = [f"* {name}",
             f".include {rel}/irlr024n.lib",
             f".include {rel}/opa365.lib",
             f".include {rel}/ref3012.lib",
             f".include {rel}/passives.lib",
             f".include {rel}/tps3808.lib",
             _board_text(qmodel),
             f"XB vin_t gin_t vout_t 0 p5v_t en_t gb_t LDO_BOARD {_params(params)}",
             ".option temp=25 tnom=25 method=gear " + options,
             nodeset or "",
             SAVE,
             bench.strip(),
             ".end", ""]
    path = os.path.join(GEN, f"{name}.cir")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def run(name, bench, params=None, qmodel="IRLR024N", options="", nodeset=NODESET_ON):
    path = build(name, bench, params, qmodel, options, nodeset)
    vec, _ = ng.run(path)
    return vec


# ---------------------------------------------------------------- sources
def sources(vin=NOMINAL_VIN, vin_ac=0, v5=5.0, v5_ac=0, en=None, rsrc="0", lsrc="0"):
    """VIN source with optional wiring impedance, 5 V bias, EN left floating
    (pulled up on the board) unless a value or source string is given."""
    s = []
    if rsrc == "0" and lsrc == "0":
        s.append(f"VIN vin_t gin_t DC {vin} AC {vin_ac}")
    else:
        s.append(f"VIN vs gin_t DC {vin} AC {vin_ac}")
        s.append(f"RSRC vs vs2 {rsrc}")
        s.append(f"LSRC vs2 vin_t {lsrc}")
    s.append(f"V5 p5v_t gb_t DC {v5} AC {v5_ac}")
    if en is not None:
        s.append(f"VEN en_t gb_t {en}")
    return "\n".join(s)


# ---------------------------------------------------------------- analyses
BREAKS = {
    # name: (voltage source param, current source param, driver node a,
    #        driven node b, branch current vector of the series source)
    "sense": ("lb_vac", "lb_iac", "vout_t", "xb.fb_top", "v.xb.vlb#branch"),
    "opamp": ("lb2_vac", "lb2_iac", "xb.eaout_u", "xb.eaout", "v.xb.vlb2#branch"),
}


def loop_gain(name, iload, vin=NOMINAL_VIN, params=None, qmodel="IRLR024N",
              fstart=10, fstop=50e6, ppd=40, where="sense"):
    """Middlebrook double injection. A voltage source vz sits between the
    driver node a and the driven node b (V(b) = V(a) + vz) and a current
    source can inject into b.
      Tv = -V(a)/V(b) with the voltage source on
      Ti = -i_d/i_L   with the current source on, i_d = current from a to b
      T  = (Tv*Ti - 1)/(Tv + Ti + 2)
    'sense' breaks the Kelvin sense line, 'opamp' breaks the op-amp output pin
    (every loop passes through it, including the local compensation loop)."""
    kv, ki, na, nb, src = BREAKS[where]
    bench = (sources(vin=vin) + f"\nILOAD vout_t 0 DC {iload}\n"
             f".ac dec {ppd} {fstart} {fstop}")
    pv = dict(params or {})
    pv.update({kv: 1, ki: 0})
    v1 = run(name + "_v", bench, pv, qmodel)
    pi = dict(params or {})
    pi.update({kv: 0, ki: 1})
    v2 = run(name + "_i", bench, pi, qmodel)
    f = v1["frequency"].real
    tv = -v1[na] / v1[nb]
    ib = v2[src]                # SPICE branch current: from b through the source into a
    ti = ib / (1 - ib)          # so i_d = -ib and i_L = 1 - ib
    t = (tv * ti - 1) / (tv + ti + 2)
    return f, t


def margins(f, t):
    """Crossover frequency, phase margin and gain margin of loop gain t."""
    mag = 20 * np.log10(np.abs(t))
    ph = np.degrees(np.unwrap(np.angle(t)))
    # bring the low frequency phase to the range (-180, 180]
    ph -= 360 * np.round(ph[0] / 360)
    out = {"fc": np.nan, "pm": np.nan, "gm": np.nan, "f180": np.nan}
    idx = np.where((mag[:-1] > 0) & (mag[1:] <= 0))[0]
    if len(idx):
        k = idx[0]
        x = (0 - mag[k]) / (mag[k + 1] - mag[k])
        out["fc"] = float(10 ** (np.log10(f[k]) + x * (np.log10(f[k + 1]) - np.log10(f[k]))))
        phc = ph[k] + x * (ph[k + 1] - ph[k])
        out["pm"] = float(180 + phc)
    # first crossing of -180 degrees above the crossover
    j = np.where((ph[:-1] > -180) & (ph[1:] <= -180))[0]
    if len(j):
        k = j[0]
        x = (-180 - ph[k]) / (ph[k + 1] - ph[k])
        out["f180"] = float(10 ** (np.log10(f[k]) + x * (np.log10(f[k + 1]) - np.log10(f[k]))))
        out["gm"] = float(-(mag[k] + x * (mag[k + 1] - mag[k])))
    return out


def op(name, iload, vin=NOMINAL_VIN, params=None, qmodel="IRLR024N", extra=""):
    bench = sources(vin=vin) + f"\nILOAD vout_t 0 DC {iload}\n{extra}\n.op"
    return run(name, bench, params, qmodel)

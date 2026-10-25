"""Check the OPA365 macromodel against the datasheet numbers it is built from.
Writes ../results/model_check_opa365.csv."""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ngspice_shared as ng  # noqa: E402

WORK = os.path.join(HERE, "netlists", "generated")
os.makedirs(WORK, exist_ok=True)
MODELS = os.path.join(HERE, "models").replace("\\", "/")


def run(text, tag):
    path = os.path.join(WORK, f"opamp_{tag}.cir")
    with open(path, "w") as f:
        f.write(text)
    vec, _ = ng.run(path)
    return vec


def main():
    rel = os.path.relpath(MODELS, WORK).replace("\\", "/")
    head = f".include {rel}/opa365.lib\nVCC vcc 0 DC 5\n"
    # open loop gain: very slow DC feedback holds the output at mid supply
    ol = run("* open loop\n" + head +
             "VIN inp 0 DC 2.5 AC 1\n"
             "XU inp inn vcc 0 out OPA365\n"
             "RF out inn 1G\nCF inn 0 1\n"
             "RL out 0 10k\n"
             ".ac dec 50 0.1 1g\n.end\n", "aol")
    f = ol["frequency"].real
    a = ol["out"] / ol["inp"]
    a_db = 20 * np.log10(np.abs(a))
    k = int(np.argmax(a_db < 0))
    fu = float(np.interp(0, a_db[k - 1:k + 1][::-1], f[k - 1:k + 1][::-1]))
    ph_u = float(np.degrees(np.angle(a[k])))
    aol_db = float(a_db[np.argmin(abs(f - 1))])
    gbw = float(np.abs(a[np.argmin(abs(f - 1e6))]) * f[np.argmin(abs(f - 1e6))])
    # slew rate in a unity gain buffer, 1 V to 4 V step
    sr = run("* slew\n" + head +
             "VIN inp 0 DC 1 PULSE(1 4 1u 1n 1n 5u 10u)\n"
             "XU inp out vcc 0 out OPA365\nRL out 0 10k\n"
             ".tran 1n 4u\n.end\n", "slew")
    t, vo = sr["time"], sr["out"]
    t20 = float(np.interp(1.6, vo[t > 1e-6], t[t > 1e-6]))
    t80 = float(np.interp(3.4, vo[t > 1e-6], t[t > 1e-6]))
    slew = 1.8 / (t80 - t20)
    # output swing with a 100 kohm load (the gate pull-down in this design)
    sw = run("* swing\n" + head +
             "VIN inp 0 DC 0\nVREF inn 0 DC 2.5\n"
             "XU inp inn vcc 0 out OPA365\nRL out 0 100k\n"
             ".dc VIN 0 5 0.01\n.end\n", "swing")
    vmax = float(np.max(sw["out"]))
    vmin = float(np.min(sw["out"]))
    iq = run("* supply current\n" + head +
             "VIN inp 0 DC 2.5\nXU inp out vcc 0 out OPA365\n.op\n.end\n", "iq")
    icc = float(-iq["vcc#branch"][0])

    rows = [
        ("open loop gain at 1 Hz (dB)", "120 typ", f"{aol_db:.1f}"),
        ("gain bandwidth, |A| x f at 1 MHz (MHz)", "50 typ", f"{gbw / 1e6:.1f}"),
        ("unity gain crossing (MHz)", "not specified", f"{fu / 1e6:.1f}"),
        ("phase at unity gain (deg)", "not specified", f"{ph_u:.1f}"),
        ("slew rate, 20 to 80 % (V/us)", "25 typ", f"{slew / 1e6:.1f}"),
        ("max output, 100 kohm load (V)", "within about 10 mV of 5 V", f"{vmax:.4f}"),
        ("min output, 100 kohm load (V)", "within about 10 mV of 0 V", f"{vmin:.4f}"),
        ("supply current (mA)", "4.6 typ", f"{icc * 1e3:.2f}"),
    ]
    out = os.path.join(HERE, "..", "results", "model_check_opa365.csv")
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["parameter", "datasheet", "model"])
        w.writerows(rows)
    for r in rows:
        print(" | ".join(r))


if __name__ == "__main__":
    main()

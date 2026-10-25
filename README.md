# NMOS LDO Board

A linear regulator board that makes 1.0 V at up to 1 A from a 1.5 to 2.0 V rail. I designed the circuit, laid out a four-layer board in KiCad 10, and checked it with ngspice and a thermal model of the routed copper. The results below are from simulation.

![Board render](docs/img/board_angle.png)

| Top | Bottom |
|---|---|
| ![Top view](docs/img/board_top.png) | ![Bottom view](docs/img/board_bottom.png) |

## Design

I used an N-channel MOSFET, the IRLR024N, as a source follower. A P-channel pass device on a 1.5 V input only gets about 1.5 V of gate drive, so its on-resistance is high. A separate 5 V bias rail powers the error amplifier and lets the gate rise well above the output. That keeps the dropout at 90 mV at 1 A.

The error amplifier is an OPA365 set up as a PI controller. The follower's pole moves with load current, so the crossover goes from about 2 kHz at no load to 180 kHz at 1 A. I put the PI zero at 1.25 kHz, just under the light-load crossover, and added a 5 mA preload so the pole never drops too low.

The divider senses the output right at the terminal block through two net ties, so the copper drop between Q1 and the load does not show up at the output. A TPS3808 holds the regulator off until VIN is above about 1.37 V, and an RC filter on the set point gives a 3.7 ms soft start.

![Schematic](docs/img/schematic.png)

## Results

| | Target | Simulated |
|---|---|---|
| Output voltage at the terminals | 1.000 V ±1% | 1.000 V |
| Dropout at 1 A | ≤ 200 mV | 90 mV |
| Load step, 10 mA to 1 A in 1 µs | within ±30 mV | −8.7 / +7.4 mV |
| PSRR at 1 / 10 / 100 kHz | ≥ 60 / 40 / 30 dB | 99 / 81 / 63 dB |
| Worst phase margin over load, ESR and part tolerances | ≥ 45° | 56° |
| Soft start, 10 to 90% | 1 to 10 ms | 3.7 ms |
| Q1 junction at 1 W, 25 °C still air | ≤ 125 °C | 58 °C |

I broke the loop at the sense line and measured the loop gain at 0 A, 10 mA, 100 mA and 1 A. Then I swept the output capacitor ESR and the part tolerances. The worst case was 56° of phase margin at no load, with the polymer capacitor 20% high.

![Loop gain](results/loop_gain_bode.png)

For the load step I went from 10 mA to 1 A at 1 A/µs. The output dropped 8.7 mV and was back within 1 mV after about 0.3 ms.

![Load step](results/load_transient.png)

The thermal model uses the copper of all four layers. Q1 dissipates 1 W with 2.0 V in and 1 A out. The 30 vias under and next to its tab keep the junction at 58 °C. Without them it reaches 64 °C.

![Board temperature](results/thermal_map.png)

## Board

The board is 54 × 42 mm with four layers, and both inner layers are solid ground. The power path runs in one straight line along the top edge, from J1 through the input capacitors, Q1 and the output capacitors to J2. The reference and feedback parts return to a separate quiet ground that meets the main ground only at the output terminal. ERC and DRC are clean, and `fab/` has the Gerbers, drill file, BOM and pick-and-place file.

## Files

```
hardware/  KiCad project
fab/       Gerbers, drill, BOM, pick and place, STEP
sim/       ngspice models and the Python that runs each analysis
results/   plots, metrics.csv and the data behind each plot
scripts/   Python that generates the schematic and board files
docs/      design notes, schematic PDF and renders
```

To rerun the simulations you need Python 3 with numpy, scipy, matplotlib and pillow, plus the ngspice shared library. The one that ships with KiCad works.

```
python sim/run_all.py
```

The hand calculations, the other plots, the layout notes and the part models are in [docs/design-notes.md](docs/design-notes.md).

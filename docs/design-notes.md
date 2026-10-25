# Design notes

These are the calculations and checks behind the README. Every number here is from ngspice or the thermal model, and the full list is in `results/metrics.csv`.

## Full spec table

| Parameter | Condition | Target | Simulated |
|---|---|---|---|
| Output voltage at J2 | VIN 1.8 V, 0.5 A | 1.000 V ±1% | 1.0003 V |
| Initial accuracy, worst case | 0.2% reference, 0.1% resistors, 200 µV offset | 0.990 to 1.010 V | 0.9969 to 1.0037 V |
| Load regulation at J2 | 0 to 1 A | ≤ 1 mV | 0.001 mV |
| Line regulation | VIN 1.5 to 2.0 V, at 0 A and 1 A | ≤ 1 mV | < 0.001 mV |
| Dropout | 1 A, VOUT 1% low | ≤ 200 mV | 90 mV |
| Load step | 10 mA to 1 A and back at 1 A/µs | within ±30 mV | −8.7 / +7.4 mV |
| Line step | VIN 1.5 to 2.0 V in 10 µs and back, 1 A | within ±10 mV | 0.08 mV |
| PSRR from VIN | 1 kHz / 10 kHz / 100 kHz, 1 A | ≥ 60 / 40 / 30 dB | 99 / 81 / 63 dB |
| Phase margin | 0 A, 10 mA, 100 mA, 1 A | ≥ 45° | 59°, 79°, 108°, 81° |
| Worst phase margin | ESR range and part corners | ≥ 45° | 56° |
| Worst gain margin | same sweeps | ≥ 10 dB | 29.6 dB |
| Soft start, 10 to 90% | EN high, no load | 1 to 10 ms | 3.69 ms |
| Inrush current | no load | ≤ 0.5 A | 0.35 A |
| Peak VOUT at startup | EN first, or VIN last | ≤ 1.010 V | 1.0003 V |
| Q1 junction temperature | 1.00 W in Q1, 25 °C still air | ≤ 125 °C | 58 °C |
| 5 V bias current | 0.5 A load | report | 5.17 mA |

The schematic PDF is [schematic.pdf](schematic.pdf).

## How the circuit works

Q1 is a logic-level NMOS in DPAK. Its drain tab sits on the VIN copper and its source feeds the output capacitors. U1 runs from the 5 V rail, compares the divided output with a 0.8 V set point, and drives the gate through a 47 Ω resistor, R5.

R2 and R3 read VOUT and ground at the J2 pads through net ties NT1 and NT2, so the copper in the power path does not move the output.

EN on J3 and the TPS3808 supervisor both feed the internal enable. When either one is low, Q3 empties the soft-start capacitor, D1 and R13 pull the feedback node up so U1 turns the gate off, and Q4 discharges the output through 22 Ω. U3 waits 20 ms after VIN passes about 1.37 V and trips again below 1.345 V, so the output always comes up through soft start.

## Hand calculations

### Set point

V_SET = 1.25 V × R8 / (R7 + R8) = 1.25 × 10k / 15.62k = 0.8003 V

V_OUT = V_SET × (R2 + R3) / R3 = 0.8003 × 12.75k / 10.2k = 1.0003 V

I used 0.1% thin film parts for R2, R3, R7 and R8. With the 0.2% reference and 200 µV of op amp offset, the worst-case corners give 0.9969 V and 1.0037 V, inside the ±1% target.

### Gate drive

At 1 A the fitted Q1 model needs V_GS = 2.21 V, so the gate sits near 3.21 V. U1 can swing to 4.98 V into the 100 kΩ gate pull-down, which leaves 1.77 V of headroom at full load. Near dropout the gate goes to the top of U1's swing and Q1 sees about 4 V of gate drive.

### Dropout

V_DO ≈ 1 A × (86 mΩ + 3.6 mΩ) ≈ 90 mV

86 mΩ is the fitted on-resistance at about 4 V of gate drive, and 3.6 mΩ is the copper. The datasheet maximum of 110 mΩ at 4 V would still give about 115 mV, well under 200 mV. At the 1.5 V minimum input there is 500 mV of headroom.

### Soft start

R7, R8 and C12 also filter the reference.

τ = (R7 ∥ R8) × C12 = 3.60 kΩ × 0.47 µF = 1.69 ms

That puts the reference noise corner at 94 Hz. The 10 to 90% rise is 2.2τ = 3.7 ms, and the simulation gives 3.69 ms. The steepest slope into 450 µF of output capacitance works out to about 0.27 A of inrush. The simulation shows 0.35 A, because the loop has to catch up once the gate passes threshold.

### Compensation

U1 runs as a PI controller. R4 and C9 set the gain and the zero, and C10 adds a high-frequency pole.

K_P = R4 / R2 = 127k / 2.55k = 50
f_Z = 1 / (2π R4 C9) = 1.25 kHz
f_P = 1 / (2π R4 C10) = 380 kHz

The plant is the source follower driving the output capacitors. Its pole is at gm / (2π C_OUT), and gm grows with load current.

| Load | Q1 gm | Follower pole | Crossover | Phase margin |
|---|---|---|---|---|
| 0 A, 5 mA preload | about 0.09 S | about 30 Hz | 1.8 kHz | 59° |
| 10 mA | 0.17 S | 59 Hz | 4.2 kHz | 79° |
| 100 mA | 1.09 S | 380 Hz | 23.4 kHz | 108° |
| 1 A | 4.03 S | 1.4 kHz | 180 kHz | 81° |

At light load the integrator and the follower pole push the phase toward −180°, so I put the zero just below the light-load crossover. The 5 mA preload, R1, keeps gm from falling far enough to pull the crossover under the zero.

At 1 A the crossover is where K_P × gm × Z_COUT falls to one. With gm = 4 S and about 6 mΩ from the polymer ESR in parallel with the ceramics, that lands near 200 kHz, and the simulation gives 180 kHz. R5 isolates U1 from about 2 nF of gate capacitance.

### Thermal

P_Q1 = (2.0 V − 1.0 V) × 1 A = 1.0 W

T_J = 25 °C + 1.0 W × 32.4 K/W ≈ 57 °C

R_θJC is 3.3 K/W from the datasheet, and the rest of R_θJA comes from the board model. The model gives 58 °C because U1 and R1 add about 30 mW. With 35% less surface cooling the junction reaches 68 °C, which still allows 82 °C ambient.

### Capacitors

The output has one 330 µF polymer tantalum with 15 mΩ ESR for the first microseconds of a load step, plus three 47 µF X5R 1206 parts for low ESR and ESL at high frequency. I modeled each ceramic as 40 µF to allow for DC bias. The phase margin stays at 57° or more across 5 to 45 mΩ of polymer ESR and 1 to 10 mΩ per ceramic, so the loop does not depend on ESR.

For the load step, V_GS has to rise from 1.70 V to 2.21 V. With a gain of 50 that takes about 10 mV of error at the output, and the simulation gives 8.7 mV because the integrator and the output capacitors help.

The input has a second 330 µF polymer and a 47 µF ceramic between J1 and the Q1 tab. The load step includes 10 mΩ and 100 nH of input wiring, and the result is the same at 1.5 V and 1.8 V input.

## More simulation results

I measured loop gain with Middlebrook's double injection at the sense line, one run with a series voltage source and one with a shunt current source.

Phase margin against capacitor ESR. The ceramic ESR only matters at full load.

![Phase margin against ESR](../results/phase_margin_vs_esr.png)

The corner sweep moves the Q1 threshold by ±0.5 V, VIN from 1.5 to 2.0 V, the capacitors by their tolerance, the op amp output resistance, and the compensation parts. The worst gain margin was 29.6 dB, with the op amp output resistance at 20 Ω and a 1 A load.

Line step.

![Line step](../results/line_transient.png)

PSRR and output impedance. Between 10 Hz and 1 MHz the PSRR is lowest at 355 kHz, where it is still 50 dB. The output impedance peaks at 84 mΩ near 2 kHz with a 10 mA load. Above 1 MHz the capacitor ESL sets both curves.

![PSRR](../results/psrr.png)

![Output impedance](../results/output_impedance.png)

Dropout and load regulation. The Q1 source pad rises 2.6 mV from 0 to 1 A because of the copper between Q1 and J2. The sense lines remove it, so J2 moves by 0.001 mV.

![Dropout and load regulation](../results/dropout_and_load_regulation.png)

Soft start and sequencing. With EN already high and VIN arriving last, U3 holds the regulator off for 20.4 ms after VIN is good, and then the output ramps through soft start with no overshoot.

![Soft start](../results/soft_start.png)

![VIN last](../results/startup_vin_last.png)

## Layout notes

| | |
|---|---|
| Size | 54 × 42 mm, four M3 holes |
| Stackup | 4 layers, 1.6 mm, 35 µm copper on every layer |
| Top | parts, the VIN and VOUT pours, the quiet ground pour, ground fill |
| Inner layers | solid ground |
| Bottom | the VIN heat spreader, ground fill, the sense pair, the EN line and a few short jumpers |
| Checks | ERC with no errors or warnings; DRC with schematic parity and no violations |
| Outputs | Gerber X2, Excellon drill, fab notes, BOM, pick and place, STEP, renders |

- I aimed for 50 × 40 mm. The three terminal blocks, four M3 holes and the straight power row needed 54 × 42 mm.
- J1, C1, C2, Q1, C3 to C6 and J2 sit in one line along the top edge, so the power loop stays short and the control parts stay out of it.
- The Q1 tab sits on a 25 × 8 mm VIN pour. Thirty 0.3 mm vias under and next to the tab tie it to a 26 × 15 mm VIN pour on the bottom. The vias inside the tab pad are marked in [`fab/fab_notes.txt`](../fab/fab_notes.txt) to be filled and capped so solder does not wick into them.
- `sim/pcb_parasitics.py` solves the copper as a resistor grid. J1 to the Q1 tab is 0.38 mΩ, the Q1 source to J2 is 2.54 mΩ, and the ground return is 0.46 mΩ. The board netlist uses these values, rounded up.
- U2, C11, R3, R8, C12 and Q3 return to a separate quiet ground island that meets the main ground only at J2, so the set point does not see the ripple of the power ground.
- U1, R5 and the compensation parts sit just below Q1, so the gate trace is short and the feedback node stays small.
- I checked each symbol against its footprint. Q1 has its gate on pad 1, the drain on the tab and the source on pad 3, and the SOT parts, the diode band and the polymer capacitor anode all match their datasheets.

## Key parts

50 parts on 37 lines. The full list with part numbers is [`fab/bom.csv`](../fab/bom.csv).

| Ref | Part | MPN |
|---|---|---|
| Q1 | N-channel MOSFET, 55 V, 65 mΩ, DPAK | IRLR024NTRPBF |
| U1 | 50 MHz rail-to-rail op amp | OPA365AIDBVR |
| U2 | 1.25 V reference, 0.2% | REF3012AIDBZR |
| U3 | voltage supervisor | TPS3808G01DBVR |
| Q2 to Q4 | small-signal NMOS | BSS138 |
| C1, C3 | 330 µF 6.3 V polymer tantalum, 15 mΩ | T520D337M006ATE015 |
| C2, C4 to C6 | 47 µF 6.3 V X5R 1206 | GRM31CR60J476ME19L |
| J1, J2, J3 | 5.08 mm screw terminals | Phoenix 1715721, 1715734 |

## Part models

I wrote the Q1, U1, U2 and U3 models from datasheet numbers, and each model file lists what it takes from the datasheet and what it assumes. The Q1 model is an ngspice VDMOS fitted by least squares in `sim/fit_mosfet.py`, checked in `results/model_check_irlr024n.csv`.

A few limits to keep in mind:

- Every electrical model runs at 25 °C.
- The op amp model has no noise, CMRR or PSRR, and the reference has no noise or drift.
- Copper resistance comes from the layout, while copper inductance is an estimate.
- The thermal model is steady state with a fixed surface coefficient, and it leaves out heat that leaves through the part bodies and terminals, so it reads a bit high.

## Rebuilding the design files

The schematic and board files are generated by the scripts in `scripts/`, so they can be rebuilt from text with KiCad 10:

```
python scripts/build_schematic.py
kicad-cli sch export netlist --format kicadsexpr -o hardware/nmos-ldo-board.net hardware/nmos-ldo-board.kicad_sch
python scripts/check_netlist.py hardware/nmos-ldo-board.net
<KiCad python> scripts/build_pcb.py
python scripts/make_project.py <KiCad>/share/kicad/demos/pic_programmer/pic_programmer.kicad_pro
kicad-cli pcb drc --refill-zones --save-board hardware/nmos-ldo-board.kicad_pcb
<KiCad python> scripts/export_copper.py
python sim/pcb_parasitics.py
python scripts/export_outputs.py
```

`make_project.py` has to run before the zone fill, because saving the board rewrites the project file with KiCad's defaults. `export_copper.py` changes the inputs of the thermal and copper models, so rerun `sim/run_all.py` after a rebuild.

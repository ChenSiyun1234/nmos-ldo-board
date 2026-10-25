"""Compare the netlist KiCad exports from the schematic with the intended
pin-to-net map written by build_schematic.py. Exits non-zero on a mismatch.

    kicad-cli sch export netlist --format kicadsexpr -o hardware/nmos-ldo-board.net hardware/nmos-ldo-board.kicad_sch
    python scripts/check_netlist.py hardware/nmos-ldo-board.net
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sexpr import find, find_all, parse  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))


def read_netlist(path):
    with open(path, encoding="utf-8") as f:
        tree = parse(f.read())[0]
    nets = find(tree, "nets")
    pin_net = {}
    for net in find_all(nets, "net"):
        name = find(net, "name")[1]
        for node in find_all(net, "node"):
            ref = find(node, "ref")[1]
            pin = find(node, "pin")[1]
            pin_net[(ref, pin)] = name.lstrip("/")
    comps = {}
    for comp in find_all(find(tree, "components"), "comp"):
        ref = find(comp, "ref")[1]
        fields = {}
        fl = find(comp, "fields")
        if fl:
            for fld in find_all(fl, "field"):
                fields[find(fld, "name")[1]] = fld[2] if len(fld) > 2 else ""
        comps[ref] = dict(value=find(comp, "value")[1],
                          footprint=(find(comp, "footprint") or [None, ""])[1], fields=fields)
    return pin_net, comps


def main(path):
    pin_net, comps = read_netlist(path)
    with open(os.path.join(ROOT, "hardware", "intended_nets.json")) as f:
        intended = json.load(f)
    errors = []
    for ref, pins in intended.items():
        for pin, net in pins.items():
            got = pin_net.get((ref, pin))
            if net is None:
                if got is not None and not got.startswith("unconnected"):
                    errors.append(f"{ref}.{pin}: expected no connection, got {got}")
            elif got != net:
                errors.append(f"{ref}.{pin}: expected {net}, got {got}")
    for (ref, pin), net in pin_net.items():
        if ref not in intended and not ref.startswith(("H", "FID")):
            errors.append(f"{ref}.{pin} on {net} is not in the intended map")
    # every net needs at least two pins unless it is an intended single test point
    count = {}
    for (ref, pin), net in pin_net.items():
        count[net] = count.get(net, 0) + 1
    for net, n in sorted(count.items()):
        if n < 2 and not net.startswith("unconnected"):
            errors.append(f"net {net} has only {n} pin")
    print(f"{len(pin_net)} pins on {len(count)} nets checked")
    for e in errors:
        print("  MISMATCH", e)
    if errors:
        sys.exit(1)
    print("netlist matches the intended connections")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "hardware", "nmos-ldo-board.net"))

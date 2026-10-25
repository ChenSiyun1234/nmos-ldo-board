"""Write hardware/nmos-ldo-board.kicad_pro: net classes, design rules, check
severities and the root sheet entry. It starts from the project file of a
KiCad 10 demo so every key is one KiCad itself writes.

    python scripts/make_project.py <KiCad>/share/kicad/demos/pic_programmer/pic_programmer.kicad_pro
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NAME = "nmos-ldo-board"
OUT = os.path.join(ROOT, "hardware", NAME + ".kicad_pro")


def netclass(name, clearance, track, via_d, via_drill, priority):
    return {"bus_width": 12, "clearance": clearance, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "name": name, "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": priority,
            "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": track, "tuning_profile": "",
            "via_diameter": via_d, "via_drill": via_drill, "wire_width": 6}


def main(base):
    with open(base, encoding="utf-8") as f:
        pro = json.load(f)
    pro["meta"]["filename"] = os.path.basename(OUT)

    # board design rules
    ds = pro["board"]["design_settings"]
    for k in [k for k in ds if k.startswith("rule_severitieslegacy")]:
        del ds[k]
    d = ds["defaults"]
    d.update({"board_outline_line_width": 0.1, "copper_line_width": 0.2, "copper_text_size_h": 1.0,
              "copper_text_size_v": 1.0, "copper_text_thickness": 0.15, "courtyard_line_width": 0.05,
              "fab_line_width": 0.1, "other_line_width": 0.1, "silk_line_width": 0.15,
              "silk_text_size_h": 0.8, "silk_text_size_v": 0.8, "silk_text_thickness": 0.15})
    d["zones"] = {"45_degree_only": False, "min_clearance": 0.25}
    ds["rules"].update({
        "min_clearance": 0.15, "min_connection": 0.0, "min_copper_edge_clearance": 0.3,
        "min_hole_clearance": 0.2, "min_hole_to_hole": 0.25, "min_silk_clearance": 0.0,
        "min_text_height": 0.7, "min_text_thickness": 0.12, "min_through_hole_diameter": 0.3,
        "min_track_width": 0.15, "min_via_annular_width": 0.1, "min_via_diameter": 0.5,
        "solder_mask_to_copper_clearance": 0.0, "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1,
        # arc approximation error for zone fills; 0.01 mm leaves fills 0.1 um inside
        # the zone clearances after a refill, 0.005 mm keeps DRC clean
        "max_error": 0.005})
    ds["track_widths"] = [0.0, 0.25, 0.4, 0.8, 1.5]
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.6, "drill": 0.3},
                            {"diameter": 0.8, "drill": 0.4}]
    ds["drc_exclusions"] = []
    # run every optional check too, except length tuning, which this board does not use
    for k in ("missing_courtyard", "footprint_type_mismatch", "footprint_filters_mismatch",
              "track_not_centered_on_via"):
        ds["rule_severities"][k] = "warning"
    for k, v in list(ds["rule_severities"].items()):
        if v == "ignore" and k != "tuning_profile_track_geometries":
            ds["rule_severities"][k] = "warning"

    # schematic checks: nothing ignored except KiCad's own simulator model check,
    # which does not apply because the circuit is simulated from sim/ instead
    ers = pro["erc"]["rule_severities"]
    for k, v in list(ers.items()):
        if v == "ignore" and k != "simulation_model_issue":
            ers[k] = "warning"
    pro["erc"]["erc_exclusions"] = []

    ns = pro["net_settings"]
    ns["classes"] = [netclass("Default", 0.2, 0.25, 0.6, 0.3, 2147483647),
                     netclass("Power", 0.25, 1.0, 0.8, 0.4, 0),
                     netclass("Sense", 0.2, 0.25, 0.6, 0.3, 1)]
    ns["netclass_assignments"] = None
    ns["net_colors"] = None
    ns["netclass_patterns"] = [{"netclass": "Power", "pattern": "/VIN"},
                               {"netclass": "Power", "pattern": "/VOUT"},
                               {"netclass": "Power", "pattern": "GND"},
                               {"netclass": "Sense", "pattern": "/VOUT_S"},
                               {"netclass": "Sense", "pattern": "/GND_S"}]
    pro["text_variables"] = {}
    pro["boards"] = []
    pro["libraries"] = {"pinned_footprint_libs": [], "pinned_symbol_libs": []}
    for k in pro.get("pcbnew", {}).get("last_paths", {}):
        pro["pcbnew"]["last_paths"][k] = ""

    # root sheet from the schematic
    sch = os.path.join(ROOT, "hardware", NAME + ".kicad_sch")
    with open(sch, encoding="utf-8") as f:
        head = f.read(400)
    root_uuid = head.split('(uuid "', 1)[1].split('"', 1)[0]
    pro["sheets"] = [[root_uuid, "Root"]]
    pro["schematic"]["top_level_sheets"] = [{"filename": NAME + ".kicad_sch", "name": NAME, "uuid": root_uuid}]
    pro["schematic"]["bom_export_filename"] = "${PROJECTNAME}.csv"
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main(sys.argv[1])

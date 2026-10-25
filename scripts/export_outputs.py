"""Run the schematic and board checks, then export every output with kicad-cli.

    python scripts/export_outputs.py

Writes
    hardware/reports/erc.rpt, drc.rpt, drc_refill.rpt   ERC, and DRC with schematic parity on the
                                        stored zone fill and on a fresh refill
    docs/schematic.pdf, docs/img/schematic.png
    docs/img/board_top.png, board_bottom.png, board_angle.png   3D renders
    fab/gerbers/                        Gerber X2 for all layers, drill files and drill map
    fab/nmos-ldo-board-gerbers.zip      the same files zipped for a board house, with fab/fab_notes.txt
    fab/bom.csv                         grouped BOM with manufacturer part numbers
    fab/pick_and_place.csv              SMD placement, both sides, mm
    fab/nmos-ldo-board.step             board and parts for mechanical CAD

Needs KiCad 10. Set KICAD_CLI to the kicad-cli executable if it is not on the
PATH. PyMuPDF renders the schematic PNG; without it that one image is skipped.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NAME = "nmos-ldo-board"
SCH = f"hardware/{NAME}.kicad_sch"
PCB = f"hardware/{NAME}.kicad_pcb"
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"


def find_cli():
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    found = shutil.which("kicad-cli")
    if found:
        return found
    patterns = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "KiCad", "*", "bin",
                             "kicad-cli.exe"),
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli", "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli"]
    for p in patterns:
        hits = sorted(glob.glob(p), reverse=True)
        if hits:
            return hits[0]
    raise SystemExit("kicad-cli not found: set KICAD_CLI to its full path")


CLI = None


def cli(*args):
    r = subprocess.run([CLI, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit("kicad-cli failed: " + " ".join(args[:3]))
    return r.stdout


def path(rel):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def checks():
    path("hardware/reports/x")
    cli("sch", "erc", "--severity-all", "-o", "hardware/reports/erc.rpt", SCH)
    with open(path("hardware/reports/erc.rpt"), encoding="utf-8") as f:
        erc = f.read()
    m = re.search(r"ERC messages: (\d+)\s+Errors (\d+)\s+Warnings (\d+)", erc)
    print(f"ERC: {m.group(1)} messages, {m.group(2)} errors, {m.group(3)} warnings")
    bad = int(m.group(2)) + int(m.group(3))
    # DRC twice: on the zone fill stored in the board, and on a fresh refill of
    # every zone, which is what KiCad's DRC dialog does by default (not saved)
    for rpt, extra, what in (("drc.rpt", [], "stored fill"), ("drc_refill.rpt", ["--refill-zones"], "fresh refill")):
        cli("pcb", "drc", "--severity-all", "--schematic-parity", *extra, "-o", f"hardware/reports/{rpt}", PCB)
        with open(path(f"hardware/reports/{rpt}"), encoding="utf-8") as f:
            drc = f.read()
        counts = re.findall(r"Found (\d+) ([A-Za-z ]+?) \*\*", drc)
        print(f"DRC, {what}: " + ", ".join(f"{n} {w}" for n, w in counts))
        bad += sum(int(n) for n, _ in counts)
    if bad:
        raise SystemExit("checks are not clean, see hardware/reports/")


def schematic():
    cli("sch", "export", "pdf", "-o", "docs/schematic.pdf", SCH)
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            print("PyMuPDF not installed: docs/img/schematic.png skipped")
            return
    doc = pymupdf.open(path("docs/schematic.pdf"))
    doc[0].get_pixmap(dpi=150).save(path("docs/img/schematic.png"))
    print("schematic: docs/schematic.pdf, docs/img/schematic.png")


def fabrication():
    gdir = path("fab/gerbers/x")
    gdir = os.path.dirname(gdir)
    for old in glob.glob(os.path.join(gdir, "*")):
        os.remove(old)
    cli("pcb", "export", "gerbers", "-o", "fab/gerbers/", "-l", LAYERS, "--subtract-soldermask", PCB)
    cli("pcb", "export", "drill", "-o", "fab/gerbers/", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", PCB)
    files = sorted(os.listdir(gdir))
    notes = path("fab/fab_notes.txt")
    with zipfile.ZipFile(path(f"fab/{NAME}-gerbers.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for fn in files:
            z.write(os.path.join(gdir, fn), fn)
        if os.path.exists(notes):
            z.write(notes, "fab_notes.txt")
    print(f"gerbers and drill: {len(files)} files in fab/gerbers and fab/{NAME}-gerbers.zip")
    cli("sch", "export", "bom", "-o", "fab/bom.csv",
        "--fields", "Reference,${QUANTITY},Value,Description,Manufacturer,MPN,Footprint",
        "--labels", "Reference,Qty,Value,Description,Manufacturer,MPN,Footprint",
        "--group-by", "Value,Manufacturer,MPN,Footprint", "--ref-range-delimiter", "", "--exclude-dnp", SCH)
    cli("pcb", "export", "pos", "-o", "fab/pick_and_place.csv", "--format", "csv", "--units", "mm",
        "--side", "both", "--smd-only", "--exclude-dnp", PCB)
    cli("pcb", "export", "step", "-f", "--subst-models", "--no-dnp", "-o", f"fab/{NAME}.step", PCB)
    print("bom, pick and place, step written to fab/")


def renders():
    common = ["--quality", "high", "--background", "opaque"]
    cli("pcb", "render", "--side", "top", "--width", "1600", "--height", "1250", *common,
        "-o", "docs/img/board_top.png", PCB)
    cli("pcb", "render", "--side", "bottom", "--width", "1600", "--height", "1250", *common,
        "-o", "docs/img/board_bottom.png", PCB)
    cli("pcb", "render", "--side", "top", "--rotate", "-50,0,-30", "--perspective", "--zoom", "0.85",
        "--width", "1800", "--height", "1200", *common, "-o", "docs/img/board_angle.png", PCB)
    print("renders: docs/img/board_top.png, board_bottom.png, board_angle.png")


def scrub():
    """Keep machine paths out of the published text files."""
    home = os.path.expanduser("~")
    pats = [re.escape(ROOT), re.escape(ROOT.replace("\\", "/")), re.escape(home), re.escape(home.replace("\\", "/"))]
    rx = re.compile("|".join(pats), re.I)
    for top in (os.path.join(ROOT, "hardware", "reports"), os.path.join(ROOT, "fab")):
        for dirpath, _dirs, files in os.walk(top):
            for fn in files:
                if os.path.splitext(fn)[1].lower() in (".zip", ".png", ".pdf"):
                    continue
                p = os.path.join(dirpath, fn)
                with open(p, encoding="utf-8", errors="surrogateescape", newline="") as f:
                    text = f.read()
                if rx.search(text):
                    print("machine path removed from", os.path.relpath(p, ROOT))
                    with open(p, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                        f.write(rx.sub(".", text))


def main():
    global CLI
    CLI = find_cli()
    checks()
    schematic()
    fabrication()
    scrub()
    renders()


if __name__ == "__main__":
    sys.exit(main())

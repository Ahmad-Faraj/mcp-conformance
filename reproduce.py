"""Regenerate every number, table and figure in the paper from the released data.

    python reproduce.py           regenerate, then build the PDF if LaTeX is present
    python reproduce.py --verify  regenerate into a scratch copy and diff, changing nothing

Works without make, which is the point: a reviewer on any platform can run one
command. Exits non-zero if an input is missing or a generated file no longer
matches the released data.
"""

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REL = ROOT / "data" / "release"
CENSUS = REL / "probe_census.jsonl"
FRAME = REL / "frame_latest.jsonl"
REPROBE = REL / "entrypoint_reprobe.jsonl"


def run(cmd, **kw):
    print("  " + " ".join(str(c) for c in cmd))
    return subprocess.run([sys.executable if c == "python" else c for c in cmd],
                          cwd=ROOT, check=True, **kw)


def check_inputs():
    missing = [p for p in (CENSUS, FRAME, REPROBE) if not p.exists()]
    if missing:
        for p in missing:
            print(f"missing input: {p}", file=sys.stderr)
        print("\nThe release carries these three files. Fetch the full release before "
              "running this.", file=sys.stderr)
        sys.exit(1)


def regenerate(numbers_out=None):
    run(["python", "driver/make_numbers.py", "--in", CENSUS, "--frame", FRAME,
         "--reprobe", REPROBE] + (["--out", numbers_out] if numbers_out else []),
        stdout=subprocess.DEVNULL)
    if numbers_out:
        return
    run(["python", "driver/make_tables.py", "--in", CENSUS], stdout=subprocess.DEVNULL)
    run(["python", "driver/make_figures.py", "--in", CENSUS, "--frame", FRAME,
         "--reprobe", REPROBE], stdout=subprocess.DEVNULL)


def build_pdf():
    if not shutil.which("latexmk"):
        print("latexmk not found, skipping the PDF build")
        return
    subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "main.tex"],
                   cwd=ROOT / "paper", check=False, stdout=subprocess.DEVNULL)
    log = (ROOT / "paper" / "main.log").read_text(encoding="utf-8", errors="replace")
    if "There were undefined references" in log:
        print("WARNING: the build has undefined references")
    for line in log.splitlines():
        if line.startswith("Output written"):
            print("  " + line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="regenerate to a temporary file and compare, without writing")
    args = ap.parse_args()
    check_inputs()

    if args.verify:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "numbers.tex")
            print("regenerating numbers.tex from the release")
            regenerate(numbers_out=out)
            same = filecmp.cmp(ROOT / "paper" / "numbers.tex", out, shallow=False)
        print("numbers.tex reproduces" if same
              else "numbers.tex DIFFERS from what the released data produces")
        sys.exit(0 if same else 1)

    print("regenerating numbers, tables and figures")
    regenerate()
    print("building the PDF")
    build_pdf()
    print("done")


if __name__ == "__main__":
    main()

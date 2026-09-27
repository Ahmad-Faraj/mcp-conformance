"""Build a one-file LaTeX version of the EMSE manuscript for Editorial Manager.

Springer compiles the uploaded source into the review PDF itself, and its upload
form accepts one main .tex as the manuscript with supporting files beside it. The
repository build splits the paper across sections, tables and generated-number
files, so this inlines every \\input into a single main.tex, keeps the figures, the
class, the style and the compiled bibliography as separate flat files, compiles the
result in isolation and checks it matches the repository build.

Usage:
  python tools/make_single_tex.py [--out dist/emse-single]
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper"
EMSE = PAPER / "emse"
BS = "\\"

INPUT = re.compile(r"\\input\{([^}]+)\}")


def resolve(name: str) -> Path:
    """Find an \\input target the way the EMSE build does: beside emse, then paper."""
    stem = name[:-4] if name.endswith(".tex") else name
    stem = stem.replace("../", "")
    for base in (EMSE, PAPER):
        p = base / (stem + ".tex")
        if p.exists():
            return p
    raise FileNotFoundError(name)


UNESCAPED_PCT = re.compile(r"(?<!\\)%")


def inline(text: str, depth: int = 0) -> str:
    """Replace every \\input{...} in the code part of each line with the file's text."""
    if depth > 5:
        raise RuntimeError("input nesting too deep")
    out = []
    for line in text.split("\n"):
        m = UNESCAPED_PCT.search(line)
        code, comment = (line[:m.start()], line[m.start():]) if m else (line, "")
        hit = INPUT.search(code)
        if not hit:
            out.append(line)
            continue
        target = resolve(hit.group(1))
        body = inline(target.read_text(encoding="utf-8").rstrip("\n"), depth + 1)
        before, after = code[:hit.start()], code[hit.end():]
        if before.strip():
            out.append(before)
        out.append(f"% ---- begin {target.relative_to(PAPER).as_posix()} ----")
        out.append(body)
        out.append(f"% ---- end {target.relative_to(PAPER).as_posix()} ----")
        if after.strip() or comment:
            out.append(after + comment)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "emse-single"))
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    src = (EMSE / "main.tex").read_text(encoding="utf-8")
    # Drop the input-path hook and its comment; nothing is read from elsewhere now.
    lines = src.split("\n")
    kept = []
    for line in lines:
        if "input@path" in line:
            while kept and kept[-1].lstrip().startswith("%"):
                kept.pop()
            continue
        kept.append(line)
    src = "\n".join(kept)
    src = src.replace(BS + "graphicspath{{figures/}}", "")
    src = src.replace(BS + "bibliography{../refs}", BS + "bibliography{refs}")

    tex = inline(src)
    tex = re.sub(r"\\includegraphics(\[[^\]]*\])?\{figures/([^}]+)\}",
                 lambda m: BS + "includegraphics" + (m.group(1) or "") + "{" + m.group(2) + "}",
                 tex)
    if INPUT.search("\n".join(l for l in tex.split("\n") if not l.lstrip().startswith("%"))):
        print("an \\input survived inlining")
        return 1
    (out / "main.tex").write_text(tex, encoding="utf-8")

    for f in (EMSE / "figures").glob("*.pdf"):
        shutil.copy2(f, out / f.name)
    shutil.copy2(PAPER / "refs.bib", out / "refs.bib")
    for name in ("sn-jnl.cls", "sn-basic.bst"):
        shutil.copy2(EMSE / name, out / name)

    for cmd in (["pdflatex", "-interaction=nonstopmode", "main.tex"],
                ["bibtex", "main"],
                ["pdflatex", "-interaction=nonstopmode", "main.tex"],
                ["pdflatex", "-interaction=nonstopmode", "main.tex"]):
        subprocess.run(cmd, cwd=out, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = (out / "main.log").read_text(encoding="utf-8", errors="replace")
    errors = [l for l in log.splitlines() if l.startswith("! ")]
    undefined = [l for l in log.splitlines() if re.search(r"(Reference|Citation) .* undefined", l)]
    if errors or undefined:
        print("single-file build does not compile cleanly:")
        for l in (errors + undefined)[:10]:
            print("  ", l)
        return 1

    def pages(pdf):
        p = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", p)
        return int(m.group(1)) if m else -1

    n_single, n_repo = pages(out / "main.pdf"), pages(EMSE / "main.pdf")
    if n_single != n_repo:
        print(f"page count differs: single {n_single}, repository {n_repo}")
        return 1

    keep = {".tex", ".bib", ".bbl", ".cls", ".bst"}
    for f in out.iterdir():
        if f.suffix == ".pdf" and f.name != "main.pdf":
            continue  # figures
        if f.suffix not in keep:
            f.unlink()
    print(f"single-file build compiles on its own: {n_single} pages, no errors")
    for f in sorted(out.iterdir()):
        print(f"   {f.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

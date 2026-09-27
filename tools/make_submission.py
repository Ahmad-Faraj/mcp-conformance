"""Package the EMSE build as a self-contained LaTeX source bundle and prove it compiles.

Springer requires the editable source at submission and compiles it on its side. The
repository build reads shared sections and generated numbers from the parent
directory, which a submission system will not have, so this flattens everything into
one folder, rewrites the relative paths, compiles the copy in isolation, checks it
against the repository build, and zips it.

Usage:
  python tools/make_submission.py [--out dist]
"""

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper"
EMSE = PAPER / "emse"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()

    out = Path(args.out)
    src = out / "emse-source"
    if src.exists():
        shutil.rmtree(src)
    # Flat: Editorial Manager rejects a zip that contains any subfolder. Tables and
    # figures get a prefix so a table and a figure sharing a name stay distinct.
    src.mkdir(parents=True)

    bs = "\\"
    lines = (EMSE / "main.tex").read_text(encoding="utf-8").split("\n")
    out_lines = []
    skip_comment_block = False
    for line in lines:
        # The input-path hook only existed to reach the parent directory; drop it and
        # the comment that explains it.
        if "input@path" in line:
            while out_lines and out_lines[-1].lstrip().startswith("%"):
                out_lines.pop()
            continue
        # Paths one level up in the repository sit beside main.tex in the bundle.
        line = line.replace("{../", "{")
        line = line.replace("{sections/", "{")
        out_lines.append(line)
    tex = "\n".join(out_lines)
    tex = tex.replace(chr(92) + "graphicspath{{figures/}}", "")
    code = "\n".join(l.split("%", 1)[0] for l in out_lines)
    assert "../" not in code and "input@path" not in code, "a parent path survived"
    (src / "main.tex").write_text(tex, encoding="utf-8")

    def flat(text):
        text = re.sub(r"\\input\{tables/([^}]+)\}", r"\\input{tab-\1}", text)
        text = re.sub(r"\\includegraphics(\[[^\]]*\])?\{figures/([^}]+)\}",
                      r"\\includegraphics\1{fig-\2}", text)
        return text

    for f in (PAPER / "sections").glob("*.tex"):
        (src / f.name).write_text(flat(f.read_text(encoding="utf-8")), encoding="utf-8")
    for f in (PAPER / "tables").glob("*.tex"):
        (src / ("tab-" + f.name)).write_text(flat(f.read_text(encoding="utf-8")),
                                             encoding="utf-8")
    for f in (EMSE / "figures").glob("*.pdf"):
        shutil.copy2(f, src / ("fig-" + f.name))
    for name in ("numbers.tex", "validation_numbers.tex", "disclosure_numbers.tex",
                 "comparison_numbers.tex", "refs.bib"):
        shutil.copy2(PAPER / name, src / name)
    for name in ("sn-jnl.cls", "sn-basic.bst"):
        shutil.copy2(EMSE / name, src / name)

    # Compile the copy on its own.
    for cmd in (["pdflatex", "-interaction=nonstopmode", "main.tex"],
                ["bibtex", "main"],
                ["pdflatex", "-interaction=nonstopmode", "main.tex"],
                ["pdflatex", "-interaction=nonstopmode", "main.tex"]):
        subprocess.run(cmd, cwd=src, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = (src / "main.log").read_text(encoding="utf-8", errors="replace")
    errors = [l for l in log.splitlines() if l.startswith("! ")]
    undefined = [l for l in log.splitlines() if re.search(r"(Reference|Citation) .* undefined", l)]
    if errors or undefined:
        print("bundle does not compile cleanly:")
        for l in (errors + undefined)[:10]:
            print("  ", l)
        return 1

    def pages(pdf):
        p = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", p)
        return int(m.group(1)) if m else -1

    n_bundle, n_repo = pages(src / "main.pdf"), pages(EMSE / "main.pdf")
    if n_bundle != n_repo:
        print(f"page count differs: bundle {n_bundle}, repository build {n_repo}")
        return 1

    # Keep the compiled bibliography in the bundle, drop the rest of the build output.
    keep = {".tex", ".bib", ".bbl", ".cls", ".bst", ".pdf"}
    for f in src.iterdir():
        if f.is_file() and f.suffix not in keep:
            f.unlink()
    pdf = out / "emse-manuscript.pdf"
    shutil.copy2(src / "main.pdf", pdf)
    (src / "main.pdf").unlink()

    nested = [f for f in src.rglob("*") if f.is_dir()]
    if nested:
        print("bundle has subfolders:", nested)
        return 1
    zpath = out / "emse-source.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src).as_posix())
    print(f"bundle compiles on its own: {n_bundle} pages, no errors, no undefined references")
    print(f"wrote {zpath}")
    print(f"wrote {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

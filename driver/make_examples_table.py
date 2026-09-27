"""Generate the silent-execution examples table from the released responses.

The rows are chosen by hand, the text is not: every argument and every reply is read
from consequences.json, collapsed to one line and truncated, so the table cannot drift
from the data it illustrates.

Rows are ordered by how much they establish. The first group sent a value that no
coercion rule turns into what the schema asked for ("not-a-number" where a number is
required), and the tool still produced an answer. The second group sent the integer
12345 where a string is required; a runtime that stringifies it may answer the
question correctly, which is the weaker reading the threats section discusses.

Usage:
  python driver/make_examples_table.py [--cons data/release/consequences.json]
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (tool name, which group). Chosen for variety of domain and failure shape.
PICKS = [
    ("hn_top_stories", "no coercion"),
    ("upcoming_deadlines", "no coercion"),
    ("get_recent_trades", "no coercion"),
    ("scan_code_imports", "coercible"),
    ("register_project", "coercible"),
]

TEX_ESC = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "_": r"\_",
           "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&", "~": r"\textasciitilde{}",
           "^": r"\textasciicircum{}"}


def tex(s):
    return "".join(TEX_ESC.get(c, c) for c in s)


def one_line(s, limit):
    s = re.sub(r"\s+", " ", str(s)).strip()
    # Keep the table printable: drop characters outside Latin-1 (emoji, symbols).
    s = s.encode("latin-1", "ignore").decode("latin-1")
    return s if len(s) <= limit else s[: limit - 3].rstrip() + "..."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cons", default=str(ROOT / "data" / "release" / "consequences.json"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "tables" / "consequences.tex"))
    args = ap.parse_args()

    cons = json.loads(Path(args.cons).read_text(encoding="utf-8"))
    silent = [r for r in cons.get("silent-execution", []) if isinstance(r, dict)]
    by_tool = {}
    for r in silent:
        by_tool.setdefault(r.get("tool"), r)

    rows = []
    for tool, group in PICKS:
        r = by_tool.get(tool)
        if r is None:
            raise SystemExit(f"make_examples_table: no silent execution for tool {tool!r}")
        sent = r.get("sent") or {}
        # Show only the poisoned property: the one carrying a wrong-typed value.
        poison = {k: v for k, v in sent.items()
                  if v == 12345 or (isinstance(v, str) and v.startswith("not-a"))}
        shown = ", ".join(f"{k}: {json.dumps(v)}" for k, v in (poison or sent).items())
        rows.append((tool, shown, one_line(r.get("text"), 110), group))

    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Servers that ran a tool on an argument their published schema rejects",
        r"and returned an ordinary result. In the first three the argument cannot be",
        r"coerced into the declared type, and each reply answers a question that was not",
        r"asked. In the last two an integer was sent where a string was declared, and a",
        r"runtime that stringifies it may answer correctly (Section~\ref{sec:threats}).",
        r"Replies are verbatim, collapsed to one line and truncated. None carries an error",
        r"indication a client could act on.}",
        r"\label{tab:consequences}",
        r"\small",
        r"\begin{tabular}{p{0.24\linewidth}p{0.22\linewidth}p{0.46\linewidth}}",
        r"\toprule",
        r"Tool & Argument sent & Reply returned to the client \\",
        r"\midrule",
    ]
    for i, (tool, shown, text, group) in enumerate(rows):
        if i and rows[i - 1][3] != group:
            lines.append(r"\midrule")
        lines.append(rf"\texttt{{{tex(tool)}}} & \texttt{{{tex(shown)}}} & "
                     rf"\texttt{{{tex(text)}}} \\")
        lines.append(r"\addlinespace")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()

"""Agreement between the analysis classifier and one or two raters.

Usage:
  python validation/agreement.py private/rating/llm_labels.csv [private/rating/human.csv]

The classifier's buckets map to the hazard question "did the tool execute on
the bad input?": silent-execution -> yes, in-band-error -> no. A rater's
EXECUTED -> yes, REJECTED or ENV-ERROR -> no. UNCLEAR items are reported and
left out of kappa.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ("EXECUTED", "REJECTED", "ENV-ERROR", "UNCLEAR")


def read_labels(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["item_id"]: r["label"].strip().upper() for r in csv.DictReader(f)
                if r.get("label", "").strip()}


def kappa(pairs):
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def compare(name_a, a, name_b, b):
    common = sorted(set(a) & set(b))
    clear = [i for i in common if "UNCLEAR" not in (a[i], b[i])]
    pairs = [(a[i], b[i]) for i in clear]
    print(f"\n== {name_a} vs {name_b}: {len(common)} shared items, {len(clear)} without UNCLEAR")
    print(f"   agreement {sum(x == y for x, y in pairs)}/{len(pairs)}, Cohen's kappa {kappa(pairs):.3f}")
    conf = Counter(pairs)
    cols = sorted({y for _, y in pairs})
    print("   " + f"{name_a:>12} \\ {name_b}".ljust(26) + "".join(f"{c:>11}" for c in cols))
    for r in sorted({x for x, _ in pairs}):
        print("   " + r.rjust(26) + "".join(f"{conf[(r, c)]:>11}" for c in cols))
    return [i for i in clear if a[i] != b[i]]


def main():
    key = json.loads((ROOT / "private" / "rating" / "key.json").read_text(encoding="utf-8"))
    clf = {i: ("EXEC" if v["bucket"] == "silent-execution" else "NOT") for i, v in key.items()}
    raters = [(Path(p).stem, read_labels(p)) for p in sys.argv[1:]]

    for name, lab in raters:
        print(f"\n{name}: {len(lab)} labels  {dict(Counter(lab.values()))}")
        bad = [i for i, l in lab.items() if l not in LABELS]
        if bad:
            print(f"   invalid labels on {bad[:10]}")
        binary = {i: ("EXEC" if l == "EXECUTED" else "UNCLEAR" if l == "UNCLEAR" else "NOT")
                  for i, l in lab.items()}
        dis = compare("classifier", clf, name, binary)
        print(f"   disagreements: {', '.join(dis)}")
        by_bucket = Counter((key[i]["bucket"], l) for i, l in lab.items())
        print("   rater label by classifier bucket:")
        for k in sorted(by_bucket):
            print(f"     {k[0]:17} {k[1]:10} {by_bucket[k]}")

    if len(raters) == 2:
        (na, a), (nb, b) = raters
        dis = compare(na, a, nb, b)
        print(f"   disagreements: {', '.join(dis)}")


if __name__ == "__main__":
    main()

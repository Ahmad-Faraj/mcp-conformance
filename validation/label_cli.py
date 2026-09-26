"""Label one rating item at a time, from the terminal.

    python validation/label_cli.py

Shows each reply from private/rating/human.csv, takes one keystroke, and saves
after every answer. Stop with q and rerun later to continue where you left off.
The labels and their rules are in validation/CODEBOOK.md; the short form is on
screen while you work.
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET = os.path.join(os.path.dirname(HERE), "private", "rating", "human.csv")

KEYS = {"e": "EXECUTED", "r": "REJECTED", "v": "ENV-ERROR", "u": "UNCLEAR"}

HELP = """
  e  EXECUTED   the tool ran on the bad input and answered normally
                (data, a confirmation, an empty list, "no results")
  r  REJECTED   the reply says the argument is invalid, missing or wrong-typed
  v  ENV-ERROR  an error about the environment: missing key, no network,
                missing file or service, rate limit, unrelated crash
  u  UNCLEAR    too short, cut off, or ambiguous to decide (asks for a note)

  s  skip for now     b  back one     q  save and quit
"""


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames


def save(path, rows, fields):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main():
    if not os.path.exists(SHEET):
        sys.exit(f"sheet not found: {SHEET}")
    rows, fields = load(SHEET)
    total = len(rows)
    i = 0
    while i < total:
        row = rows[i]
        if (row.get("label") or "").strip():
            i += 1
            continue
        done = sum(1 for r in rows if (r.get("label") or "").strip())
        print("\n" + "=" * 72)
        print(f"item {row['item_id']}   ({done} of {total} labeled)")
        print(f"tool:      {row.get('tool', '')}")
        print(f"arguments: {row.get('arguments_sent', '')[:300]}")
        print("-" * 72)
        print((row.get("reply_text") or "").strip()[:1200])
        print("-" * 72)
        print(HELP)
        choice = input("label> ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            i += 1
            continue
        if choice == "b":
            i = max(0, i - 1)
            rows[i]["label"] = ""
            continue
        if choice not in KEYS:
            print("  use e, r, v, u, s, b or q")
            continue
        row["label"] = KEYS[choice]
        if choice == "u":
            row["note"] = input("  one line on why it is unclear> ").strip()
        save(SHEET, rows, fields)
        i += 1

    done = sum(1 for r in rows if (r.get("label") or "").strip())
    save(SHEET, rows, fields)
    print(f"\nsaved {SHEET}")
    print(f"{done} of {total} labeled")
    if done == total:
        print("all done. next: python validation/agreement.py "
              "private/rating/llm_labels.csv private/rating/human.csv")


if __name__ == "__main__":
    main()

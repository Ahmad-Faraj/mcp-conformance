"""Build the blinded rating set for the wrong-typed-argument replies.

Reads data/consequences.json (local, not released), pools the silent-execution
and in-band-error buckets, shuffles them with a fixed seed, and writes:

  private/rating/items.jsonl   blinded items for the LLM rater (all items)
  private/rating/human.csv     the first 100 items as a sheet for the human rater
  private/rating/key.json      item_id -> server and analysis bucket (never shown
                               to a rater)

Items stay under private/ because reply text comes from the raw transcripts,
which are not disclosure-filtered.
"""
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 20260924
HUMAN_N = 100


def main():
    cons = json.loads((ROOT / "data" / "consequences.json").read_text(encoding="utf-8"))
    pool = [(b, r) for b in ("silent-execution", "in-band-error") for r in cons[b]]
    random.Random(SEED).shuffle(pool)

    out = ROOT / "private" / "rating"
    out.mkdir(parents=True, exist_ok=True)
    key, items = {}, []
    for i, (bucket, r) in enumerate(pool, 1):
        iid = f"R{i:03d}"
        key[iid] = {"server": r["server"], "bucket": bucket}
        items.append({"item_id": iid, "tool": r["tool"],
                      "arguments_sent": r["sent"], "reply_text": r["text"]})

    with (out / "items.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with (out / "human.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "tool", "arguments_sent", "reply_text", "label", "note"])
        for it in items[:HUMAN_N]:
            w.writerow([it["item_id"], it["tool"], json.dumps(it["arguments_sent"], ensure_ascii=False),
                        it["reply_text"], "", ""])
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(items)} items; human sheet {min(HUMAN_N, len(items))}; seed {SEED}")


if __name__ == "__main__":
    main()

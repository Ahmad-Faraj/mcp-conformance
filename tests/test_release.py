"""Guards on the published dataset.

Two of the defects found while preparing this release were of this kind: a file
that joined on real server names while the census carried pseudonyms, and a table
that shipped withheld identities outright. Both passed every other check. These
tests fail loudly if either happens again.
"""

import csv
import json
from pathlib import Path

import pytest

RELEASE = Path(__file__).resolve().parent.parent / "data" / "release"

pytestmark = pytest.mark.skipif(not (RELEASE / "probe_census.jsonl").exists(),
                                reason="release not built")


def released_names():
    with (RELEASE / "probe_census.jsonl").open(encoding="utf-8") as f:
        return {json.loads(line)["server_name"] for line in f}


def names_in(path):
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as f:
            return [json.loads(line).get("server_name") for line in f]
    if path.suffix == ".csv":
        with path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return [r["server"] for r in rows] if rows and "server" in rows[0] else []
    if path.name == "consequences.json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return [r["server"] for v in data.values() if isinstance(v, list)
                for r in v if isinstance(r, dict) and r.get("server")]
    return []


def release_files():
    return sorted(p for p in RELEASE.iterdir()
                  if p.is_file() and p.suffix in (".jsonl", ".csv", ".json"))


@pytest.mark.parametrize("path", release_files(), ids=lambda p: p.name)
def test_no_file_names_a_server_the_census_withholds(path):
    """Every server named anywhere must be named in the census too.

    A withheld server appears in the census only under its pseudonym, so a real
    name in any other file is a server whose identity has leaked.
    """
    known = released_names()
    leaked = [n for n in names_in(path) if n and n not in known]
    assert not leaked, f"{len(leaked)} withheld identities, e.g. {leaked[:3]}"


def test_withheld_rows_carry_nothing_that_reidentifies_them():
    with (RELEASE / "probe_census.jsonl").open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    withheld = [r for r in rows if r.get("identity_withheld")]
    assert withheld, "expected some withheld rows"
    for r in withheld:
        for field in ("cmd", "server_info", "server_version", "stderr_tail"):
            assert not r.get(field), f"{r['server_name']} still carries {field}"


def test_withheld_language_rows_drop_the_repository():
    for name in ("repo_languages.csv", "residual_languages.csv"):
        p = RELEASE / name
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["server"].startswith("withheld-"):
                    assert not r["repository"], f"{name}: {r['server']} keeps its URL"


def test_september_rows_carry_their_break_cause():
    """The comparison reads this field because withholding strips the stderr."""
    p = RELEASE / "probe_census_sept.jsonl"
    if not p.exists():
        pytest.skip("no September run in this release")
    with p.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert all("rerun_break_cause" in r for r in rows)
    assert sum(1 for r in rows if r["rerun_break_cause"] == "python-sdk-2") > 0

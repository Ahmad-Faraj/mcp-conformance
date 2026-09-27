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


def test_withheld_reply_text_is_scrubbed_of_the_servers_own_identifiers():
    """A tool's reply can name its own product or repository.

    Withholding the server's name while publishing that reply withheld nothing: a
    regulatory tool reported the repository that served its snapshot. The release
    removes each withheld server's identifying strings from its reply text.
    """
    import sys
    sys.path.insert(0, str(RELEASE.parent.parent / "driver"))
    from make_release import identifying_tokens, scrub_tokens

    entry = {"server": {"name": "io.github.acme/deadline-tracker",
                        "packages": [{"identifier": "@acme/deadline-tracker"}],
                        "repository": {"url": "https://github.com/acme/deadline-tracker"}}}
    toks = identifying_tokens("io.github.acme/deadline-tracker", entry)
    rec = {"tool": "upcoming", "text": '{"served_by": "acme/deadline-tracker", "n": 3}'}
    out = scrub_tokens(rec, toks)
    assert "acme" not in out["text"].lower()
    assert "deadline-tracker" not in out["text"].lower()
    assert '"n": 3' in out["text"], "non-identifying content must survive"


def test_withheld_set_cannot_be_recovered_by_subtraction():
    """The census is complete, so the frame must not name what the census withholds.

    If it did, eligible names in the frame minus names in the census would be
    exactly the list of servers with a security-relevant finding.
    """
    import sys
    sys.path.insert(0, str(RELEASE.parent.parent / "driver"))
    from run_batch import eligible_packages

    census = released_names()
    eligible_real = set()
    with (RELEASE / "frame_latest.jsonl").open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e["meta"].get("status") != "active":
                continue
            s = e["server"]
            if list(eligible_packages(s)) and not s["name"].startswith("withheld-"):
                eligible_real.add(s["name"])
    recovered = eligible_real - census
    assert not recovered, f"{len(recovered)} withheld servers recoverable, e.g. {sorted(recovered)[:3]}"


def test_every_release_file_is_tracked_by_git():
    """A release file that exists only on the machine that built it is invisible to
    a reviewer's clone, and twice a number reproduced here and not on a clean clone
    for exactly that reason. This fails locally, before the push.
    """
    import subprocess
    root = RELEASE.parent.parent
    tracked = set(subprocess.run(["git", "ls-files", "data/release"], cwd=root,
                                 capture_output=True, text=True).stdout.split())
    on_disk = {p.relative_to(root).as_posix() for p in RELEASE.rglob("*") if p.is_file()}
    untracked = sorted(on_disk - tracked)
    assert not untracked, f"release files not tracked by git: {untracked}"

"""End-to-end: run the real probe against servers whose correct verdict is known.

These are the tests that matter most. Every verdict in the census comes out of
probe(), so each behaviour the paper reports is reproduced here by a fake server
and the probe must grade it the way the paper says it does.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "driver"))

from mcpprobe import probe  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fake_server.py")
TIMEOUT = 5.0


def run(mode):
    return probe([sys.executable, FAKE, mode], TIMEOUT)


def verdicts(result):
    return {c["id"]: c["verdict"] for c in result["checks"]}


def test_conforming_server_passes_every_check():
    r = run("conforming")
    assert r["handshake_ok"]
    assert verdicts(r) == {
        "server-initialize": "pass",
        "ping": "pass",
        "tools-list": "pass",
        "tools-schema-valid": "pass",
        "tools-call-unknown": "pass",
        "tools-call-invalid-args": "pass",
        "malformed-json": "pass",
        "stdout-purity": "pass",
    }


def test_sdk_default_is_error_as_result_and_silent_execution():
    """The two findings the paper leads with, reproduced on a known server."""
    v = verdicts(run("sdk-default"))
    assert v["tools-call-unknown"] == "error-as-result"
    assert v["tools-call-invalid-args"] == "fail"
    # Neither finding should leak into the checks it does not concern.
    assert v["malformed-json"] == "pass"
    assert v["stdout-purity"] == "pass"


def test_poisoned_property_is_recorded():
    r = run("sdk-default")
    assert r["poisoned_property"] == "text"
    assert r["poisoned_required"] is True


def test_server_that_dies_on_malformed_frame_fails_that_check_only():
    v = verdicts(run("dies-on-malformed"))
    assert v["malformed-json"] == "fail"
    assert v["tools-call-unknown"] == "error-as-result"


def test_stdout_banner_fails_purity():
    r = run("noisy")
    assert verdicts(r)["stdout-purity"] == "fail"
    assert r["stdout_noise"]


@pytest.mark.parametrize("mode, expected", [
    ("crash", "crash-python-exception"),
    ("needs-config", "needs-auth-or-config"),
])
def test_startup_failures_are_classified(mode, expected):
    r = run(mode)
    assert not r["handshake_ok"]
    assert r["failure_class"] == expected


def test_silent_server_is_a_hang_not_a_crash():
    r = probe([sys.executable, FAKE, "hang"], 2.0)
    assert not r["handshake_ok"]
    assert r["failure_class"] == "hang-no-reply"


def test_every_run_keeps_a_transcript():
    """The release ships transcripts; a probe that does not record one breaks it."""
    r = run("conforming")
    assert r["transcript"], "probe returned no transcript"

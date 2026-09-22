"""Shared startup-failure classification for the table, figure and numbers generators.

The census classifier in run_batch.py keys on exit codes and stderr keywords. uv's
"An executable named `x` is not provided by package `y`" exits 1 and contains
neither "error" nor a traceback, so those runs landed in crash-exit-1. They are
the entry-point artifact the paper corrects for (re-probed in
entrypoint_reprobe.jsonl), not server crashes. Every generator reclassifies them
through this module so the table, the figure and the prose cannot disagree.

The released census keeps the original label; this is applied at analysis time.
"""

import re

ENTRYPOINT_NOT_PROVIDED = "entrypoint-not-provided"

UVX_NO_EXE = re.compile(r"An executable named `[^`]+` is not provided by package `[^`]+`")


def failure_class(r: dict) -> str | None:
    """Return the startup-failure class for a census row, or None if it handshook."""
    if r.get("handshake_ok"):
        return None
    if any(UVX_NO_EXE.search(line or "") for line in r.get("stderr_tail") or []):
        return ENTRYPOINT_NOT_PROVIDED
    return r.get("failure_class") or "unclassified"

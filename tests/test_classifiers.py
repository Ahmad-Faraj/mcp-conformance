"""Unit tests for the pure functions every census number passes through."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "driver"))

from compare_runs import sdk2_victim  # noqa: E402
from failure_classes import (  # noqa: E402
    ENTRYPOINT_NOT_PROVIDED, HARNESS_ERROR, failure_class, harness_error)
from mcpprobe import _schema_type, classify_failure, wrong_typed_args  # noqa: E402


# --- startup failure classification -------------------------------------------

@pytest.mark.parametrize("stderr, exit_code, expected", [
    (["npm error 404 Not Found - GET https://registry.npmjs.org/x"], 1,
     "install-not-found"),
    (["npm error code ERESOLVE"], 1, "install-error"),
    (["  x No solution found when resolving tool dependencies:"], 1, "install-error"),
    (["Error: OPENAI_API_KEY environment variable is not set"], 1,
     "needs-auth-or-config"),
    (["Traceback (most recent call last):", "ValueError: boom"], 1,
     "crash-python-exception"),
    (["Something error-ish happened"], 1, "crash-with-error-output"),
    ([], 2, "crash-exit-2"),
    ([], 0, "exit-silent"),
])
def test_classify_failure(stderr, exit_code, expected):
    assert classify_failure(exit_code, stderr) == expected


def test_config_is_checked_before_generic_traceback():
    """A server that crashes because a key is missing needs config, not a fix.

    Getting this order wrong would move servers from the environment bucket to
    the server-fault bucket and inflate the startup-failure figure.
    """
    stderr = ["Traceback (most recent call last):",
              "KeyError: the environment variable GITHUB_TOKEN is not set"]
    assert classify_failure(1, stderr) == "needs-auth-or-config"


# --- the shared failure-class layer --------------------------------------------

def test_harness_error_is_separated_from_server_failure():
    assert harness_error({"batch_error": "BrokenPipeError"})
    assert harness_error({"handshake_ok": None})
    assert not harness_error({"handshake_ok": False})
    assert failure_class({"batch_error": "x"}) == HARNESS_ERROR


def test_uvx_entrypoint_artifact_is_recognised():
    row = {"handshake_ok": False, "failure_class": "crash-exit-1",
           "stderr_tail": ["An executable named `foo` is not provided by package `foo`."]}
    assert failure_class(row) == ENTRYPOINT_NOT_PROVIDED


def test_handshaking_server_has_no_failure_class():
    assert failure_class({"handshake_ok": True}) is None


# --- schema handling -------------------------------------------------------------

@pytest.mark.parametrize("prop, expected", [
    ({"type": "string"}, "string"),
    ({"type": ["string", "null"]}, "string"),
    ({"type": ["null", "integer"]}, "integer"),
    ({"type": ["null"]}, None),
    ({}, None),
    ("not a dict", None),
])
def test_schema_type_handles_unions(prop, expected):
    """A union type killed the probe on six census servers before this was fixed."""
    assert _schema_type(prop) == expected


def test_wrong_typed_args_poisons_a_required_string_with_an_integer():
    schema = {"properties": {"q": {"type": "string"}}, "required": ["q"]}
    args, name, required = wrong_typed_args(schema)
    assert args == {"q": 12345}
    assert (name, required) == ("q", True)


def test_wrong_typed_args_fills_the_other_required_properties():
    schema = {"properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
              "required": ["a", "b"]}
    args, name, _ = wrong_typed_args(schema)
    assert name == "a" and args["a"] == "not-an-int"
    assert args["b"] == "x", "a placeholder must fill the unpoisoned required property"


def test_wrong_typed_args_records_when_the_property_was_optional():
    schema = {"properties": {"q": {"type": "string"}}}
    _, _, required = wrong_typed_args(schema)
    assert required is False


def test_wrong_typed_args_returns_none_when_nothing_is_typed():
    assert wrong_typed_args({"properties": {"q": {}}}) is None
    assert wrong_typed_args("not a schema") is None


# --- the September re-run attribution -------------------------------------------

def test_sdk2_signature_from_stderr():
    row = {"stderr_tail": ["ModuleNotFoundError: No module named 'mcp.server.fastmcp'. "
                           "This is mcp 2.x, where FastMCP was renamed to MCPServer"]}
    assert sdk2_victim(row)


def test_sdk2_removed_decorator_signature():
    row = {"stderr_tail": ["AttributeError: 'Server' object has no attribute 'list_tools'"]}
    assert sdk2_victim(row)


def test_unrelated_crash_is_not_attributed_to_the_sdk():
    row = {"stderr_tail": ["AttributeError: 'Client' object has no attribute 'list_tools'"]}
    assert not sdk2_victim(row)


def test_released_classification_takes_precedence_over_stripped_stderr():
    """Withholding strips stderr, so the release carries the verdict as a field."""
    assert sdk2_victim({"rerun_break_cause": "python-sdk-2"})
    assert not sdk2_victim({"rerun_break_cause": None,
                            "stderr_tail": ["This is mcp 2.x, where FastMCP was "
                                            "renamed to MCPServer"]})

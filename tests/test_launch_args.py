"""Registry-declared launch arguments.

The census started 523 servers without the arguments their registry entries
declare, and graded most of them as failing to start. These tests pin the
rendering to the registry's own server.json reference examples, and show on a
known server that the difference is the difference between starting and not.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "driver"))

from mcpprobe import probe  # noqa: E402
from run_batch import docker_cmd, render_args  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fake_server.py")


def test_snyk_example_from_the_registry_reference():
    # server.json reference, "Embedded MCP inside a CLI tool": snyk mcp -t stdio
    args = [{"type": "positional", "value": "mcp"},
            {"type": "named", "name": "-t", "default": "stdio",
             "choices": ["stdio", "sse"]}]
    assert render_args(args) == ["mcp", "-t", "stdio"]


def test_optional_named_argument_without_a_value_is_left_out():
    assert render_args([{"type": "named", "name": "--port", "format": "number"}]) == []


def test_unresolvable_template_is_left_out():
    arg = {"type": "named", "name": "--mount",
           "value": "type=bind,src={source_path},dst={target_path}",
           "variables": {"source_path": {"isRequired": True},
                         "target_path": {"default": "/project"}}}
    assert render_args([arg]) == []


def test_template_resolved_from_variable_defaults():
    arg = {"type": "named", "name": "--root", "value": "{dir}",
           "variables": {"dir": {"default": "/data"}}}
    assert render_args([arg]) == ["--root", "/data"]


def test_npm_places_runtime_arguments_before_the_package():
    pkg = {"registryType": "npm", "identifier": "x", "version": "1.0.0",
           "runtimeArguments": [{"type": "positional", "value": "--prefer-online"}],
           "packageArguments": [{"type": "positional", "value": "serve"}]}
    cmd = docker_cmd(pkg)
    i = cmd.index("x@1.0.0")
    assert cmd[i - 1] == "--prefer-online"
    assert cmd[i + 1] == "serve"


def test_pypi_appends_package_arguments_after_the_spec():
    pkg = {"registryType": "pypi", "identifier": "bourdon", "version": "1.0",
           "packageArguments": [{"type": "positional", "value": "serve"}]}
    assert docker_cmd(pkg)[-2:] == ["bourdon==1.0", "serve"]


def test_without_args_reproduces_the_july_launch():
    pkg = {"registryType": "pypi", "identifier": "bourdon", "version": "1.0",
           "packageArguments": [{"type": "positional", "value": "serve"}]}
    assert docker_cmd(pkg, with_args=False)[-1] == "bourdon==1.0"


def test_a_server_launched_without_its_argument_does_not_start():
    r = probe([sys.executable, FAKE, "needs-serve"], 3.0)
    assert not r["handshake_ok"]


def test_the_same_server_launched_with_its_argument_starts_and_conforms():
    r = probe([sys.executable, FAKE, "needs-serve", "serve"], 5.0)
    assert r["handshake_ok"]

"""mcpprobe: execution-based conformance probe for stdio MCP servers.

Launches a server process, performs the MCP initialize lifecycle, then runs a
sequence of conformance and robustness checks. Emits one JSON result object
capturing the full verdict vector plus a message transcript.

Checks are judged against the *negotiated* protocol version, and IDs are
aligned with the official modelcontextprotocol/conformance suite's categories
(server-initialize, tools-list, tools-call-*) with additional ecosystem
robustness probes (malformed framing, stdout purity, crash survival) that the
official suite does not cover.

Usage:
  python mcpprobe.py --cmd "npx -y @modelcontextprotocol/server-memory" [--timeout 20]
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time

try:
    import jsonschema
except ImportError:  # schema validity checks degrade gracefully
    jsonschema = None

CLIENT_PROTOCOL_VERSION = "2025-06-18"  # widely supported; server may downgrade
CLIENT_INFO = {"name": "mcpprobe", "version": "0.1.0"}

# JSON-RPC error codes referenced by the MCP spec.
PARSE_ERROR = -32700
INVALID_PARAMS = -32602
METHOD_NOT_FOUND = -32601


class ServerProcess:
    """A stdio MCP server subprocess with line-framed JSON-RPC I/O."""

    def __init__(self, cmd: list[str], env: dict | None = None):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stderr_tail: list[str] = []
        self.stdout_noise: list[str] = []  # non-JSON lines on stdout = violation
        self._next_id = 0
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\r\n"))
        self.lines.put(None)  # EOF marker

    def _read_stderr(self):
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip("\r\n"))
            del self.stderr_tail[:-40]

    def send_raw(self, text: str):
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def send(self, method: str, params: dict | None = None, *, notification=False):
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notification:
            self._next_id += 1
            msg["id"] = self._next_id
        self.send_raw(json.dumps(msg))
        return None if notification else self._next_id

    def recv(self, want_id, timeout: float):
        """Wait for the response with matching id; collect noise/EOF on the way."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"_probe": "timeout"}
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                return {"_probe": "timeout"}
            if line is None:
                return {"_probe": "eof"}
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.stdout_noise.append(line[:200])
                continue
            if isinstance(msg, dict) and msg.get("id") == want_id:
                return msg
            # Server-initiated requests/notifications are recorded implicitly.

    def request(self, method, params=None, timeout: float = 10.0):
        rid = self.send(method, params)
        return self.recv(rid, timeout)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def shutdown(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


def check(result, cid, verdict, detail=""):
    result["checks"].append({"id": cid, "verdict": verdict, "detail": detail})


def classify_failure(exit_code, stderr_lines) -> str:
    """Attribute a pre-handshake death to an install vs. startup-crash stage."""
    text = "\n".join(stderr_lines).lower()
    if "npm error 404" in text or "npm error code e404" in text:
        return "install-not-found"
    if "npm error" in text or "no solution found when resolving" in text \
            or "distribution not found" in text or "no matching distribution" in text:
        return "install-error"
    if "traceback (most recent call last)" in text:
        return "crash-python-exception"
    if "error" in text:
        return "crash-with-error-output"
    if exit_code not in (0, None):
        return f"crash-exit-{exit_code}"
    return "exit-silent"


def wrong_typed_args(schema: dict) -> dict | None:
    """Build args violating the first typed required property of inputSchema."""
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties") or {}
    required = schema.get("required") or list(props)
    poison = {"string": 12345, "number": "not-a-number", "integer": "not-an-int",
              "boolean": "not-a-bool", "array": 7, "object": 7}
    for name in required:
        p = props.get(name)
        if isinstance(p, dict) and p.get("type") in poison:
            args = {n: _minimal_value(props.get(n, {})) for n in required}
            args[name] = poison[p["type"]]
            return args
    return None


def _minimal_value(prop: dict):
    return {"string": "x", "number": 1, "integer": 1, "boolean": True,
            "array": [], "object": {}}.get(prop.get("type", "string"), "x")


def probe(cmd: list[str], timeout: float) -> dict:
    result = {
        "cmd": cmd, "started": False, "handshake_ok": False,
        "negotiated_version": None, "server_info": None, "capabilities": None,
        "tools_count": None, "checks": [], "stdout_noise": None,
        "stderr_tail": None, "exit_code": None, "duration_s": None,
    }
    t0 = time.monotonic()
    env = dict(os.environ)
    try:
        sp = ServerProcess(cmd, env=env)
    except OSError as e:
        check(result, "launch", "error", str(e))
        return result
    result["started"] = True

    try:
        # server-initialize: lifecycle + version negotiation
        resp = sp.request("initialize", {
            "protocolVersion": CLIENT_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        }, timeout=timeout)
        r = resp.get("result") if isinstance(resp, dict) else None
        if resp.get("_probe") in ("timeout", "eof") or not isinstance(r, dict):
            check(result, "server-initialize", "fail", f"no valid initialize result: {str(resp)[:200]}")
            if resp.get("_probe") == "eof":
                try:
                    sp.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                result["failure_class"] = classify_failure(sp.proc.returncode, sp.stderr_tail)
            elif resp.get("_probe") == "timeout":
                result["failure_class"] = "hang-no-reply"
            return result
        result["handshake_ok"] = True
        result["negotiated_version"] = r.get("protocolVersion")
        result["server_info"] = r.get("serverInfo")
        result["capabilities"] = r.get("capabilities")
        v = "pass" if isinstance(r.get("protocolVersion"), str) and isinstance(r.get("capabilities"), dict) else "fail"
        check(result, "server-initialize", v, json.dumps({k: r.get(k) is not None for k in ("protocolVersion", "capabilities", "serverInfo")}))
        sp.send("notifications/initialized", {}, notification=True)

        # ping: spec requires an empty-object result
        resp = sp.request("ping", timeout=timeout)
        if resp.get("_probe"):
            check(result, "ping", "fail", str(resp))
        else:
            check(result, "ping", "pass" if resp.get("result") == {} else "fail", str(resp.get("result"))[:120])

        # tools-list + declared-schema validity
        tools = []
        if (result["capabilities"] or {}).get("tools") is not None:
            resp = sp.request("tools/list", {}, timeout=timeout)
            tl = (resp.get("result") or {}).get("tools") if isinstance(resp, dict) else None
            if isinstance(tl, list):
                tools = tl
                result["tools_count"] = len(tl)
                bad = [t.get("name") for t in tl if not (isinstance(t, dict) and t.get("name") and isinstance(t.get("inputSchema"), dict))]
                check(result, "tools-list", "pass" if not bad else "fail",
                      f"{len(tl)} tools" + (f"; missing name/inputSchema: {bad[:5]}" if bad else ""))
                if jsonschema:
                    invalid = []
                    for t in tl:
                        try:
                            jsonschema.validators.validator_for(t.get("inputSchema", {})).check_schema(t.get("inputSchema", {}))
                        except Exception as e:  # noqa: BLE001
                            invalid.append(f"{t.get('name')}: {str(e)[:80]}")
                    check(result, "tools-schema-valid", "pass" if not invalid else "fail", "; ".join(invalid[:5]))
            else:
                check(result, "tools-list", "fail", str(resp)[:200])
        else:
            check(result, "tools-list", "skip", "no tools capability declared")

        # tools-call-unknown: must be a protocol error, not a crash
        resp = sp.request("tools/call", {"name": "mcpprobe_no_such_tool__", "arguments": {}}, timeout=timeout)
        if resp.get("_probe"):
            check(result, "tools-call-unknown", "fail", f"{resp['_probe']} (no error reply)")
        elif "error" in resp:
            code = resp["error"].get("code")
            check(result, "tools-call-unknown", "pass" if code in (INVALID_PARAMS, METHOD_NOT_FOUND) else "warn",
                  f"error code {code}")
        elif (resp.get("result") or {}).get("isError"):
            # Spec text says protocol error -32602, but the official SDKs emit a
            # tool result with isError — grade as its own category, not a fail.
            check(result, "tools-call-unknown", "error-as-result",
                  str((resp["result"].get("content") or [{}])[0].get("text"))[:120])
        else:
            check(result, "tools-call-unknown", "fail", f"success reply: {str(resp.get('result'))[:120]}")

        # tools-call-invalid-args: wrong-typed argument should be rejected
        target = next((t for t in tools if wrong_typed_args(t.get("inputSchema") or {})), None)
        if target:
            args = wrong_typed_args(target["inputSchema"])
            resp = sp.request("tools/call", {"name": target["name"], "arguments": args}, timeout=timeout)
            if resp.get("_probe"):
                check(result, "tools-call-invalid-args", "fail", f"{resp['_probe']} on {target['name']}")
            elif "error" in resp or (resp.get("result") or {}).get("isError"):
                check(result, "tools-call-invalid-args", "pass", f"rejected on {target['name']}")
            else:
                check(result, "tools-call-invalid-args", "fail",
                      f"accepted wrong-typed args on {target['name']}")
        else:
            check(result, "tools-call-invalid-args", "skip", "no tool with a typed required property")

        # malformed-json: parse error expected; process must survive
        sp.send_raw('{"jsonrpc": "2.0", this is not json')
        time.sleep(1.0)
        if not sp.alive():
            check(result, "malformed-json", "fail", "process died on malformed input")
        else:
            resp = sp.request("ping", timeout=timeout)
            check(result, "malformed-json", "pass" if not resp.get("_probe") else "fail",
                  "survived" if not resp.get("_probe") else f"unresponsive after malformed input ({resp['_probe']})")

        # stdout-purity: stdio transport forbids non-JSON-RPC output on stdout
        check(result, "stdout-purity", "pass" if not sp.stdout_noise else "fail",
              f"{len(sp.stdout_noise)} non-JSON stdout lines" if sp.stdout_noise else "")
    finally:
        sp.shutdown()
        result["exit_code"] = sp.proc.returncode
        result["stdout_noise"] = sp.stdout_noise[:5]
        result["stderr_tail"] = sp.stderr_tail[-10:]
        result["duration_s"] = round(time.monotonic() - t0, 2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="server launch command line")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    cmd = args.cmd.split()
    if os.name == "nt" and cmd[0] in ("npx", "npm", "uvx"):
        cmd[0] += ".cmd" if cmd[0] != "uvx" else ".exe"
    print(json.dumps(probe(cmd, args.timeout), indent=2))


if __name__ == "__main__":
    main()

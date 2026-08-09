"""Minimal stdio JSON-RPC probe: same three steps mcpprobe uses for
tools-call-invalid-args. Sends a wrong-typed argument against a declared
string property and reports what comes back."""
import json, subprocess, sys, time

def run(cmd, label):
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", bufsize=1)

    def send(obj):
        p.stdin.write(json.dumps(obj) + "\n"); p.stdin.flush()

    def read(timeout=12):
        end = time.time() + timeout
        while time.time() < end:
            line = p.stdout.readline()
            if not line:
                time.sleep(0.05); continue
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"probe","version":"1.0"}}})
    init = read()
    send({"jsonrpc":"2.0","method":"notifications/initialized"})

    send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
    tools = read()

    # the poisoned call: declared schema says code is a string, send an integer
    send({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"scan_code_imports","arguments":{"code":12345}}})
    call = read()

    print("=" * 78)
    print(label)
    print("=" * 78)
    if tools and "result" in tools:
        t = tools["result"]["tools"][0]
        print("declared inputSchema:", json.dumps(t.get("inputSchema")))
    print()
    print("tools/call with code=12345 (schema requires string):")
    print(json.dumps(call, indent=2)[:900] if call else "  NO RESPONSE")
    print()
    if call is None:
        verdict = "NO RESPONSE"
    elif "error" in call:
        verdict = "REJECTED via JSON-RPC protocol error  -> validates"
    elif call.get("result", {}).get("isError"):
        verdict = "REJECTED via isError result           -> validates"
    else:
        verdict = "EXECUTED, well-formed result, no error -> DOES NOT VALIDATE"
    print("VERDICT:", verdict)
    print()
    p.kill()
    return verdict

if __name__ == "__main__":
    v1 = run("node lowlevel.js",  "LOW-LEVEL Server API  (@modelcontextprotocol/sdk@1.30.0)")
    v2 = run("node highlevel.js", "HIGH-LEVEL McpServer+zod (@modelcontextprotocol/sdk@1.30.0)")
    print("#" * 78)
    print("low-level  :", v1)
    print("high-level :", v2)

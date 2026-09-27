"""A minimal stdio MCP server whose behaviour is chosen on the command line.

The harness grades servers it has never seen, so the only way to know its verdicts
are right is to point it at servers whose correct verdict is known in advance. Each
mode below reproduces one behaviour the census reports, from the fully conforming
server to the SDK default to the ones that break.

    python fake_server.py conforming
    python fake_server.py sdk-default      unknown tool -> isError, no arg checking
    python fake_server.py dies-on-malformed
    python fake_server.py noisy            prints a banner on stdout
    python fake_server.py crash            Python traceback before initialize
    python fake_server.py needs-config     exits asking for an API key
    python fake_server.py hang             never answers initialize
"""

import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "conforming"

TOOL = {
    "name": "echo",
    "description": "Echo a string back.",
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def reply(msg_id, result):
    send({"jsonrpc": "2.0", "id": msg_id, "result": result})


def error(msg_id, code, message):
    send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def tool_error(msg_id, text):
    reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})


def main():
    if MODE == "crash":
        sys.stderr.write("Traceback (most recent call last):\n"
                         '  File "server.py", line 1, in <module>\n'
                         "ModuleNotFoundError: No module named 'nothing'\n")
        sys.exit(1)
    if MODE == "needs-config":
        sys.stderr.write("Error: the environment variable EXAMPLE_API_KEY is not set\n")
        sys.exit(1)
    if MODE == "noisy":
        sys.stdout.write("Server starting up, hello!\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            if MODE == "dies-on-malformed":
                sys.exit(2)
            error(None, -32700, "Parse error")
            continue

        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:
            continue  # notification
        if MODE == "hang":
            continue

        if method == "initialize":
            reply(msg_id, {"protocolVersion": "2025-06-18",
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "fake", "version": "0"}})
        elif method == "ping":
            reply(msg_id, {})
        elif method == "tools/list":
            reply(msg_id, {"tools": [TOOL]})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            if name != TOOL["name"]:
                if MODE == "conforming":
                    error(msg_id, -32602, f"Unknown tool: {name}")
                else:
                    tool_error(msg_id, f"Unknown tool: {name}")
                continue
            if not isinstance(args.get("text"), str) and MODE == "conforming":
                tool_error(msg_id, "text must be a string")
                continue
            reply(msg_id, {"content": [{"type": "text", "text": str(args.get("text"))}]})
        else:
            error(msg_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()

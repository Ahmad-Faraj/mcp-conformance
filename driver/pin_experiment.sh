#!/bin/bash
# Does pinning the Python SDK below 2.0 restore a server that broke between runs?
#
# Each server is launched twice: once as the census launches it, which resolves the
# newest mcp, and once with mcp constrained below 2.0. The probe is a bare
# initialize frame; we only care whether the process answers at all.
IMG=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
HARD="--rm -i --init --memory 768m --cpus 1 --pids-limit 256 --security-opt no-new-privileges --cap-drop ALL"
FRAME='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"pin-test","version":"1"}}}'

probe () {  # $1 = spec, $2... = extra uvx args
  local spec="$1"; shift
  local out
  out=$(printf '%s\n' "$FRAME" | timeout 120 docker run $HARD $IMG uvx "$@" "$spec" 2>/dev/null | head -c 2000)
  if echo "$out" | grep -q '"result"'; then echo "handshake"; else echo "no"; fi
}

while read -r pkg ver; do
  [ -z "$pkg" ] && continue
  spec="${pkg}==${ver}"
  a=$(probe "$spec")
  b=$(probe "$spec" --with "mcp<2")
  printf '%-34s current=%-10s mcp<2=%s\n' "$pkg" "$a" "$b"
done < ~/pin_sample.txt

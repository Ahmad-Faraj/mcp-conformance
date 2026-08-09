# SDK validation probe

Reproduces the SDK-level result in Section 3.7 / 4.3 of the paper: on
`@modelcontextprotocol/sdk@1.30.0`, the low-level `Server` API publishes an
`inputSchema` in `tools/list` but does not check `tools/call` arguments against it,
while the high-level `McpServer` API does.

Both servers expose one tool declaring a single required string property. The probe
sends the same poisoned call the census uses for `tools-call-invalid-args`: an integer
where the schema requires a string.

## Run

```bash
npm install
python probe.py
```

## Expected output

```
LOW-LEVEL Server API   -> EXECUTED, well-formed result, no error -> DOES NOT VALIDATE
HIGH-LEVEL McpServer   -> REJECTED via isError result            -> validates
```

The low-level handler receives `typeof=number` against a schema requiring a string and
returns ordinary output. The high-level server returns
`isError: true` with `MCP error -32602: Input validation error`.

## Why it matters

129 servers in the census executed a tool on an argument their own declared schema
rejects. 112 are on the official TypeScript SDK; 0 are on either Python SDK, which
validate on both paths via Pydantic. This probe isolates the cause to the API path
rather than to the authors.

Reported upstream: see `SDK_ISSUE_DRAFT.md` in the study repository.

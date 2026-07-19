# mcpprobe: Execution-Based Conformance Measurement for MCP Servers

`mcpprobe` installs Model Context Protocol (MCP) servers from a registry, runs
each in an isolated sandbox, and drives it through a suite of protocol-conformance
and robustness checks. It is the measurement harness behind the study *"Does Your
MCP Server Actually Follow the Protocol? A Large-Scale Execution-Based Conformance
Study of the Model Context Protocol Ecosystem."*

Where the official `modelcontextprotocol/conformance` suite tests the handful of
official SDKs in CI, `mcpprobe` extends the same categories of scenarios to
*arbitrary deployed servers*, so any author can check their server's conformance
before publishing, and researchers can measure the ecosystem at scale.

## What it checks

Each server is graded against the protocol version it **negotiates** (not the
latest spec). Verdicts: `pass` / `fail` / `warn` / `skip` / `error-as-result`.

| Check | What it verifies |
|-------|------------------|
| `server-initialize` | `initialize` returns a protocol version + capabilities; lifecycle completes |
| `ping` | `ping` returns an empty-object result |
| `tools-list` | every advertised tool has a `name` and an `inputSchema` object |
| `tools-schema-valid` | each `inputSchema` is a valid JSON Schema (meta-validated) |
| `tools-call-unknown` | an unknown tool is rejected; records protocol-error vs. `isError`-result mechanism |
| `tools-call-invalid-args` | a wrong-typed required argument is not silently accepted |
| `malformed-json` | the server survives a malformed frame (no crash/hang) |
| `stdout-purity` | stdio transport carries only protocol messages on stdout |

`error-as-result` is a first-class category, not a failure: the spec expresses the
unknown-tool→protocol-error behavior in prose and an example (no RFC-2119
`MUST`/`SHOULD`), and the official SDKs default to an `isError` result, so we
*measure* which mechanism a server uses rather than judging it.

## Safety

Executing thousands of untrusted packages is the core hazard, so **both** the
install phase (which runs arbitrary `postinstall`/build scripts) and the probe
phase run in containers with `--cap-drop ALL`, `--security-opt no-new-privileges`,
memory/CPU/PID caps, and no host mounts except a package-cache volume. Probing
additionally runs with `--network=none`. Do not disable these.

## Usage

```bash
# 1. Harvest the registry sampling frame
python harvest/harvest_registry.py
python harvest/frame_stats.py

# 2. Probe a seeded random sample (two-phase: install online, probe offline)
python driver/run_batch.py --n 1600 --seed 42 --offline-probe --skip-done

# 3. Analyze
python driver/analyze.py                 # funnel, verdict matrix, failure classes
python driver/taxonomy.py                # startup + conformance taxonomies -> findings.csv
python driver/detect_sdk.py              # SDK attribution -> sdk_attribution.csv

# 4. Regenerate all paper artifacts from the data
python driver/make_numbers.py            # numbers.tex (Wilson CIs)
python driver/make_tables.py             # startup/verdicts/sdk tables
python driver/make_figures.py            # funnel + by-registry figures
python driver/make_disclosure.py         # private responsible-disclosure log

# Probe a single server directly
python driver/mcpprobe.py --cmd "npx -y @modelcontextprotocol/server-everything"
```

## Reproducibility

Every reported number regenerates from the released raw transcripts and the
pinned harness commit (tag `harness-v1.0`). The registry snapshot date, sampling
seed, base images, and package versions are all recorded. Because the registry is
a moving target, the snapshot---not the live registry---is the object of study.

## Responsible disclosure

Security-relevant findings (e.g., crash/hang on malformed input) are reported to
maintainers before publication and released only in aggregate; the public dataset
is filtered accordingly. See `PROTOCOL.md`.

## Layout

```
harvest/     registry crawler + sampling-frame stats
driver/      mcpprobe harness, sandbox runner, analysis + paper-artifact generators
paper/       LaTeX source (numbers/tables/figures auto-generated from data)
data/        sampling frame + probe results (generated; git-ignored)
PROTOCOL.md  full study protocol, RQs, sampling, ethics
```

## License

MIT (harness). Dataset released under CC BY 4.0 after disclosure filtering.

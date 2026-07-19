# Study Protocol — Execution-Based Conformance Study of the MCP Server Ecosystem

*Working title: "Does Your MCP Server Actually Follow the Protocol? A Large-Scale
Execution-Based Conformance Study." Started 2026-07-19.*

## Research questions

- **RQ1 (Runnability):** What fraction of registry-published, locally-installable MCP
  servers actually start and complete a protocol handshake? (The install→handshake
  funnel has never been measured.)
- **RQ2 (Protocol conformance):** How do runnable servers conform to the MCP spec at the
  *negotiated* protocol version: lifecycle, ping, tools/list shape, declared JSON-Schema
  validity?
- **RQ3 (Robustness):** How do servers behave on inputs a real agent session can produce:
  unknown tool names, wrong-typed arguments, malformed JSON framing? Crashes, hangs,
  silent acceptance?
- **RQ4 (Spec vs. practice):** Where does ecosystem behavior systematically diverge from
  spec text (e.g., error-as-result vs. protocol error, stdout purity)? Do even official
  SDK defaults diverge?
- **RQ5 (Correlates):** Do violations correlate with package registry, SDK, popularity,
  or maintenance status?

## Positioning

All prior MCP ecosystem studies are static: code scanning (2506.13538, 1,899 servers),
registry crawling (2509.25292, 8,060 projects), or issue mining (2606.05339, 837 fault
threads). The official `modelcontextprotocol/conformance` suite executes only the five
official SDKs over HTTP in CI. **One line: the official suite tests five SDKs; we test
the seventeen-thousand-server ecosystem built on them.** The issue-mining taxonomy found
tool faults and schema enforcement to be the top fault categories — motivation we cite:
they saw the smoke in issue trackers; we measure the fire.

### Novelty boundary (adversarial check, 2026-07-19)

Closest works verified and differentiated:
- **Security-invariants benchmark (2606.29073):** fixture-based, "deliberately avoids live
  third-party execution"; its ecosystem sample is 40 repos of README metadata. No conformance.
- **MCP-SandboxScan (2601.01241), VIPER-MCP (2605.21392), malicious-server detection
  (2604.01905):** security/vulnerability detection on curated or vulnerable-by-design sets,
  not spec conformance across the registry ecosystem.
- **Remote-server auth study (2605.22333):** remote servers, authentication security only.
- **Practitioner blogs (non-peer-reviewed, cite as motivation):** RapidClaw "52% dead"
  audit (1,847 servers — maintenance-liveness rubric, methodology and data not public);
  digitalapplied 100-server stress test (task success, not protocol conformance).
- **Community signal:** modelcontextprotocol Discussion #2682 proposes a pre-publish
  conformance checklist — the ecosystem is asking for exactly this measurement; nobody
  has done it.

No academic work executes registry-published MCP servers at scale and measures protocol
conformance. Claim stands as of 2026-07-19.

## Sampling frame

Official registry (`registry.modelcontextprotocol.io`) crawled 2026-07-19: 54,320
published versions → 17,432 unique servers (17,252 active). Latest version per name kept
(`data/frame_latest.jsonl`). Runnability classes: 8,659 package-only, 7,572 remote-only,
897 both, 304 neither. Study population: package-declaring servers with stdio transport
on npm/PyPI (largest classes: 6,361 npm, 2,760 PyPI; 10,008 stdio transports),
**restricted to servers declaring no required-without-default env vars or arguments**
(self-contained). Selection bias toward self-contained servers is reported honestly; the
excluded classes are enumerated in the funnel. Remote-only servers are out of scope for
execution (future work: a read-only handshake census).

## Harness

- `driver/mcpprobe.py` — hand-rolled line-framed JSON-RPC over stdio (deliberately not
  the SDK: we must be able to send malformed frames and observe raw behavior, and the
  probe must not inherit SDK-side corrections).
- Client offers protocol version 2025-06-18; the negotiated version is recorded and all
  verdicts are judged **against the version the server negotiated**, not the latest spec.
- Checks (IDs aligned with official conformance suite categories where they exist):
  `server-initialize`, `ping`, `tools-list`, `tools-schema-valid` (JSON Schema
  meta-validation), `tools-call-unknown`, `tools-call-invalid-args` (type-poisoned
  required property), `malformed-json` (parse-error survival), `stdout-purity`
  (stdio transport forbids non-protocol stdout).
- Verdicts: `pass` / `fail` / `warn` / `skip` / `error-as-result` (spec-practice
  divergence category — the official reference servers themselves surface unknown-tool
  as `isError` results rather than JSON-RPC −32602; calibrated 2026-07-19 against
  `server-memory` 0.6.3 and `server-everything` 2.0.0, which pass all other checks).
- Full transcript-level records: negotiated version, serverInfo, capabilities, timing,
  stderr tail, stdout noise, exit code.

## Sandbox

Each server runs in a fresh container (`node:22-slim` / astral-sh uv image):
`--rm -i --init`, 768 MB memory cap, 1 CPU, pids-limit 256, `no-new-privileges`, no host
mounts except named cache volumes (npm/uv) to amortize installs. Network is enabled in
the pilot (package installation requires it); the full run will split install and probe
phases so probing happens with `--network=none`. Nothing from a probed server touches
the host filesystem.

## Network condition (dataset hygiene)

Decided 2026-07-19: the n=223 pilot was probed *with* network access (development
data only). The final *reported* dataset is a single clean run entirely under
`--network=none` (two-phase: install online, probe offline). This removes network
flakiness and any server-side outbound calls as confounders, and makes "conformance
under isolation" a crisp, reproducible condition. Cache-warming from pilot/dev runs
makes the final offline re-run fast. Any server whose behavior differs online vs.
offline is itself recorded (a server that *requires* network during a probe is a
finding, not noise).

## Funnel reporting (RQ1)

Every stage is counted and reported: declared → eligible (self-contained stdio npm/pypi)
→ sampled → container started → process launched → handshake completed → probed. The
yield rate at each stage is itself a headline result.

## Ethics / responsible disclosure

Aggregate reporting only; no name-and-shame of individual servers for
security-relevant failures without prior maintainer notification. Crash-on-malformed-input
findings that look exploitable get reported to maintainers before any per-server data
release. Per-server dataset release will exclude exploitability details pending
disclosure windows.

## Artifacts to release

1. `mcpprobe` conformance harness (open source).
2. Registry sampling frame + probe-result dataset (post-disclosure filtering).
3. The paper (arXiv → MSR/FSE/DSN 2027 track).

## Key finding: error-as-result is SDK-institutionalized (RQ4)

Spec language pinned (2025-06-18, "Tools > Error Handling"): the spec categorizes
"Unknown tools" and "Invalid arguments" under *Protocol Errors* (JSON-RPC) and
illustrates \texttt{-32602}, but uses **no RFC-2119 MUST/SHOULD** — it is prose plus an
example. Therefore we report a *spec-implementation divergence*, never a "violation."
The invalid-args case is further softened because the spec also lists "Invalid input
data" under *Tool Execution Errors* (isError) — genuinely ambiguous — so we accept either
a protocol error or isError, flagging only plain-success.

SDK attribution (from npm/PyPI dependency metadata, no execution) cross-tabbed against the
unknown-tool verdict (n=217 handshaking, dev data): official-ts 119/137 error-as-result,
official-py 30/37, fastmcp-py 24/24 (100%), hand-rolled 7/8. The divergence tracks the SDK,
not the author. Direct confirmation from official reference servers (server-memory,
server-everything = TS; mcp-server-time = Python/FastMCP) — all error-as-result. Framing:
"the official SDKs institutionalized a divergence from the written spec, and the ecosystem
inherited it." 5 official-ts servers *do* emit -32602 → achievable but not the default.
Natural upstream contribution: a well-evidenced SDK issue, filed from Ahmed's account later.

## Review-driven hardening (2026-07-19, external review)

Adopted: (#1) SDK attribution above; (#2) spec-language pinning + reframe; (#5) install
phase now runs under the same cap-drop ALL + no-new-privileges + resource caps as probing
(`HARDENING` in run_batch.py); (#6) `needs-auth-or-config` failure class separates
credential-requirement from crashes so the npm/PyPI yield gap isn't confounded; (#8) each
result carries `harness_commit`; raw JSON-RPC transcripts written to `data/transcripts/`.
Already in place before review: version-negotiated grading (#3), seeded random sampling
(#7), Wilson CIs (#9), check IDs aligned to the official conformance suite (#10), aggregate-
only disclosure policy (#4, formal disclosure log still TODO). Harness to be frozen (git tag)
before the final clean run; all prior data is development-only and will be superseded by one
clean offline run on the frozen harness.

## Status log

- 2026-07-19: Frame harvested (17,432 servers). Driver v0.1 validated on official
  reference servers. First divergence found (error-as-result vs −32602). Sandbox
  runner built; 20-server pilot launched.

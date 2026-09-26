"""Generate paper/numbers.tex from the final dataset.

Every number cited in the paper comes from here, so prose can never drift from
data. Run after the final clean dataset is complete.

Usage:
  python make_numbers.py [--in data/probe_results.jsonl] [--out paper/numbers.tex]
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from failure_classes import UVX_NO_EXE as UVX_RE, harness_error
from stats import cluster_ci, cluster_diff_ci, design_effect, wilson

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def pctci(k, n):
    p, lo, hi = wilson(k, n)
    return f"{100*p:.1f}\\% (95\\% CI {100*lo:.1f}--{100*hi:.1f})"


def load(path):
    by = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r.get("server_name") or json.dumps(r.get("cmd"))] = r
    return list(by.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_results.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "numbers.tex"))
    ap.add_argument("--frame", default=str(DATA / "frame_latest.jsonl"))
    ap.add_argument("--reprobe", default=str(DATA / "entrypoint_reprobe.jsonl"),
                    help="completed re-probe of entry-point-blocked PyPI servers")
    args = ap.parse_args()

    attempted = load(Path(args.inp))
    # Rows where our own harness died (broken pipe, uncaught exception) carry no verdict
    # about the server, so they are reported separately and excluded from every
    # denominator instead of counting as servers that failed to start.
    harness_rows = [r for r in attempted if harness_error(r)]
    rows = [r for r in attempted if not harness_error(r)]
    n_attempted = len(attempted)
    # Runs the host stopped: the memory cap or the disk guard sends SIGKILL (137).
    killed = sum(1 for r in attempted if r.get("exit_code") == 137)
    # Probes that ended for a reason that may lie outside the server: killed by a
    # resource cap, or aborted by the harness. The two sets are disjoint here, but
    # we take the union so they stay disjoint if that ever changes.
    # Servers whose only barrier is an undeclared setting. The registry records no
    # required configuration, so a client reading the listing cannot know in advance.
    n_needs_config = sum(1 for r in attempted
                         if r.get("failure_class") == "needs-auth-or-config")

    interrupted = [r for r in attempted
                   if harness_error(r) or r.get("exit_code") == 137]
    n_interrupted = len(interrupted)
    n_interrupted_nohs = sum(1 for r in interrupted if not r.get("handshake_ok"))

    # Identities withheld from the release: the security-relevant check failures plus
    # the servers that ran a tool on an argument their own schema rejects.
    _sec = {("malformed-json", "fail"), ("stdout-purity", "fail"),
            ("tools-call-unknown", "fail"), ("tools-call-invalid-args", "fail")}
    def _beside(census, name):
        """Find a companion file next to the census we were handed.

        Run against the release, that is the release's own copy, whose server
        names are the same pseudonyms the released rows carry -- so joins land and
        the counts are recomputable by anyone holding only the release. Reading the
        private copy here would silently under-count, because its keys are the real
        names.
        """
        beside = Path(census).resolve().parent / name
        return beside if beside.exists() else DATA / name

    # Resolve the consequences file beside the census we were given. Run against the
    # release, that is the release's copy, whose server names are the same
    # pseudonyms the released rows carry -- so the join still lands and the count
    # is recomputable by anyone holding only the release. Reading the private copy
    # here would silently under-count, because its keys are the real names.
    _cons_file = _beside(args.inp, "consequences.json")
    _silent = set()
    if _cons_file.exists():
        _c = json.loads(_cons_file.read_text(encoding="utf-8"))
        _silent = {r["server"] for r in _c.get("silent-execution", [])
                   if isinstance(r, dict) and r.get("server")}
    withheld = sum(1 for r in attempted if r.get("handshake_ok") and (
        r.get("server_name") in _silent
        or any((c.get("id"), c.get("verdict")) in _sec and c.get("id") != "tools-call-invalid-args"
               for c in r.get("checks", []))))
    disclosure_high = len(_silent) + sum(
        1 for r in attempted if r.get("handshake_ok")
        and any(c.get("id") == "malformed-json" and c.get("verdict") == "fail"
                for c in r.get("checks", [])))
    n = len(rows)
    hs = sum(1 for r in rows if r.get("handshake_ok"))
    responders = [r for r in rows if r.get("handshake_ok")]
    n_resp = len(responders)

    def resp_rate(pred):
        k = sum(1 for r in responders for c in r.get("checks", []) if pred(c))
        return k, pctci(k, n_resp)

    err_as_result_k, err_as_result = resp_rate(
        lambda c: c["id"] == "tools-call-unknown" and c["verdict"] == "error-as-result")
    notypecheck_k, notypecheck = resp_rate(
        lambda c: c["id"] == "tools-call-invalid-args" and c["verdict"] == "fail")
    # The rest of the unknown-tool responses split three ways: a protocol error with
    # the illustrated code (pass), a protocol error with another code (warn), and a
    # plain success that explains the failure only in prose (fail).
    unk_pe_k, unk_pe = resp_rate(
        lambda c: c["id"] == "tools-call-unknown" and c["verdict"] == "pass")
    unk_wrong_k, unk_wrong = resp_rate(
        lambda c: c["id"] == "tools-call-unknown" and c["verdict"] == "warn")
    unk_prose_k, unk_prose = resp_rate(
        lambda c: c["id"] == "tools-call-unknown" and c["verdict"] == "fail")
    malformed_k, malformed = resp_rate(
        lambda c: c["id"] == "malformed-json" and c["verdict"] == "fail")

    with open(args.frame, encoding="utf-8") as _f:
        frame_n = sum(1 for _ in _f)

    # Publisher clustering. Registry names are "namespace/server", and a single
    # publisher can account for hundreds of servers that share a template and
    # behave near-identically -- so they are not independent trials and the Wilson
    # intervals above are too narrow. Recompute each headline rate on a subset
    # holding one server per publisher, to bound how far the clustering moves it.
    def publisher(r):
        # The public release carries a hashed publisher_id, because pseudonymised
        # server names lose their namespace prefix. Prefer it when present so the
        # clustering check reproduces identically from the released dataset.
        return r.get("publisher_id") or (r.get("server_name") or "").split("/")[0]

    def clustered(sub, pred):
        """Publisher-cluster bootstrap interval for a predicate over a row subset."""
        units = [(publisher(r), pred(r)) for r in sub]
        p, lo, hi = cluster_ci(units)
        return f"{100*p:.1f}\\% (95\\% CI {100*lo:.1f}--{100*hi:.1f})"

    def diff_ci(pred, sub):
        npm = [(publisher(r), pred(r)) for r in sub if r.get("registry_type") == "npm"]
        pypi = [(publisher(r), pred(r)) for r in sub if r.get("registry_type") == "pypi"]
        d, lo, hi = cluster_diff_ci(npm, pypi)
        return f"{d:.1f} pp (95\\% CI {lo:.1f}--{hi:.1f})"

    def check_pred(cid, verdict):
        return lambda r: any(c["id"] == cid and c["verdict"] == verdict
                             for c in r.get("checks", []))

    ver_counts = Counter(r.get("negotiated_version") for r in responders)
    pub_counts = Counter(publisher(r) for r in rows)
    # How far the single largest publisher moves the headline runnability figure.
    _top_id = pub_counts.most_common(1)[0][0] if pub_counts else None
    _top_rows = [r for r in rows if publisher(r) == _top_id]
    _rest = [r for r in rows if publisher(r) != _top_id]
    top_pub_rate = (f"{100*sum(1 for r in _top_rows if r.get('handshake_ok'))/len(_top_rows):.1f}\\%"
                    if _top_rows else "-")
    _rest_rate = (sum(1 for r in _rest if r.get("handshake_ok")) / len(_rest)) if _rest else 0
    top_pub_drop = f"{100*(_rest_rate - hs/n):.1f}" if n else "-"
    seen, uniq = set(), []
    for r in rows:
        p = publisher(r)
        if p not in seen:
            seen.add(p)
            uniq.append(r)
    uniq_resp = [r for r in uniq if r.get("handshake_ok")]
    uniq_hs = len(uniq_resp)
    top_n = pub_counts.most_common(1)[0][1] if pub_counts else 0
    top10_n = sum(v for _, v in pub_counts.most_common(10))

    def uniq_rate(cid, verdict):
        k = sum(1 for r in uniq_resp for c in r.get("checks", [])
                if c["id"] == cid and c["verdict"] == verdict)
        return pctci(k, uniq_hs)

    # Entry-point correction. `uvx <pkg>` resolves only when a PyPI package's console
    # script is named after the package, so servers whose script differs installed
    # fine but were never launched -- a harness artifact, not a server defect. We
    # re-probed ALL of them with the entry point resolved; those results correct the
    # runnability numbers. (An early 30-server pilot suggested a far higher recovery
    # rate; the complete re-probe supersedes it and is what we report.)
    reprobe = load(Path(args.reprobe)) if Path(args.reprobe).exists() else []
    # A server counts as runnable once the entry-point artifact is corrected.
    _recovered = {r.get("server_name") for r in reprobe if r.get("handshake_ok")}

    def corrected_ok(r):
        return bool(r.get("handshake_ok")) or r.get("server_name") in _recovered
    ep_n = len(reprobe)
    ep_ok = sum(1 for r in reprobe if r.get("handshake_ok"))
    hs_corr = hs + ep_ok

    def reg_split(reg):
        sub = [r for r in rows if r.get("registry_type") == reg]
        return len(sub), sum(1 for r in sub if r.get("handshake_ok"))

    npm_n, npm_hs = reg_split("npm")
    pypi_n, pypi_hs = reg_split("pypi")
    npm_p = 100 * npm_hs / npm_n if npm_n else 0
    pypi_p = 100 * pypi_hs / pypi_n if pypi_n else 0
    pypi_p_corr = 100 * (pypi_hs + ep_ok) / pypi_n if pypi_n else 0

    # SDK attribution of the silent-execution population (Section 4.3). The
    # unknown-tool divergence tracks the SDK (Table 4); this checks whether the
    # input-validation failure does too. It does, and far more sharply: the
    # behaviour is confined to one SDK family. Joins the classified consequences
    # against the same package-metadata attribution used for Table 4.
    import csv as _csv
    _cons_p = _cons_file
    _sdk_p = _beside(args.inp, "sdk_attribution.csv")
    silent_fam = Counter()
    silent_major = Counter()
    silent_ver = Counter()
    # Denominators and edge types for the SDK attribution, so the prose never
    # retypes a count that the attribution run can change.
    fam_tot = Counter()
    fam_ear = Counter()
    edge_tot = Counter()
    if _cons_p.exists() and _sdk_p.exists():
        _cons = json.loads(_cons_p.read_text(encoding="utf-8"))
        with _sdk_p.open(encoding="utf-8") as _f:
            _sdk = {r["server"]: r for r in _csv.DictReader(_f)}
        for _row in _sdk.values():
            fam_tot[_row["sdk_family"]] += 1
            edge_tot[_row.get("sdk_edge") or "unattributed"] += 1
            if _row["unknown_verdict"] == "error-as-result":
                fam_ear[_row["sdk_family"]] += 1
        for _rec in _cons.get("silent-execution", []):
            _row = _sdk.get(_rec.get("server"))
            if not _row:
                silent_fam["unattributed"] += 1
                continue
            silent_fam[_row["sdk_family"]] += 1
            if _row["sdk_family"] == "official-ts":
                _v = _row.get("sdk_version") or "?"
                _m = re.match(r"[^0-9]*(\d+)", _v)
                silent_major[_m.group(1) if _m else "?"] += 1
                silent_ver[_v] += 1
    silent_ts = silent_fam.get("official-ts", 0)
    silent_py = silent_fam.get("official-py", 0) + silent_fam.get("fastmcp-py", 0)
    silent_ts_v1 = silent_major.get("1", 0)
    # Range style matters: a caret range floats to the newest 1.x at install time,
    # so these servers ran a current SDK and would pick up a 1.x fix automatically.
    # An exact version would not. Reporting them as "pinned" would invert that.
    silent_ts_caret = sum(v for k, v in silent_ver.items() if k.startswith("^"))
    silent_ts_exact = sum(v for k, v in silent_ver.items() if k and k[0].isdigit())
    sdk_ts_pop = fam_tot.get("official-ts", 0)
    sdk_py_pop = fam_tot.get("official-py", 0) + fam_tot.get("fastmcp-py", 0)
    sdk_nosdk_pop = fam_tot.get("none-handrolled", 0)
    sdk_nosdk_ear = fam_ear.get("none-handrolled", 0)

    # Entry-point re-probe coverage: the census classifier finds this many uvx
    # entry-point rows, and the completed re-probe covers this many of them.
    ep_seen = sum(1 for r in rows
                  if any(UVX_RE.search(x or "") for x in (r.get("stderr_tail") or [])))
    ep_missing = ep_seen - ep_n

    # How many malformed-frame failures sit in a language our SDK attribution cannot
    # resolve. detect_sdk.py reads npm and PyPI dependency graphs, so a server
    # compiled from Go, Rust, Swift or Dart and shipped as a binary declares no MCP
    # dependency and lands in the no-known-SDK residual whatever it is built on. A
    # maintainer demonstrated exactly this for the official Go SDK.
    n_opaque = n_go = 0
    _lang_p = _beside(args.inp, "repo_languages.csv")
    if _lang_p.exists():
        with _lang_p.open(encoding="utf-8") as _f:
            _langs = list(_csv.DictReader(_f))
        n_opaque = sum(1 for r in _langs
                       if r["attributable"] == "false" and r["language"])
        n_go = sum(1 for r in _langs if r["language"] == "Go")

    # The Go servers hiding inside the no-known-SDK residual are a natural experiment
    # on the paper's central claim: a third SDK, never sampled as a family, whose
    # defaults differ from the TypeScript and Python ones on two separate checks.
    # Identified by repository language rather than by dependency graph, because a Go
    # binary shipped through npm declares no MCP dependency at all.
    go_n = go_resp = go_malformed = go_unknown_proto = 0
    _res_p = _beside(args.inp, "residual_languages.csv")
    if _res_p.exists():
        with _res_p.open(encoding="utf-8") as _f:
            _go = [r["server"] for r in _csv.DictReader(_f) if r["language"] == "Go"]
        go_n = len(_go)
        _by_name = {r.get("server_name"): r for r in attempted}

        def _verdict(_name, _check):
            for _c in (_by_name.get(_name, {}).get("checks") or []):
                if _c["id"] == _check:
                    return _c["verdict"]
            return None

        _responding = [n for n in _go if (_by_name.get(n) or {}).get("handshake_ok")]
        go_resp = len(_responding)
        go_malformed = sum(1 for n in _responding
                           if _verdict(n, "malformed-json") == "fail")
        go_unknown_proto = sum(1 for n in _responding
                               if _verdict(n, "tools-call-unknown") == "pass")

    macros = {
        "Nframe": f"{frame_n:,}",
        "Nattempted": f"{n_attempted:,}",
        "NHarnessError": f"{len(harness_rows):,}",
        "NHarnessErrorPct": f"{100*len(harness_rows)/n_attempted:.1f}\\%",
        "NWithheld": f"{withheld:,}",
        "NDisclosureHigh": f"{disclosure_high:,}",
        "NKilled": f"{killed:,}",
        "NKilledPct": f"{100*killed/n_attempted:.1f}\\%",
        "NInterrupted": f"{n_interrupted:,}",
        "NInterruptedPct": f"{100*n_interrupted/n_attempted:.1f}\\%",
        "NInterruptedNoHandshake": f"{n_interrupted_nohs:,}",
        "NInterruptedDepressionPP": f"{100*n_interrupted_nohs/n_attempted:.1f}",
        "Nprobed": f"{n:,}",
        "NNeedsConfig": f"{n_needs_config:,}",
        "NMalformedOpaque": f"{n_opaque:,}",
        "NMalformedGo": f"{n_go:,}",
        "NGoResidual": f"{go_n:,}",
        "NGoResponding": f"{go_resp:,}",
        "NGoMalformedFail": f"{go_malformed:,}",
        "GoMalformedRate": (f"{100*go_malformed/go_resp:.0f}" + chr(92) + "%"
                            if go_resp else "n/a"),
        "NGoUnknownProto": f"{go_unknown_proto:,}",
        "NEntrypointSeen": f"{ep_seen:,}",
        "NEntrypointUnreprobed": f"{ep_missing:,}",
        # Publisher-cluster bootstrap intervals. These are the intervals the paper
        # reports, because servers from one publisher are not independent trials.
        "HandshakeRateCl": clustered(rows, lambda r: r.get("handshake_ok")),
        "ErrAsResultRateCl": clustered(
            responders, check_pred("tools-call-unknown", "error-as-result")),
        "NoTypecheckRateCl": clustered(
            responders, check_pred("tools-call-invalid-args", "fail")),
        "MalformedDiesRateCl": clustered(
            responders, check_pred("malformed-json", "fail")),
        # Registry comparison, same method applied to both outcomes so neither is
        # reported on a stronger footing than the other.
        "GapRunnableCl": diff_ci(lambda r: r.get("handshake_ok"), rows),
        "GapErrAsResultCl": diff_ci(
            check_pred("tools-call-unknown", "error-as-result"), responders),
        "PctVerOffered": f"{100*ver_counts.get('2025-06-18', 0)/len(responders):.0f}\\%" if responders else "-",
        "NVerOffered": f"{ver_counts.get('2025-06-18', 0):,}",
        "NVerDowngraded": f"{sum(v for k, v in ver_counts.items() if k and k < '2025-06-18'):,}",
        "NVerAhead": f"{sum(v for k, v in ver_counts.items() if k and k > '2025-06-18'):,}",
        "TopPublisherHandshake": top_pub_rate,
        "TopPublisherDepressionPP": top_pub_drop,
        "HandshakeDesignEffect": f"{design_effect([(publisher(r), r.get('handshake_ok')) for r in rows]):.1f}",
        "Nresponders": f"{n_resp:,}",
        "HandshakeRate": pctci(hs, n),
        "HandshakeCount": str(hs),
        "ErrAsResultRate": err_as_result,
        "ErrAsResultCount": f"{err_as_result_k:,}",
        "NotErrAsResultPct": f"{100*(n_resp-err_as_result_k)/n_resp:.1f}\\%" if n_resp else "-",
        "UnknownProtoErrCount": str(unk_pe_k),
        "UnknownWrongCodeCount": str(unk_wrong_k),
        "UnknownProseCount": str(unk_prose_k),
        "NoTypecheckRate": notypecheck,
        "MalformedDiesRate": malformed,
        # SDK attribution of the silent-execution population (Section 4.3).
        "SilentExecTS": str(silent_ts),
        "SilentExecPy": str(silent_py),
        "SilentExecTSvOne": str(silent_ts_v1),
        "SilentExecTSCaret": str(silent_ts_caret),
        "SilentExecTSExact": str(silent_ts_exact),
        # Attribution denominators and edge types (Section 4.2, Table 4).
        "SDKPopTS": f"{sdk_ts_pop:,}",
        "SDKPopPy": f"{sdk_py_pop:,}",
        "SDKIndirect": f"{edge_tot.get('indirect', 0):,}",
        "SDKDirect": f"{edge_tot.get('direct', 0):,}",
        "SDKUnattributed": f"{edge_tot.get('unattributed', 0):,}",
        "SDKNoSDK": f"{sdk_nosdk_pop:,}",
        "SDKNoSDKRate": (f"{100*sdk_nosdk_ear/sdk_nosdk_pop:.0f}\\%"
                         if sdk_nosdk_pop else "-"),
        # Publisher-clustering robustness check (Threats to Validity).
        "Npublishers": f"{len(pub_counts):,}",
        "NuniqPub": f"{len(uniq):,}",
        "TopPublisherN": f"{top_n:,}",
        "TopPublisherPct": f"{100*top_n/n:.1f}\\%",
        "TopTenPct": f"{100*top10_n/n:.1f}\\%",
        "HandshakeRatePub": pctci(uniq_hs, len(uniq)),
        "ErrAsResultRatePub": uniq_rate("tools-call-unknown", "error-as-result"),
        "NoTypecheckRatePub": uniq_rate("tools-call-invalid-args", "fail"),
        # Entry-point-corrected runnability (complete re-probe).
        "NEntrypointBlocked": f"{ep_n:,}",
        "EntrypointBlockedPct": f"{100*ep_n/pypi_n:.1f}\\%" if pypi_n else "-",
        "EntrypointRecovered": f"{ep_ok:,}",
        "EntrypointRecoveryRate": pctci(ep_ok, ep_n) if ep_n else "-",
        "HandshakeCountCorr": f"{hs_corr:,}",
        "HandshakeRateCorr": clustered(rows, corrected_ok),
        "HandshakeRateCorrBinom": pctci(hs_corr, n),
        "NpmRate": f"{npm_p:.1f}\\%",
        "NpmN": f"{npm_n:,}",
        "PypiN": f"{pypi_n:,}",
        "PypiRateRaw": f"{pypi_p:.1f}\\%",
        "PypiRateCorr": clustered([r for r in rows if r.get("registry_type") == "pypi"],
                                  corrected_ok) if pypi_n else "-",
        "GapRaw": f"{npm_p - pypi_p:.1f}",
        "GapCorr": f"{npm_p - pypi_p_corr:.1f}",
    }

    # Consequence decomposition: of the servers that fail to reject a wrong-typed
    # argument, how many actually executed the tool and returned ordinary-looking
    # output (the class a client cannot recover from), versus reporting the problem
    # in the result text without setting isError. Produced by analyze_consequences.py.
    cons_path = _cons_file
    if cons_path.exists():
        cons = json.loads(cons_path.read_text(encoding="utf-8"))
        silent = len(cons.get("silent-execution", []))
        # How much of that set rests on one poison value. The harness sends the
        # integer 12345 where a string is declared, and a runtime that coerces it
        # answers a well-formed question well. That is a weaker reading of the same
        # verdict, and its size belongs in the threats section rather than nowhere.
        int_poison = sum(1 for r in cons.get("silent-execution", [])
                         if isinstance(r, dict)
                         and 12345 in (r.get("sent") or {}).values())
        inband = len(cons.get("in-band-error", []))
        unclass = len(cons.get("unparsed", [])) + len(cons.get("no-transcript", []))
        tot = silent + inband + unclass + len(cons.get("empty-result", []))
        macros.update({
            "NAcceptInvalid": f"{tot:,}",
            "NSilentExec": f"{silent:,}",
            "NSilentIntPoison": f"{int_poison:,}",
            "SilentExecShare": f"{100*silent/tot:.0f}\\%" if tot else "-",
            "SilentExecRate": pctci(silent, n_resp),
            "NInBandError": f"{inband:,}",
            "InBandShare": f"{100*inband/tot:.0f}\\%" if tot else "-",
            "NUnclassifiable": f"{unclass:,}",
        })
    lines = ["% AUTO-GENERATED by driver/make_numbers.py -- do not edit by hand."]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in macros.items()]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({n} servers, {n_resp} responders)")
    for k, v in macros.items():
        print(f"  \\{k} = {v}")


if __name__ == "__main__":
    main()

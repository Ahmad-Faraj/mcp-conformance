# Submission Kit — arXiv + workshop

Prepared while the full census runs. Everything here is ready to use once the
census data lands and the paper is rebuilt.

---

## 1. AI-assistance disclosure (REQUIRED — goes in the paper)

Place this as a subsection of the Acknowledgments, or as a standalone "Disclosure"
note before the references. arXiv policy: AI tools may **not** be listed as authors,
and the human author bears full responsibility for all content; disclosure of
substantial AI use is expected.

> **Use of AI assistance.** This research made substantial use of an AI assistant
> (Anthropic's Claude) throughout the pipeline: literature search and synthesis,
> experimental design, implementation of the measurement harness (`mcpprobe`) and
> the analysis code, orchestration and monitoring of the measurement campaign,
> statistical analysis, figure generation, and drafting of this manuscript. The
> author defined the research goal, reviewed and approved the design and
> interpretations, checked the reported findings against the released raw data and
> code, and takes full responsibility for the content and claims herein. No AI
> system is an author. To make the work independently verifiable rather than
> reliant on any such attestation, the complete harness, raw JSON-RPC transcripts,
> dataset, and analysis scripts are released at [REPO URL], keyed to the pinned
> harness commit, so that every number in this paper can be regenerated from
> scratch.

**Honesty check — read this, Ahmed:** the sentences "reviewed and approved… checked
the reported findings… takes full responsibility" describe *you* after the two
review sessions we agreed on. Right now they are not yet true. Do the sessions
(≈2×2h: the core idea + method, then the results and how each number is derived)
**before** this statement ships. The reproducibility clause is the honest backstop
either way — it invites anyone to re-run and confirm — but the responsibility
clause must be earned, not asserted. If you would rather not do the sessions, we
soften the language to what is literally true (e.g., "the author directed the
research goal and released all artifacts for independent verification") and drop
the verification claim. I will not publish a disclosure that overstates your
involvement.

---

## 2. Acknowledgments (optional, separate from the disclosure)

> The author thanks the maintainers of the open-source MCP servers studied here,
> whose public work made this measurement possible, and the Model Context Protocol
> maintainers for the specification and the official conformance suite.

---

## 3. arXiv submission checklist

- **Primary category:** `cs.SE` (Software Engineering). Cross-list: `cs.CR`
  (relevant to the DoS/robustness findings) and optionally `cs.DC`.
- **Endorsement:** a first-time submitter to `cs.SE` may need an endorsement.
  Check your account at submission time; if prompted, request endorsement from a
  colleague/advisor already publishing in cs.SE, or from anyone who has submitted
  ≥3 papers to the category. **This is the one external dependency that can delay
  things — verify it early.**
- **License:** recommend CC BY 4.0 (maximally reusable, standard for open science).
  Alternatively arXiv's non-exclusive license if you want to keep it simpler.
- **Format:** the paper builds with `pdflatex` + `bibtex` (no exotic packages).
  arXiv compiles LaTeX source; upload `main.tex`, `sections/`, `tables/`,
  `figures/*.pdf`, `numbers.tex`, `refs.bib`. Do a clean local build first.
- **Metadata:** title, abstract (already written), author, and the AI-disclosure
  should also be reflected in the abstract-page comments field.
- **Artifact link:** the repo/dataset URL must be live before submission (the paper
  references it). Push the `mcp-conformance` repo to GitHub, tagged `harness-v1.0`,
  with a README and the responsible-disclosure-filtered dataset.

---

## 4. Workshop targeting (for the peer-reviewed venue, beyond the preprint)

Candidates that fit an execution-based measurement + conformance study:
- **MSR** (Mining Software Repositories) — data/measurement papers; strong fit.
- **ICSE / FSE** co-located workshops on software engineering for AI / LLM-based
  systems.
- **DSN** workshops (dependability) — the crash/hang/DoS robustness angle fits.
- NeurIPS/ICLR **agent** or **infrastructure** workshops — if we lead with the
  agent-reliability framing.

Pick one after the census lands; each has its own deadline, page limit, and
anonymization requirement. arXiv preprint can go up first (most of these allow
non-archival preprints; confirm per venue).

---

## 5. Pre-submission gate (do not submit until all true)

- [ ] Paper rebuilt on full-census data; all "preliminary/sample" language removed.
- [ ] Responsible-disclosure approach decided and applied to the released dataset.
- [ ] Repo public, `harness-v1.0` tag pushed, README written, dataset uploaded.
- [ ] AI-disclosure accurate (review sessions done, or language softened to fit).
- [ ] Clean `pdflatex`+`bibtex` build, zero undefined refs, figures render.
- [ ] arXiv endorsement confirmed for cs.SE.
- [ ] Author has read the whole paper end to end.

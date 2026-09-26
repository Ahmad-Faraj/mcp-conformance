# Writing standard for papers

Applies to every paper, every section, every caption, table, README, dataset card and commit message. No section is exempt. Methods and Results were exempted once (REWRITE_WORKSHEET.md) and the patterns survived there.

Checker: `tools/prose_audit.py` (set `REPO` and the section list at the top). Human baseline: 7 pre-2023 MSR/ICSE/EMSE/USENIX papers in `tools/prose_baseline/`. First full audit: `audits/mcp-2026-09-16/prose-audit.md`.

[S] = a script enforces it. [H] = a person must read for it.

## 0. Order of work
1. [H] Consistency pass first. For each factual thread (who corrected what, what the harness records, what prior work did), grep every mention and make them agree. The MCP paper had 9 contradictions; style edits on top of false sentences waste time.
2. [H] Claim calibration. No "universal", "near-universal", "never", "none", "first", "no client can" without a number or citation that supports exactly that scope.
3. Then the style rules below.
4. Rerun the checker after every edit session and report the metrics next to the baseline.

## 1. Hard fails [S]
- No em dashes: `—`, `---`, spaced ` -- ` in prose, docs and commit messages. Verbatim third-party output is exempt.
- Banned words and phrases: delve, underscore, showcase, pivotal, intricate, meticulous, commendable, realm, tapestry, testament, landscape, leverage, load-bearing, genuine/genuinely, notably, crucially, importantly, remarkably, namely, "in other words", "the relevant question", "not a matter of", "This is not a", "which is why", "which means", "which is how", "What X is (that)", "a handful of", "at all", actually, precisely, merely, simply, surface as a verb, "the one that matters", "moving target", "blast radius", "de-facto".
- Performative candor: "we are explicit", "we state ... explicitly", "we report what we found", "rather than silently", "we agree", "we adopt their", "honest/honestly". State the fact and its consequence.
- Signpost sentences: "Two/Three X matter", "We draw two conclusions", "show what this means", "The finding is that", "The correct reading is", "The result bears on".
- Question titles, second-person titles, headings phrased as claims or slogans ("The SDK is the unit of change", "X is not Y").
- Any digit or percentage in prose that is not a generated macro, unless the sentence carries `\cite` or it is a version, date, section or RQ number. Spelled-out derived quantities count as numbers: "two in five", "a fifth", "nine in ten", "seventeen thousand".
- Mixed spelling. IEEE venues use US spelling (behavior, organize, judgment).

## 2. Budgets per 1,000 words [S]
Baseline values in brackets are the pooled human papers.

| Pattern | Cap | Human baseline |
|---|---|---|
| "rather than" (never twice in one sentence, never sentence-initial) | 0.5 | 0.17 |
| ", not Y" / "X, not Y" | 0.25 | 0.11 |
| ", so" result clause | 0.5 | 0.05 |
| negations total | 8 | 6.9 |
| intensifiers (directly, explicitly, itself, alone, sharply, fully, exactly) | 1.5 | 1.4 |
| "A, B, and C" triads (max 2 in abstract, 2 in conclusion, one per sentence) | 5 | 4.4 |
| semicolons | 1.5 | 0.48 |
| \emph (never on "not", never on a rhyming contrast pair) | 3 | 3.3 |
| "That is / This is what" sentence openers | 0.5 | 0.35 |

## 3. Rhythm [S]
- Sentence length: mean 18 to 24 words, coefficient of variation 0.40 to 0.55.
- Sentences of 35+ words: at most 10%. No sentence over 45 words.
- Sentences of 8 words or fewer: at most 3 per 1,000 words, and never as a closing "verdict" line in more than one paragraph per section.
- Paragraph-length CV at least 0.55 in sections with 4+ paragraphs.

The old rule "follow a 40-word sentence with a 6-word one" is withdrawn. Applied mechanically it pushed both tails past every human baseline (CV 0.54 against 0.39 to 0.52; short verdict sentences 1.8x).

## 4. Repetition [S+H]
- No 6-gram of content words shared by two sections, except defined terms and check names.
- Each key claim is stated at most 4 times: abstract, introduction, one body section, conclusion. Tag with `%CLAIM:name` comments so the script can count them.
- No shared openers or kickers across sections ("Unlike the X question, this ...", "... and these servers do not.").
- The same concrete example appears at most twice.

## 5. Reading rules [H]
- Portability test: a sentence that would survive unchanged in another paper gets cut.
- Contrast only against a belief a reader holds. Otherwise state the positive claim.
- A paragraph's last sentence must add information, never restate its first.
- No motive assigned to other people or processes without a citation.
- Prefer the concrete noun: "a code-scanning tool answered CLEAN" over "servers may return misleading results".
- Do not soften or inflate. Use the term the evidence supports (divergence vs violation) and keep it identical everywhere.

## 6. What this cannot do
Trained detectors (Pangram, GPTZero, Originality) do not expose their features, and Originality defines heavily AI-edited human text as AI. These rules target what expert human readers notice (Russell et al. 2025, arXiv 2501.15654: frequent LLM users detected 299/300). Fixing surface signs without fixing substance only makes detection harder; accuracy and consistency come first.

## Sources
- Wikipedia, Signs of AI writing: https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing
- Liang et al. 2024, arXiv 2403.07183 and 2404.01268
- Kobak et al. 2025, Science Advances 11(27) eadt3813, arXiv 2406.07016
- Reinhart et al. 2025, PNAS, arXiv 2410.16107
- Russell, Karpinska, Iyyer 2025, arXiv 2501.15654
- Miletic and Falk 2026, arXiv 2605.19936
- GPTZero on perplexity and burstiness: https://gptzero.me/news/perplexity-and-burstiness-what-is-it/
- Pangram technical report, arXiv 2402.14873

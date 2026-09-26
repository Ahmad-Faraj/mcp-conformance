"""AI-prose pattern audit for LaTeX papers. Read-only on inputs.

usage: python audit.py  (paths configured below)
Outputs: metrics.md, flags.tsv, ngrams.txt, numbers.txt in the script directory.
"""
import re, os, sys, statistics as st, json, collections

HERE = os.path.dirname(os.path.abspath(__file__))
# Defaults to the repo this script sits in. Set PAPER_REPO to audit another one.
REPO = os.environ.get("PAPER_REPO") or os.path.dirname(HERE)
# Human comparison corpus. The papers are not redistributed here, so the baseline
# columns are skipped unless BASELINE_DIR points at a directory of .tex sources.
BASELINE_DIR = os.environ.get("BASELINE_DIR") or os.path.join(HERE, "prose_baseline")
P = os.path.join(REPO, "paper")

# ----------------------------------------------------------------------------
# LaTeX -> prose, preserving line numbers
# ----------------------------------------------------------------------------
KEEP_ARG = r"emph|textbf|textit|texttt|textsf|textsc|underline|mbox|text|url|footnote|caption"
DROP_ARG = r"cite|citep|citet|ref|label|autoref|cref|Cref|eqref|input|include|includegraphics|bibliography|bibliographystyle|vspace|hspace|addlinespace|centering|small|footnotesize|newcommand|renewcommand|usepackage|documentclass|hypersetup|IEEEauthorblockN|author|begin|end|setlength"
HEAD = r"section|subsection|subsubsection|paragraph|title"


def strip_comments(line):
    return re.sub(r"(?<!\\)%.*$", "", line)


def clean(s, macro_names=()):
    """Turn a LaTeX fragment into plain prose. Macros from numbers.tex -> NUM."""
    s = s.replace("~", " ").replace("\\ ", " ").replace("\\,", " ")
    s = re.sub(r"\\(%|&|_|#|\$)", lambda m: m.group(1), s)
    s = s.replace("``", '"').replace("''", '"')
    s = re.sub(r"\\-\{\}-", "--", s)
    # math -> NUM
    s = re.sub(r"\$[^$]*\$", " NUM ", s)
    s = re.sub(r"\\\((.*?)\\\)", " NUM ", s)
    for _ in range(3):
        s = re.sub(r"\\(?:%s)\s*(\[[^\]]*\])?\{[^{}]*\}" % DROP_ARG, " ", s)
        s = re.sub(r"\\(?:%s)\*?\{([^{}]*)\}" % KEEP_ARG, r"\1", s)
    for m in macro_names:
        s = re.sub(r"\\%s(\{\})?(?![A-Za-z])" % m, " NUM ", s)
    s = re.sub(r"\\(ie)\b(\{\})?", "i.e.", s)
    s = re.sub(r"\\(eg)\b(\{\})?", "e.g.", s)
    s = re.sub(r"\\item\b", " ", s)
    s = re.sub(r"\\[A-Za-z]+\*?(\{\})?", " ", s)  # any remaining command
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\b\d[\d,.]*\b%?", " NUM ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*|NUM")


def words(s):
    return WORD.findall(s)


ABBR = re.compile(r"(e\.g|i\.e|vs|et al|Fig|Sec|cf|approx|etc)\.$", re.I)


def split_sentences(par_text, par_line_offsets):
    """Split raw LaTeX paragraph into sentences with starting line numbers."""
    out = []
    start = 0
    for m in re.finditer(r"[.?!](?:''|\"|\)|\})*\s+(?=[A-Z\\(`])", par_text):
        end = m.end()
        chunk = par_text[start:m.start() + 1]
        if ABBR.search(chunk.strip()):
            continue
        # decimal like "88.4" won't match because next char must be space
        out.append((start, par_text[start:end].strip()))
        start = end
    if par_text[start:].strip():
        out.append((start, par_text[start:].strip()))
    res = []
    for off, txt in out:
        line = par_line_offsets[min(off, len(par_line_offsets) - 1)]
        res.append((line, txt))
    return res


def paragraphs_from_lines(lines, first_line=1, skip_envs=("figure", "figure*", "table", "table*", "tabular", "lstlisting", "equation")):
    """Yield (kind, start_line, raw_text, line_map). kind in prose/heading/caption/item."""
    buf, bmap = [], []
    in_env = 0
    out = []

    def flush():
        nonlocal buf, bmap
        if buf and "".join(buf).strip():
            out.append(("prose", bmap[0], "".join(buf), bmap))
        buf, bmap = [], []

    for i, raw in enumerate(lines):
        ln = first_line + i
        line = strip_comments(raw.rstrip("\n"))
        # captions inside skipped envs are collected separately
        if re.search(r"\\begin\{(%s)\}" % "|".join(re.escape(e) for e in skip_envs), line):
            flush()
            in_env += 1
        if in_env:
            cm = re.search(r"\\caption\{", line)
            if cm:
                # collect caption until braces balance
                j, text, depth, started = i, "", 0, False
                cmap = []
                while j < len(lines):
                    seg = strip_comments(lines[j].rstrip("\n"))
                    if j == i:
                        seg = seg[cm.end() - 1:]
                    for ch in seg + " ":
                        if ch == "{":
                            depth += 1
                            started = True
                            if depth == 1:
                                continue
                        if ch == "}":
                            depth -= 1
                            if depth == 0 and started:
                                break
                        text += ch
                        cmap.append(first_line + j)
                    if depth == 0 and started:
                        break
                    j += 1
                out.append(("caption", first_line + i, text, cmap))
            if re.search(r"\\end\{(%s)\}" % "|".join(re.escape(e) for e in skip_envs), line):
                in_env -= 1
            continue
        if not line.strip():
            flush()
            continue
        hm = re.match(r"\s*\\(%s)\*?\{(.*)\}\s*$" % HEAD, line)
        if hm:
            flush()
            out.append(("heading", ln, hm.group(2), [ln] * len(hm.group(2))))
            continue
        pm = re.match(r"\s*\\paragraph\{([^}]*)\}(.*)$", line)
        if pm:
            flush()
            out.append(("heading", ln, pm.group(1), [ln] * len(pm.group(1))))
            line = pm.group(2)
            if not line.strip():
                continue
        if re.match(r"\s*\\item\b", line):
            flush()
        if re.match(r"\s*\\(begin|end)\{(itemize|enumerate|abstract|document)\}", line):
            flush()
            continue
        if re.match(r"\s*\\(label|input|maketitle|bibliography|bibliographystyle)", line):
            continue
        t = line + " "
        buf.append(t)
        bmap.extend([ln] * len(t))
    flush()
    return out


# ----------------------------------------------------------------------------
# Pattern catalogue (regexes on cleaned sentence text). group -> {name: regex}
# ----------------------------------------------------------------------------
def wl(ws):
    return r"\b(?:%s)\b" % "|".join(ws)

KOBAK_STYLE = "accentuates acknowledges addresses adept advancement advocates affirming akin align amidst assessments attains attributed augmenting avenue bolster broader burgeoning capabilities capitalizing categorized combating compelling consolidates contributing conversely correlating crafted culminating customizing delineates delve delved delves delving demonstrating discern discerned discernible discerning displaying disrupts distinctive elevate elucidate elucidates elucidating embracing emphasize emphasizes employing empowers enabling encapsulates encompass encompasses endeavors enduring enhancements enhances ensuring equipping escalating evaluates evolving exacerbating examines exceeding excels exceptional exerting exhibiting exhibits expedite exploration explores facilitated facilitates featuring formidable fostering foundational furnish garnered garnering grappled groundbreaking groundwork harness harnesses harnessing heighten heightened hinder hinges hinting illuminates illuminating imbalances impacting impede imperative impressive incorporates influencing inherent initially innovative inquiries integrates integration interconnectedness interplay intricacies intricate intricately introduces invaluable investigates involves juxtaposed leverages leveraging maintaining merges methodologies meticulous meticulously multifaceted necessitate necessitates necessity notable noteworthy nuanced nuances offering optimizing orchestrating outlines overlook paving persist pinpoint pinpointed pinpointing pioneering pioneers pivotal poised pose posed poses posing predominantly preserving pressing promise pronounced propelling realm realms recognizing refine refines refining remarkable renowned revealing reveals revolutionize revolutionizing revolves scrutinize scrutinized scrutinizing seamless seamlessly seeks serves serving shaping shedding showcased showcases showcasing signifying solidify spanned spanning spurred stands stemming strategically streamline streamlined streamlines streamlining struggle substantiated substantiates surged surmount surpass surpassed surpasses surpassing swift swiftly thorough transformative typically ultimately uncharted uncovering underexplored underscore underscored underscores underscoring unexplored unlocking unparalleled unraveling unveil unveiled unveiling unveils uphold upholding urging utilizes varying versatility warranting yielding".split()
KOBAK_STYLE = [w for w in KOBAK_STYLE if w not in ("harness","harnesses","harnessing","capabilities","integration")]  # domain nouns in this field
KOBAK_COMMON = "across additionally comprehensive crucial enhancing exhibited insights notably particularly within potential findings".split()
LIANG = "commendable meticulous meticulously intricate innovative notable versatile realm pivotal showcasing".split()
WIKI_VOCAB = "additionally boasts bolstered crucial delve emphasizing enduring garner intricate intricacies interplay key landscape meticulous meticulously pivotal underscore underscores tapestry testament valuable vibrant enhance enhances fostering highlighting highlights showcasing".split()
PRACTITIONER_WORDS = "genuinely genuine load-bearing surface surfaces surfaced surfacing landscape robust robustness leverage leverages actually precisely exactly explicitly directly fundamentally inherently merely simply truly clearly unambiguously squarely sharply firmly the-one handful".split()

CATALOGUE = collections.OrderedDict([
    # lexical, studied
    ("lex.kobak_style291", wl(KOBAK_STYLE)),
    ("lex.kobak_common", wl(KOBAK_COMMON)),
    ("lex.liang_adj", wl(LIANG)),
    ("lex.wiki_vocab", wl(WIKI_VOCAB)),
    ("lex.wiki_copula_avoid", r"\b(?:serves as|stands as|functions as|acts as|marks a|represents a|boasts)\b"),
    ("lex.wiki_significance", r"\b(?:testament|pivotal role|crucial role|key role|broader|underscor\w*|highlight\w*|reflects? broader|setting the stage|evolving landscape|shift)\b"),
    # lexical, practitioner
    ("lex.genuinely", r"\bgenuine(?:ly)?\b"),
    ("lex.load_bearing", r"\bload-bearing\b"),
    ("lex.surface_verb_noun", r"\bsurface[sd]?\b|\bsurfacing\b"),
    ("lex.landscape", r"\blandscape\b"),
    ("lex.robust", r"\brobust(?:ness|ly)?\b"),
    ("lex.leverage", r"\bleverag\w*\b"),
    ("lex.actually", r"\bactually\b"),
    ("lex.intensifier", r"\b(?:precisely|exactly|explicitly|directly|fundamentally|inherently|truly|clearly|unambiguously|sharply|entirely|fully|far more|at all|itself|themselves|merely|simply|alone)\b"),
    ("lex.hedge", r"\b(?:roughly|nearly|near-universal|almost|largely|arguably|may|might|could|appears?|suggests?|likely|some|several|a few|a handful)\b"),
    ("lex.handful", r"\ba handful of\b"),
    # structural, studied/wiki
    ("str.rather_than", r"\brather than\b"),
    ("str.instead", r"\binstead\b"),
    ("str.not_X_but_Y", r"\bnot\b[^.;:]{1,80}?\bbut\b"),
    ("str.not_only", r"\bnot (?:only|just|merely)\b"),
    ("str.X_comma_not_Y", r",\s+not\s+(?:the|a|an|its|their|our|by|from|in|of|to|as|\w+s\b|\w+)(?!\s+(?:only|yet))"),
    ("str.not_a_matter_of", r"\bnot a (?:matter|question|formality|case) of\b|\bis not a (?:matter|formality|question)\b|\bThis is not\b"),
    ("str.rule_of_three", r"\b[\w\-]+(?: [\w\-]+){0,4}, [\w\-]+(?: [\w\-]+){0,4},? (?:and|or) [\w\-]+"),
    ("str.emph_triple_verb", r"\b\w+(?:ed|s), \w+(?:ed|s),? (?:and|or) \w+(?:ed|s)\b"),
    ("str.paired_abstraction", r"\b\w+(?:ity|ness|ance|ence|tion|ment|ism)\s+(?:and|or|versus|vs)\s+\w+(?:ity|ness|ance|ence|tion|ment|ism)\b"),
    # structural, practitioner
    ("str.that_is_what", r"\b(?:That|This|It|which) (?:is|was) (?:what|why|how|precisely|exactly|the reason|the right|the clearest|the one)\b|\bwhich is why\b|\bwhich means\b|\bThat is\b"),
    ("str.signpost", r"\b(?:the relevant question|the question|namely|in other words|put differently|crucially|importantly|notably|in particular|specifically|to be clear|in short|what matters|the point is|worth noting|it is worth|the key|what it does indicate|the finding is|the correct reading|the result bears)\b"),
    ("str.initial_adverb", r"^(?:Notably|Importantly|Crucially|Interestingly|Moreover|Furthermore|Additionally|Indeed|Ultimately|Overall|Thus|Therefore|Consequently|Specifically|Separately|Yet|Still|Instead|Unlike|Because|Where|Rather)\b"),
    ("str.first_second", r"\b(?:First|Second|Third|Finally)\b,"),
    ("str.therefore_so", r"\b(?:therefore|thus|hence|so that|so the|so a|so it|so we|so these|so our)\b"),
    ("str.colon_in_sentence", r":"),
    ("str.semicolon", r";"),
    ("str.both_and", r"\bboth\b[^.;]{1,60}\band\b"),
    ("str.the_one", r"\bthe one\b|\bthe only\b|\bthe single\b"),
    ("str.performative_candor", r"\b(?:we are explicit|we state|we record|we report what we found|rather than silently|we agree|we adopt|we decline|we do not claim|honest)\w*"),
    ("str.whereas_while", r"\b(?:whereas|while)\b"),
    ("str.does_not_merely", r"\bdoes not merely\b|\bnot merely\b"),
    ("str.question_title", r"\?"),
])

# categories considered AI-tell for the sentence-level flag list (subset; generic words like
# 'while', 'therefore', hedges are measured but do not flag a sentence on their own)
FLAGGING = [
    "lex.kobak_style291", "lex.liang_adj", "lex.wiki_vocab", "lex.wiki_copula_avoid", "lex.genuinely",
    "lex.load_bearing", "lex.surface_verb_noun", "lex.landscape", "lex.robust", "lex.leverage",
    "lex.actually", "lex.handful", "str.rather_than", "str.instead", "str.not_X_but_Y", "str.not_only",
    "str.X_comma_not_Y", "str.not_a_matter_of", "str.that_is_what", "str.signpost", "str.initial_adverb",
    "str.paired_abstraction", "str.performative_candor", "str.the_one", "str.does_not_merely",
]


def analyse_units(units, macro_names):
    """units: list of (file, kind, line, raw). Returns dict metrics + sentence records."""
    sents, pars = [], []
    raw_all = ""
    for f, kind, line, raw, lmap in units:
        raw_all += raw + "\n"
        if kind == "heading":
            continue
        ss = split_sentences(raw, lmap)
        pw = 0
        for ln, sraw in ss:
            c = clean(sraw, macro_names)
            w = words(c)
            if len(w) < 2:
                continue
            sents.append({"file": f, "line": ln, "kind": kind, "raw": sraw, "clean": c, "n": len(w)})
            pw += len(w)
        if pw and kind == "prose":
            pars.append(pw)
    return sents, pars, raw_all


def metrics(sents, pars, raw_all):
    L = [s["n"] for s in sents]
    N = sum(L)
    k = 1000.0 / N if N else 0
    m = {
        "words": N, "sentences": len(L),
        "sent_mean": st.mean(L) if L else 0, "sent_sd": st.pstdev(L) if L else 0,
    }
    m["sent_cv"] = m["sent_sd"] / m["sent_mean"] if m["sent_mean"] else 0
    m["pct_short_le10"] = 100 * sum(1 for x in L if x <= 10) / len(L) if L else 0
    m["pct_long_ge35"] = 100 * sum(1 for x in L if x >= 35) / len(L) if L else 0
    # adjacent-sentence length change (rhythm): mean |len_i - len_{i-1}| / mean
    d = [abs(L[i] - L[i - 1]) for i in range(1, len(L))]
    m["adj_delta_norm"] = (st.mean(d) / m["sent_mean"]) if d else 0
    m["par_n"] = len(pars)
    m["par_mean"] = st.mean(pars) if pars else 0
    m["par_cv"] = (st.pstdev(pars) / st.mean(pars)) if len(pars) > 1 else 0
    prose = "\n".join(s["raw"] for s in sents)
    m["emdash_per_k"] = k * (len(re.findall(r"---|\u2014", prose)) + len(re.findall(r"\s--\s", prose)))
    m["colon_per_k"] = k * sum(s["clean"].count(":") for s in sents)
    m["semicolon_per_k"] = k * sum(s["clean"].count(";") for s in sents)
    m["emph_per_k"] = k * len(re.findall(r"\\(?:emph|textit)\{", prose))
    m["textbf_per_k"] = k * len(re.findall(r"\\textbf\{", prose))
    for name, rx in CATALOGUE.items():
        flags = re.I if name not in ("str.initial_adverb", "str.first_second") else 0
        c = sum(len(re.findall(rx, s["clean"], flags)) for s in sents)
        m[name] = k * c
    # type-token ratio on first 2000 words (MATTR-ish)
    toks = [w.lower() for s in sents for w in words(s["clean"]) if w != "NUM"]
    win = 500
    if len(toks) >= win:
        ttrs = [len(set(toks[i:i + win])) / win for i in range(0, len(toks) - win + 1, 100)]
        m["mattr500"] = st.mean(ttrs)
    else:
        m["mattr500"] = len(set(toks)) / max(1, len(toks))
    return m


def load_macros():
    names = re.findall(r"\\newcommand\{\\(\w+)\}", open(os.path.join(P, "numbers.tex"), encoding="utf8").read())
    return names + ["ArtifactURL"]


def paper_units():
    macros = load_macros()
    units = collections.OrderedDict()
    main = open(os.path.join(P, "main.tex"), encoding="utf8").read().split("\n")
    # title
    tl = [(i + 1, l) for i, l in enumerate(main) if l.startswith("\\title") or (i > 0 and main[i - 1].startswith("\\title"))]
    a0 = next(i for i, l in enumerate(main) if "\\begin{abstract}" in l)
    a1 = next(i for i, l in enumerate(main) if "\\end{abstract}" in l)
    units["abstract"] = [("paper/main.tex",) + p[:2] + (p[2], p[3]) for p in paragraphs_from_lines(main[a0 + 1:a1], a0 + 2)]
    d0 = next(i for i, l in enumerate(main) if "Data and code availability" in l)
    d1 = next(i for i, l in enumerate(main) if "bibliographystyle" in l)
    units["main-backmatter"] = [("paper/main.tex",) + p[:2] + (p[2], p[3]) for p in paragraphs_from_lines(main[d0:d1], d0 + 1)]
    for sec in ["intro", "related", "method", "results", "discussion", "threats", "ethics", "conclusion"]:
        fn = os.path.join(P, "sections", sec + ".tex")
        lines = open(fn, encoding="utf8").read().split("\n")
        units[sec] = [("paper/sections/%s.tex" % sec,) + p[:2] + (p[2], p[3]) for p in paragraphs_from_lines(lines)]
    caps = []
    for t in ["consequences", "sdk", "startup", "verdicts"]:
        fn = os.path.join(P, "tables", t + ".tex")
        lines = open(fn, encoding="utf8").read().split("\n")
        caps += [("paper/tables/%s.tex" % t,) + p[:2] + (p[2], p[3]) for p in paragraphs_from_lines(lines) if p[0] == "caption"]
    units["table-captions"] = caps
    return units, macros


def baseline_units(path):
    txt = open(path, encoding="utf8", errors="replace").read()
    lines = txt.split("\n")
    b = next(i for i, l in enumerate(lines) if "\\begin{abstract}" in l)
    e = len(lines)
    for i, l in enumerate(lines):
        if i > b and re.match(r"\s*\\(bibliography\{|bibliographystyle|appendix|end\{document\}|begin\{thebibliography\})", l):
            e = i
            break
    ps = paragraphs_from_lines(lines[b:e], b + 1)
    # abstract+intro subset: up to the second \section
    secs = [i for i, p in enumerate(ps) if p[0] == "heading"]
    return [(path,) + p[:2] + (p[2], p[3]) for p in ps], ps


if __name__ == "__main__":
    units, macros = paper_units()
    allsents, allpars, allraw = [], [], ""
    table = collections.OrderedDict()
    for sec, us in units.items():
        s, p, r = analyse_units(us, macros)
        table[sec] = metrics(s, p, r)
        allsents += s; allpars += p; allraw += r
    table["PAPER (all)"] = metrics(allsents, allpars, allraw)
    body = [s for s in allsents if s["kind"] != "caption"]
    # abstract + intro subset for like-for-like with baseline A+I
    ai = [s for s in allsents if s["file"] == "paper/main.tex" and s["line"] < 70 or s["file"].endswith("intro.tex")]
    table["PAPER abstract+intro"] = metrics(ai, [], "")

    BL = BASELINE_DIR
    bfiles = {
        "BL Gistable ICSE18": os.path.join(BL, "1808.04919", "COMBINED.tex"),
        "BL MicroPkgs MSR18": os.path.join(BL, "1709.04638", "COMBINED.tex"),
        "BL git2net MSR19": os.path.join(BL, "1903.10180", "COMBINED.tex"),
        "BL npmSmallWorld USENIX19": os.path.join(BL, "1902.09217", "COMBINED.tex"),
        "BL ResearchCode SciData22": os.path.join(BL, "2103.12793", "COMBINED.tex"),
        "BL DepSmells TSE21": os.path.join(BL, "2010.14573", "COMBINED.tex"),
        "BL DepNetEvo EMSE19": os.path.join(BL, "1710.04936", "COMBINED.tex"),
    }
    blall = []
    for name, fp in bfiles.items():
        if not os.path.exists(fp):
            continue  # baseline corpus absent; paper columns still computed
        us, ps = baseline_units(fp)
        s, p, r = analyse_units(us, [])
        table[name] = metrics(s, p, r)
        blall.append((s, p))
        # abstract+intro: sentences before the 2nd heading line
        heads = [u[2] for u in us if u[1] == "heading"]
        cut = heads[1] if len(heads) > 1 else 10 ** 9
        table[name + " A+I"] = metrics([x for x in s if x["line"] < cut], [], "")
    table["BASELINE pooled"] = metrics([x for s, p in blall for x in s], [x for s, p in blall for x in p], "")

    keys = list(next(iter(table.values())).keys())
    with open(os.path.join(HERE, "metrics.tsv"), "w", encoding="utf8") as fh:
        fh.write("metric\t" + "\t".join(table.keys()) + "\n")
        for k in keys:
            fh.write(k + "\t" + "\t".join("%.2f" % table[t][k] for t in table) + "\n")
    json.dump(table, open(os.path.join(HERE, "metrics.json"), "w"), indent=1)

    # sentence flags
    with open(os.path.join(HERE, "flags.tsv"), "w", encoding="utf8") as fh:
        for s in allsents:
            hits = []
            for name in FLAGGING:
                flags = re.I if name not in ("str.initial_adverb",) else 0
                ms = re.findall(CATALOGUE[name], s["clean"], flags)
                if ms:
                    hits.append("%s[%s]" % (name, "|".join(sorted(set(m if isinstance(m, str) else m[0] for m in ms)))[:60]))
            if s["n"] >= 45:
                hits.append("len>=45(%d)" % s["n"])
            if hits:
                fh.write("%s:%d\t%d\t%s\t%s\n" % (s["file"], s["line"], s["n"], "; ".join(hits), s["clean"]))
    # all sentences dump
    with open(os.path.join(HERE, "sentences.tsv"), "w", encoding="utf8") as fh:
        for s in allsents:
            fh.write("%s:%d\t%d\t%s\n" % (s["file"], s["line"], s["n"], s["clean"]))

    # shared n-grams across different files (repeated framings)
    STOP = set("the a an of to in and or on for is are that this it its we our with by as at be from which not their they these those was were has have".split())
    grams = collections.defaultdict(list)
    for s in allsents:
        w = [x.lower() for x in words(s["clean"])]
        seen = set()
        for n in (4, 5, 6):
            for i in range(len(w) - n + 1):
                g = tuple(w[i:i + n])
                if sum(1 for x in g if x not in STOP and x != "num") < 2 or g in seen:
                    continue
                seen.add(g)
                grams[g].append("%s:%d" % (s["file"].replace("paper/", ""), s["line"]))
    with open(os.path.join(HERE, "ngrams.txt"), "w", encoding="utf8") as fh:
        rows = [(g, locs) for g, locs in grams.items() if len(locs) >= 3 or len(set(l.split(":")[0] for l in locs)) >= 2]
        rows.sort(key=lambda r: (-len(r[0]), -len(r[1])))
        for g, locs in rows:
            fh.write("%d\t%s\t%s\n" % (len(locs), " ".join(g), ", ".join(locs)))

    # hard-coded numbers in authored prose
    with open(os.path.join(HERE, "numbers.txt"), "w", encoding="utf8") as fh:
        for s in allsents:
            raw = re.sub(r"\\(?:ref|label|cite|input|includegraphics)\{[^}]*\}", "", s["raw"])
            raw = re.sub(r"\\texttt\{[^}]*\}", "", raw)
            nums = re.findall(r"(?<![\w.-])\d[\d,.]*\\?%?|\\\(\d[^)]*\\\)|\$[^$]*\d[^$]*\$", raw)
            nums = [n for n in nums if not re.fullmatch(r"(RQ)?\d", n)]
            if nums:
                fh.write("%s:%d\t%s\t%s\n" % (s["file"], s["line"], " | ".join(nums), s["clean"][:160]))
    print(open(os.path.join(HERE, "metrics.tsv"), encoding="utf8").read())

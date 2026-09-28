"""Claim-evidence map: which computed number or verified source backs each sentence.

The paper's LaTeX is split into sentences. A sentence is a claim when it
states a number (found with the number gate's own ``numeric_tokens``) or cites
a source. Each number is matched against the allowed-numbers registry with the
gate's tolerance and traced to the variant, metric, statistic, and metrics file
it came from; each citation is traced to the verified bibliography record and
to the evidence cards (verbatim abstract quotes) collected for it.

Status of a claim:

* ``unverified`` -- a number matches no registered value, or a cited key is
  not in the verified bibliography;
* ``weak`` -- everything resolves, but a cited paper has no evidence card, so
  the support is not evidenced at quote level;
* ``verified`` -- every number and citation resolves to evidence.

Everything here is deterministic; no model is involved.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tyche.analysis.registry import NumberEntry, NumberRegistry
from tyche.gates.checks import numeric_tokens
from tyche.textutil import sanitize_untrusted
from tyche.trace.lineage import latest_record, load_json, read_provenance

# Reading order of the main text; ``<name>_floats`` sorts right before ``<name>`` (as main.tex inputs it).
SECTION_ORDER = ("abstract", "introduction", "related_work", "method", "experiments", "analysis", "conclusion")
# Statements Tyche's own code generates (not model-written claims); the run-level map skips them.
GENERATED_SECTIONS = ("ai_statement", "reproducibility")

_FLOAT_ENVS = ("table", "table*", "figure", "figure*", "wraptable", "wrapfigure", "algorithm", "algorithm*")
_DROPPED_ENVS = (
    "tabular", "tabular*", "tabularx", "tabulary", "longtable", "verbatim", "verbatim*", "lstlisting", "algorithmic",
)
_MATH_ENVS = (
    "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "eqnarray",
    "eqnarray*", "flalign", "flalign*", "alignat", "alignat*", "displaymath", "math",
)
_HEADINGS = ("section", "subsection", "subsubsection", "paragraph", "subparagraph")
_ABBREVIATIONS = frozenset(
    {
        "e.g", "i.e", "al", "etc", "fig", "figs", "sec", "secs", "eq", "eqs", "vs", "cf", "tab", "no", "nos",
        "approx", "resp", "ref", "refs", "app", "alg", "thm", "def", "lem", "prop", "ch", "pp", "vol", "viz",
        "w.r.t", "a.k.a", "wrt", "esp", "incl", "ca", "dr", "mr", "mrs", "ms", "prof", "jr", "st",
    }
)

_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)
_BEGIN_END = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")
_CONTROL = re.compile(r"\\(?:[A-Za-z@]+\*?|.)", re.S)
_OPTIONAL_ARG = re.compile(r"\s*\[[^\]]*\]")
_PARBREAK = re.compile(r"\n[ \t]*\n")
_CAPTION = re.compile(r"\\caption\*?\s*(?:\[[^\]]*\])?\s*(?=\{)")
# natbib citation commands with up to two optional arguments; a superset of the citation gate's pattern.
_CITE = re.compile(r"\\[Cc]ite(?:t|p|alp|alt|author|year|yearpar|num)?\*?((?:\s*\[[^\]]*\]){0,2})\s*\{([^}]*)\}")
_REF = re.compile(r"\\(?:ref|eqref|cref|Cref|autoref|pageref|nameref)\*?\{([^}]*)\}")
_URL = re.compile(r"\\url\{([^}]*)\}")
_FOOTNOTE = re.compile(r"\\footnote\{([^{}]*)\}")

_GREEK = dict(
    zip(
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau upsilon phi "
        "chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega varepsilon vartheta varphi "
        "varrho varsigma varpi".split(),
        "αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΥΦΨΩεθφρςπ",
    )
)
_SYMBOLS = {
    **_GREEK,
    "times": "×", "pm": "±", "mp": "∓", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "sim": "~", "simeq": "≃", "cdot": "·", "to": "→", "rightarrow": "→", "leftarrow": "←",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔", "infty": "∞", "in": "∈", "notin": "∉",
    "sum": "Σ", "prod": "Π", "partial": "∂", "uparrow": "↑", "downarrow": "↓", "ldots": "…", "dots": "…",
    "cdots": "…", "circ": "°", "ll": "≪", "gg": "≫", "propto": "∝", "forall": "∀", "exists": "∃", "cup": "∪",
    "cap": "∩", "subset": "⊂", "subseteq": "⊆", "mid": "|", "vert": "|", "lvert": "|", "rvert": "|",
    "langle": "⟨", "rangle": "⟩", "ell": "ℓ", "top": "⊤", "star": "*", "ast": "*", "prime": "'",
    "textasciitilde": "~", "textbackslash": "\\", "textendash": "–", "textemdash": "—", "textdegree": "°",
    "textless": "<", "textgreater": ">", "textbar": "|", "dag": "†", "ddag": "‡", "checkmark": "✓",
    "LaTeX": "LaTeX", "TeX": "TeX", "S": "§", "lbrace": "\x01", "rbrace": "\x02", "backslash": "\\",
}
_OPERATORS = frozenset(
    "log exp max min arg argmax argmin sin cos tan lim sup inf det Pr dim ker deg".split()
)
_SPACES = frozenset("quad qquad newline linebreak hfill enspace thinspace medskip smallskip bigskip".split())
# Commands whose brace arguments are layout, identifiers, or paths: dropped with the command.
_DROP_ARGS = {
    "label": 1, "includegraphics": 1, "vspace": 1, "hspace": 1, "input": 1, "include": 1, "begin": 1, "end": 1,
    "setlength": 2, "addtolength": 2, "textcolor": 1, "color": 1, "colorbox": 1, "resizebox": 2, "scalebox": 1,
    "bibliography": 1, "bibliographystyle": 1, "phantom": 1, "hphantom": 1, "vphantom": 1, "href": 1,
    "rule": 2, "raisebox": 1, "fontsize": 2, "nocite": 1,
}
_CONTROL_SYMBOLS = {
    "%": "%", "&": "&", "_": "_", "#": "#", "$": "$", "{": "\x01", "}": "\x02", ",": " ", ";": " ", ":": " ",
    " ": " ", "\\": " ", "\n": " ", "[": " ", "]": " ",
}

_VARIANT_STATS = ("mean", "std", "ci_low", "ci_high", "ci_halfwidth", "n")
_COMPARISON_STATS = ("diff", "diff_ci_low", "diff_ci_high", "p_value", "relative_percent", "n")
_ANALYSIS_CONSTANTS = ("count.variants", "count.baselines", "count.metrics", "confidence.percent", "alpha", "p_threshold")


# -- LaTeX to sentences ------------------------------------------------------
def section_sort_key(name: str) -> tuple[int, str]:
    if name in SECTION_ORDER:
        return SECTION_ORDER.index(name) * 2 + 1, ""
    if name.endswith("_floats") and name[: -len("_floats")] in SECTION_ORDER:
        return SECTION_ORDER.index(name[: -len("_floats")]) * 2, ""
    return len(SECTION_ORDER) * 2, name


def _group(text: str, pos: int) -> tuple[int, int, int] | None:
    """(content start, content end, index after) of the balanced ``{...}`` group at ``pos``."""
    if pos >= len(text) or text[pos] != "{":
        return None
    depth = 0
    i = pos
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pos + 1, i, i + 1
        i += 1
    return pos + 1, len(text), len(text)


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\n":
        pos += 1
    return pos


def _env_end(text: str, env: str, pos: int) -> tuple[int, int]:
    """(start, end) of the ``\\end{env}`` closing an environment opened before ``pos``; nesting-aware."""
    depth = 1
    for match in _BEGIN_END.finditer(text, pos):
        if match.group(2).strip() != env:
            continue
        depth += 1 if match.group(1) == "begin" else -1
        if depth == 0:
            return match.start(), match.end()
    return len(text), len(text)


def _prepare(latex: str) -> str:
    """Drop comments and tabular material; replace each float by its caption paragraphs."""
    text = _COMMENT.sub("", latex or "")
    out: list[str] = []
    i = 0
    while True:
        match = _BEGIN_END.search(text, i)
        if match is None:
            out.append(text[i:])
            break
        env = match.group(2).strip()
        if match.group(1) != "begin" or (env not in _FLOAT_ENVS and env not in _DROPPED_ENVS):
            out.append(text[i : match.end()])
            i = match.end()
            continue
        end_start, end_end = _env_end(text, env, match.end())
        out.append(text[i : match.start()] + "\n\n")
        if env in _FLOAT_ENVS:
            body = text[match.end() : end_start]
            for caption in _CAPTION.finditer(body):
                group = _group(body, caption.end())
                if group is not None:
                    out.append(body[group[0] : group[1]].strip() + "\n\n")
        i = end_end
    return "".join(out)


def _next_char(text: str, pos: int) -> str:
    pos = _skip_ws(text, pos)
    return text[pos] if pos < len(text) else ""


def _ends_sentence(text: str, punct: int, after: int) -> bool:
    """Whether the punctuation at ``punct`` (followed by whitespace at ``after``) ends a sentence."""
    following = _next_char(text, after)
    if following.islower():
        return False
    if text[punct] != ".":
        return True
    k = punct
    while k > 0 and (text[k - 1].isalpha() or text[k - 1] == "."):
        k -= 1
    return text[k:punct].lower() not in _ABBREVIATIONS


def split_sentences(latex: str) -> list[str]:
    """LaTeX sentences of a section, in order.

    Comments and tabular bodies are dropped and floats contribute only their
    captions. Sentences end at ``.``/``?``/``!`` followed by whitespace, outside
    math and brace groups, unless the period ends a known abbreviation or the
    next word starts in lower case; paragraph breaks, list items, headings, and
    environment boundaries also end a sentence.
    """
    text = _prepare(latex)
    pieces: list[str] = []
    start = 0

    def cut(pos: int) -> None:
        nonlocal start
        piece = text[start:pos].strip()
        if piece:
            pieces.append(piece)
        start = pos

    n = len(text)
    i = 0
    depth = 0
    math: str | None = None  # "$", "$$", "\\(", "\\[", or a math environment name
    display_from = 0

    def close_display(content_end: int, after: int) -> None:
        # A display ending in a period ends the sentence it belongs to.
        if text[display_from:content_end].rstrip().endswith(".") and not _next_char(text, after).islower():
            cut(after)

    while i < n:
        char = text[i]
        if char == "\n":
            gap = _PARBREAK.match(text, i)
            if gap is not None:
                # Neither math nor a brace group may span a paragraph; recover from unbalanced input.
                cut(i)
                depth, math = 0, None
                i = gap.end()
                continue
        if math is not None:
            if char == "\\":
                control = _CONTROL.match(text, i)
                token = control.group(0) if control else "\\"
                if (math, token) in (("\\(", "\\)"), ("\\[", "\\]")):
                    math = None
                    i += 2
                    if token == "\\]":
                        close_display(i - 2, i)
                    continue
                env = _BEGIN_END.match(text, i)
                if env is not None and env.group(1) == "end" and env.group(2).strip() == math:
                    math = None
                    i = env.end()
                    close_display(env.start(), i)
                    continue
                i += len(token)
                continue
            if char == "$":
                if math == "$$" and text.startswith("$$", i):
                    math = None
                    i += 2
                    close_display(i - 2, i)
                    continue
                if math == "$":
                    math = None
            i += 1
            continue
        if char == "\\":
            control = _CONTROL.match(text, i)
            token = control.group(0) if control else "\\"
            name = token[1:].rstrip("*")
            if token in ("\\(", "\\["):
                math = token
                i += 2
                display_from = i
                continue
            if name in ("begin", "end"):
                env = _BEGIN_END.match(text, i)
                if env is not None:
                    if env.group(1) == "begin" and env.group(2).strip() in _MATH_ENVS:
                        math = env.group(2).strip()
                        display_from = env.end()
                    else:
                        cut(i)
                        start = env.end()
                    i = env.end()
                    continue
            if name in ("item", "par"):
                cut(i)
                j = i + len(token)
                if name == "item":
                    option = _OPTIONAL_ARG.match(text, j)
                    j = option.end() if option else j
                start = i = j
                continue
            if name in _HEADINGS:
                cut(i)
                j = i + len(token)
                option = _OPTIONAL_ARG.match(text, j)
                j = option.end() if option else j
                group = _group(text, _skip_ws(text, j))
                i = group[2] if group else j
                cut(i)
                continue
            i += len(token)
            continue
        if char == "$":
            if text.startswith("$$", i):
                math = "$$"
                i += 2
                display_from = i
            else:
                math = "$"
                i += 1
            continue
        if char == "{":
            depth += 1
            i += 1
            continue
        if char == "}":
            depth = max(0, depth - 1)
            i += 1
            if depth == 0 and (i >= n or text[i].isspace()):
                k = i - 2
                while k >= 0 and text[k].isspace():
                    k -= 1
                # A run-in heading or footnote ending in a period: \textbf{Setup.} We ...
                if k >= 0 and text[k] in ".?!" and _ends_sentence(text, k, i):
                    cut(i)
            continue
        if char in ".?!" and depth == 0:
            j = i + 1
            while j < n and text[j] in ")]'\"":
                j += 1
            if (j >= n or text[j].isspace()) and _ends_sentence(text, i, j):
                cut(j)
                i = j
                continue
        i += 1
    cut(n)
    return pieces


def _cite_keys(latex: str) -> list[str]:
    keys: list[str] = []
    for match in _CITE.finditer(latex):
        for key in match.group(2).split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def plain_text(latex: str) -> str:
    """Readable text of a LaTeX fragment: markup and math delimiters removed, citations as ``[k1; k2]``."""
    protected: list[str] = []

    def protect(value: str) -> str:
        protected.append(value)
        return f"\x00{len(protected) - 1}\x00"

    text = _CITE.sub(lambda m: protect("[" + "; ".join(k.strip() for k in m.group(2).split(",") if k.strip()) + "]"),
                     latex or "")
    text = _REF.sub(lambda m: protect(m.group(1)), text)
    text = _URL.sub(lambda m: protect(m.group(1)), text)
    text = _FOOTNOTE.sub(r" (\1)", text)
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "\\":
            control = _CONTROL.match(text, i)
            token = control.group(0) if control else "\\"
            i += len(token)
            if not token[1:2].isalpha() and token[1:2] != "@":
                out.append(_CONTROL_SYMBOLS.get(token[1:], ""))
                continue
            name = token[1:].rstrip("*")
            if name in _DROP_ARGS:
                option = _OPTIONAL_ARG.match(text, i)
                i = option.end() if option else i
                for _ in range(_DROP_ARGS[name]):
                    group = _group(text, _skip_ws(text, i))
                    if group is None:
                        break
                    i = group[2]
                out.append(" ")
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name])
            elif name in _OPERATORS:
                out.append(name)
            elif name in _SPACES:
                out.append(" ")
            else:
                option = _OPTIONAL_ARG.match(text, i)
                if option is not None and not text[i:option.end()].startswith((" ", "\n")):
                    i = option.end()
            continue
        if char in "{}$":
            i += 1
            continue
        out.append(" " if char == "~" else char)
        i += 1
    result = "".join(out).replace("``", '"').replace("''", '"').replace("---", "—").replace("--", "–")
    result = result.replace("\x01", "{").replace("\x02", "}")
    result = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], result)
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"\s+([.,;:!?])", r"\1", result)
    return re.sub(r"\(\s+", "(", result)


# -- numbers -------------------------------------------------------------------
def _comparison(row: dict[str, Any], metrics_files: dict[str, str]) -> dict[str, Any]:
    proposed, baseline = row.get("proposed"), row.get("baseline")
    return {
        "proposed": proposed,
        "baseline": baseline,
        "metric": row.get("metric"),
        "diff": row.get("diff"),
        "ci_low": row.get("ci_low"),
        "ci_high": row.get("ci_high"),
        "p_value": row.get("p_value"),
        "relative": row.get("relative"),
        "better": row.get("better"),
        "n": row.get("n"),
        "metrics_files": [metrics_files.get(str(proposed)), metrics_files.get(str(baseline))],
    }


def parse_label(
    label: str, analysis: dict[str, Any] | None = None, metrics_files: dict[str, str] | None = None
) -> dict[str, Any]:
    """Variant, metric, statistic, and comparison named by a registry label (see ``build_registry``).

    The saved analysis, when given, disambiguates names that contain dots; without it the
    label grammar alone is used.
    """
    analysis = analysis or {}
    files = metrics_files or {}
    out: dict[str, Any] = {"variant": None, "metric": None, "stat": None, "comparison": None, "source": "analysis"}
    if label.startswith("setup:"):
        out["source"] = "setup"
        return out
    if label in _ANALYSIS_CONSTANTS:
        out["stat"] = label
        return out
    for row in analysis.get("comparisons") or []:
        base = f"{row.get('proposed')}-vs-{row.get('baseline')}.{row.get('metric')}."
        if label.startswith(base) and label[len(base) :] in _COMPARISON_STATS:
            out.update(metric=row.get("metric"), stat=label[len(base) :], comparison=_comparison(row, files))
            return out
    variants = analysis.get("variants") or {}
    for variant in sorted(variants, key=len, reverse=True):
        if not label.startswith(variant + "."):
            continue
        rest = label[len(variant) + 1 :]
        names = set(analysis.get("metrics") or []) | set(variants.get(variant) or {})
        for metric in sorted(names, key=len, reverse=True):
            if rest == metric:
                out.update(variant=variant, metric=metric, stat="value")
                return out
            if rest.startswith(metric + ".") and rest[len(metric) + 1 :] in _VARIANT_STATS:
                out.update(variant=variant, metric=metric, stat=rest[len(metric) + 1 :])
                return out
    head, _, stat = label.rpartition(".")
    pair, _, metric = head.partition(".")
    if "-vs-" in pair and metric and stat in _COMPARISON_STATS:
        proposed, _, baseline = pair.partition("-vs-")
        row = {"proposed": proposed, "baseline": baseline, "metric": metric}
        out.update(metric=metric, stat=stat, comparison=_comparison(row, files))
        return out
    if stat in _VARIANT_STATS and "." in head:
        variant, _, metric = head.partition(".")
        out.update(variant=variant, metric=metric, stat=stat)
        return out
    variant, _, metric = label.partition(".")
    if metric:
        out.update(variant=variant, metric=metric, stat="value")
    return out


def _fits(token: str, percent: bool, entry: NumberEntry) -> tuple[bool, float] | None:
    """How ``token`` fits ``entry`` under the number gate's rule: (as a percentage of a fraction, rounding error).

    Mirrors ``NumberRegistry.match`` so the map and the gate agree on what is matched at all.
    """
    try:
        x = float(token)
    except ValueError:
        return None
    signed = token.strip().startswith("-")
    decimals = len(token.split(".", 1)[1]) if "." in token else 0
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    forms = [(entry.value, False)] if signed else [(entry.value, False), (abs(entry.value), False)]
    if percent or abs(entry.value) <= 1.0:
        forms += [(value * 100.0, True) for value, _ in list(forms)]
    fits = [(scaled, abs(value - x)) for value, scaled in forms if abs(value - x) <= tol]
    return min(fits, key=lambda f: (f[1], f[0])) if fits else None


def _label_words(parsed: dict[str, Any], label: str) -> set[str]:
    words: set[str] = set()
    for part in (parsed.get("variant"), parsed.get("metric"), (parsed.get("comparison") or {}).get("baseline")):
        if part:
            words |= {w for w in re.split(r"[^a-z0-9]+", str(part).lower()) if len(w) > 2}
    return words or {w for w in re.split(r"[^a-z0-9]+", label.lower()) if len(w) > 2}


def _number(
    token: str,
    percent: bool,
    registry: NumberRegistry,
    analysis: dict[str, Any] | None,
    metrics_files: dict[str, str],
    sentence_words: set[str],
) -> dict[str, Any]:
    """The registered value a number most plausibly states, with every other value it also fits.

    The gate accepts a token that rounds any registered value; the map has to say which one the
    sentence means. Candidates are ranked by scale (a token written without % does not state a
    fraction times 100, and one with % prefers a percentage), then by how many of the label's
    variant and metric words the sentence uses, then by rounding error. When the best candidates
    tie on scale and wording but hold different values, the attribution is marked ambiguous.
    """
    ranked = []
    for index, entry in enumerate(registry.entries):
        fit = _fits(token, percent, entry)
        if fit is None:
            continue
        scaled, error = fit
        parsed = parse_label(entry.label, analysis, metrics_files)
        as_percent = scaled or entry.label.endswith("percent")
        overlap = len(_label_words(parsed, entry.label) & sentence_words)
        ranked.append(((as_percent != percent, -overlap), error, index, entry, parsed))
    if not ranked:
        return {"text": token, "percent": percent, "match": None, "alternatives": [], "ambiguous": False}
    ranked.sort(key=lambda r: (r[0], r[1], r[2]))
    rank, _, _, entry, parsed = ranked[0]
    # A bare count that only fits a fraction times 100 ("96 events" vs accuracy 0.96) is a guess.
    ambiguous = rank[0] or any(r[0] == rank and abs(r[3].value - entry.value) > 1e-12 for r in ranked[1:])
    match = {
        "label": entry.label,
        "value": entry.value,
        "kind": entry.kind,
        "variant": parsed["variant"],
        "metric": parsed["metric"],
        "stat": parsed["stat"],
        "comparison": parsed["comparison"],
        "source": parsed["source"],
        "metrics_file": metrics_files.get(parsed["variant"]) if parsed["variant"] else None,
    }
    alternatives = list(dict.fromkeys(r[3].label for r in ranked[1:] if r[3].label != entry.label))
    return {"text": token, "percent": percent, "match": match, "alternatives": alternatives, "ambiguous": ambiguous}


# -- citations -------------------------------------------------------------------
def _paper_url(paper: dict[str, Any]) -> str | None:
    if paper.get("url"):
        return str(paper["url"])
    if paper.get("doi"):
        return f"https://doi.org/{paper['doi']}"
    if paper.get("arxiv_id"):
        return f"https://arxiv.org/abs/{paper['arxiv_id']}"
    return None


def _citation(key: str, papers: dict[str, dict[str, Any]], cards: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    paper = papers.get(key)
    found = list(cards.get(key, [])) if paper is not None else []
    return {
        "key": key,
        "known": paper is not None,
        "title": sanitize_untrusted(str(paper.get("title") or "")) if paper is not None else None,
        "year": paper.get("year") if paper is not None else None,
        "url": _paper_url(paper) if paper is not None else None,
        "cards": found,
        "carded": bool(found),
    }


# -- the map -----------------------------------------------------------------------
def build_claim_map(
    sections: dict[str, str],
    *,
    registry: NumberRegistry,
    papers: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    analysis: dict[str, Any] | None = None,
    metrics_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Claims of the given sections with the evidence behind each number and citation."""
    if not isinstance(registry, NumberRegistry):
        registry = NumberRegistry.from_list(list(registry or []))
    files = dict(metrics_files or {})
    by_key: dict[str, dict[str, Any]] = {}
    for paper in papers or []:
        key = str(paper.get("key") or "")
        if key and key not in by_key:
            by_key[key] = paper
    cards_by_key: dict[str, list[dict[str, str]]] = {}
    for card in cards or []:
        cards_by_key.setdefault(str(card.get("key") or ""), []).append(
            {"claim": sanitize_untrusted(str(card.get("claim") or "")), "quote": sanitize_untrusted(str(card.get("quote") or ""))}
        )
    stats = dict.fromkeys(
        ("sentences", "claims", "verified", "weak", "unverified", "numbers", "numbers_matched", "citations",
         "citations_known", "citations_carded"),
        0,
    )
    claims: list[dict[str, Any]] = []
    for name in sorted(sections, key=section_sort_key):
        for latex in split_sentences(sections[name] or ""):
            stats["sentences"] += 1
            tokens = numeric_tokens(latex)
            keys = _cite_keys(latex)
            if not tokens and not keys:
                continue
            words = {w for w in re.split(r"[^a-z0-9]+", plain_text(latex).lower()) if len(w) > 2}
            numbers = [_number(tok, pct, registry, analysis, files, words) for tok, pct, _ in tokens]
            citations = [_citation(key, by_key, cards_by_key) for key in keys]
            if any(n["match"] is None for n in numbers) or any(not c["known"] for c in citations):
                status = "unverified"
            elif any(not c["carded"] for c in citations):
                status = "weak"
            else:
                status = "verified"
            claims.append(
                {
                    "id": f"C{len(claims) + 1:03d}",
                    "section": name,
                    "sentence": plain_text(latex),
                    "latex": latex,
                    "kind": "mixed" if numbers and citations else ("numeric" if numbers else "citation"),
                    "status": status,
                    "numbers": numbers,
                    "citations": citations,
                }
            )
            stats[status] += 1
            stats["numbers"] += len(numbers)
            stats["numbers_matched"] += sum(1 for n in numbers if n["match"] is not None)
            stats["citations"] += len(citations)
            stats["citations_known"] += sum(1 for c in citations if c["known"])
            stats["citations_carded"] += sum(1 for c in citations if c["carded"])
    stats["claims"] = len(claims)
    return {"version": 1, "stats": stats, "claims": claims}


# -- locating a run's evidence ------------------------------------------------------
def _read_tree_sections(directory: Path) -> dict[str, str]:
    out = {}
    for file in sorted(directory.glob("*.tex")):
        try:
            out[file.stem] = file.read_text(encoding="utf-8")
        except OSError:
            continue
    return out


def _json_sections(run_dir: Path, record: dict[str, Any] | None) -> dict[str, str]:
    data = load_json(run_dir / str(record["path"])) if record else None
    sections = data.get("sections") if isinstance(data, dict) else None
    return {str(k): str(v or "") for k, v in sections.items()} if isinstance(sections, dict) else {}


def _paper_sections(run_dir: Path, rows: list[dict[str, Any]]) -> tuple[dict[str, str], str, Path | None] | None:
    """Final paper text: packaged source, else the latest compiled source, else the review's or writer's JSON."""
    packaged = run_dir / "package" / "paper_source"
    sections = _read_tree_sections(packaged / "sections")
    if any(text.strip() for text in sections.values()):
        return sections, "package/paper_source/sections", packaged / "refs.bib"
    source = latest_record(rows, "paper_source")
    if source is not None:
        tree = run_dir / str(source["path"])
        sections = _read_tree_sections(tree / "sections")
        if any(text.strip() for text in sections.values()):
            return sections, str(source["id"]), tree / "refs.bib"
    refs = latest_record(rows, "refs_bib")
    fallback_bib = run_dir / str(refs["path"]) if refs else None
    for name, stage in (("paper", "review"), ("draft", "write")):
        record = latest_record(rows, name)
        sections = _json_sections(run_dir, record)
        if record is not None and any(text.strip() for text in sections.values()):
            stage_bib = run_dir / stage / "refs.bib"
            return sections, str(record["id"]), stage_bib if stage_bib.is_file() else fallback_bib
    return None


_BIB_ENTRY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=^\s*@|\Z)", re.S | re.M)
_BIB_FIELD = re.compile(r"^\s*(\w+)\s*=\s*(.+?),?\s*$", re.M)


def _bib_papers(path: Path | None) -> list[dict[str, Any]]:
    """Minimal records of the compiled bibliography (it includes reviewer-admitted, verified entries)."""
    try:
        text = path.read_text(encoding="utf-8") if path is not None else ""
    except OSError:
        return []
    out = []
    for entry in _BIB_ENTRY.finditer(text):
        fields = {name.lower(): plain_text(value) for name, value in _BIB_FIELD.findall(entry.group(2))}
        year = re.search(r"\d{4}", fields.get("year", ""))
        out.append(
            {
                "key": entry.group(1),
                "title": fields.get("title", ""),
                "year": int(year.group(0)) if year else None,
                "doi": fields.get("doi", ""),
                "arxiv_id": fields.get("eprint", ""),
                "url": fields.get("url", ""),
            }
        )
    return out


def claim_map_for_run(run_dir: Path) -> dict[str, Any] | None:
    """The claim map of a run's final paper, or None if the run has no paper text yet."""
    run_dir = Path(run_dir)
    rows = read_provenance(run_dir)
    found = _paper_sections(run_dir, rows)
    if found is None:
        return None
    sections, sections_source, bib_path = found
    skipped = sorted(name for name in sections if name in GENERATED_SECTIONS)
    sections = {name: text for name, text in sections.items() if name not in GENERATED_SECTIONS}
    records = {name: latest_record(rows, name) for name in ("numbers", "source_manifest", "analysis", "experiment_results")}

    def load(name: str) -> Any:
        record = records[name]
        return load_json(run_dir / str(record["path"])) if record else None

    numbers = load("numbers")
    registry = NumberRegistry.from_list(numbers) if isinstance(numbers, list) else NumberRegistry()
    manifest = load("source_manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    analysis = load("analysis")
    metrics_files: dict[str, str] = {}
    if records["experiment_results"] is not None:
        results_dir = run_dir / str(records["experiment_results"]["path"])
        for file in sorted(results_dir.glob("*.metrics.json")):
            metrics_files[file.name[: -len(".metrics.json")]] = file.name
    papers = [p for p in manifest.get("papers") or [] if isinstance(p, dict)]
    listed = {str(p.get("key")) for p in papers}
    papers += [p for p in _bib_papers(bib_path) if p["key"] not in listed]
    result = build_claim_map(
        sections,
        registry=registry,
        papers=papers,
        cards=[c for c in manifest.get("evidence_cards") or [] if isinstance(c, dict)],
        analysis=analysis if isinstance(analysis, dict) else None,
        metrics_files=metrics_files,
    )
    bibliography = None
    if bib_path is not None and bib_path.is_file():
        try:
            bibliography = bib_path.relative_to(run_dir).as_posix()
        except ValueError:
            bibliography = bib_path.as_posix()
    result["sources"] = {
        "sections": sections_source,
        "bibliography": bibliography,
        **{name: (record["id"] if record else None) for name, record in records.items()},
    }
    result["skipped_sections"] = skipped
    return result

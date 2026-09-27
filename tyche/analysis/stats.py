"""Deterministic statistics over experiment metrics.

All numbers that may appear in the paper's results are computed here from the
metrics files, with a fixed random seed, so a rerun reproduces them exactly.
Confidence intervals use the percentile bootstrap; paired comparisons use a
sign-flip permutation test on per-item differences.
"""

from __future__ import annotations

import math
import re
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from tyche.experiments.bridge import numeric_metrics

_LOWER_TOKENS = {
    "token", "tokens", "cost", "costs", "latency", "time", "seconds", "ms", "error", "errors", "stale", "violation",
    "violations", "regression", "regressions", "loss", "perplexity", "ppl", "steps", "calls", "episodes", "wer", "cer",
}
_HIGHER_TOKENS = {
    "accuracy", "acc", "f1", "success", "precision", "recall", "score", "reward", "em", "bleu", "rouge", "auc",
    "hit", "hits", "win", "pass", "correct", "exact",
}
# pair_id names one item across variants (an "id" often also carries the variant name).
_ITEM_ID_KEYS = ("pair_id", "id", "item_id", "question_id", "qid", "task_id", "index")
_BOOL_ALIASES = {
    "accuracy": ("correct", "is_correct", "exact_match", "em"),
    "success": ("success", "succeeded", "solved", "correct"),
}


def lower_is_better(metric: str) -> bool:
    """Decide direction from whole name tokens; quality words (accuracy, f1, success) win over cost words."""
    tokens = set(re.split(r"[^a-z0-9]+", metric.lower())) - {""}
    if tokens & _HIGHER_TOKENS:
        return False
    return bool(tokens & _LOWER_TOKENS)


@dataclass
class MetricSummary:
    value: float | None
    n: int = 0
    mean: float | None = None
    std: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass
class Comparison:
    metric: str
    proposed: str
    baseline: str
    n: int
    diff: float
    ci_low: float
    ci_high: float
    p_value: float
    relative: float | None
    better: bool


@dataclass
class Analysis:
    proposed: str
    baselines: list[str]
    metrics: list[str]
    variants: dict[str, dict[str, MetricSummary]]
    comparisons: list[Comparison] = field(default_factory=list)
    lower_is_better: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    confidence: float = 0.95

    @property
    def confidence_percent(self) -> str:
        return f"{self.confidence * 100:g}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "proposed": self.proposed,
            "baselines": self.baselines,
            "metrics": self.metrics,
            "lower_is_better": self.lower_is_better,
            "variants": {v: {m: asdict(s) for m, s in ms.items()} for v, ms in self.variants.items()},
            "comparisons": [asdict(c) for c in self.comparisons],
            "notes": self.notes,
        }


# Per-item fields that split items into groups a metric may be reported over, e.g.
# stratum="change_count" for change_count_accuracy, or pass="matched_budget".
_GROUP_KEYS = (
    "stratum", "category", "question_set", "question_type", "qtype", "type", "set", "bucket", "slice", "split",
    "subset", "task_type", "pass", "setting", "phase",
)
# Group values that stand for the headline evaluation when a metric names no group.
_DEFAULT_GROUP_VALUES = {"main", "primary", "default", "test", "full", "eval", "evaluation"}
# Per-item fields that mark an item whose call failed; a metric may be reported over scored items only.
_FAILED_KEYS = ("error", "_fatal", "exception")
# Aggregation words a metric name adds to its per-item field (mean_prompt_tokens -> prompt_tokens).
_STAT_WORDS = {"mean", "avg", "average"}


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


def _words(text: str) -> set[str]:
    return {_stem(t) for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t}


def _group_keep(items: list[dict[str, Any]], metric: str) -> dict[str, set[str]]:
    """Group values a metric is reported over, per grouping field present on every item.

    Keep the values the metric's name mentions (change_count_accuracy -> stratum change_count);
    when it mentions none, keep the default values (pass main, phase eval) if the field has any.
    """
    name = "_" + _norm(metric) + "_"
    keep: dict[str, set[str]] = {}
    for key in _GROUP_KEYS:
        if not items or not all(isinstance(i, dict) and isinstance(i.get(key), str) for i in items):
            continue
        values = {i[key] for i in items}
        if len(values) < 2:
            continue
        named = {v for v in values if _norm(v) and "_" + _norm(v) + "_" in name}
        default = {v for v in values if _norm(v) in _DEFAULT_GROUP_VALUES}
        if named or default:
            keep[key] = named or default
    return keep


def _is_failed(item: dict[str, Any]) -> bool:
    if any(item.get(key) not in (None, False, "", [], {}) for key in _FAILED_KEYS):
        return True
    status = item.get("status")
    return isinstance(status, str) and status.lower() in {"failed", "error", "errored"}


def _value_keys(metric: str, drop: set[str]) -> list[str]:
    """Per-item fields that may hold ``metric``'s values, most literal first."""
    keys = [metric]
    for stem, aliases in _BOOL_ALIASES.items():
        if stem in metric.lower():
            keys.extend(aliases)
    parts = [p for p in _norm(metric).split("_") if p and p not in drop]
    for words in (parts, [p for p in parts if p not in _STAT_WORDS]):
        name = "_".join(words)
        keys.append(name)
        if name.endswith("_rate"):
            keys.append(name[: -len("_rate")])
    return list(dict.fromkeys(k for k in keys if k))


Rule = tuple[tuple[tuple[str, frozenset[str]], ...], str | None, bool]


def _candidate_rules(items: list[dict[str, Any]], metric: str, description: str, value_keys: list[str]) -> list[Rule]:
    """Item filters a metric may be computed over, most specific first: (group filters, flag, drop failed).

    A boolean flag is a candidate only when the metric's name or its planned description names it
    (stale_fact_rate "on changed-target queries" -> changed_target), never the value field itself.
    """
    keep = _group_keep(items, metric)
    groups = tuple(sorted((k, frozenset(v)) for k, v in keep.items()))
    words = _words(metric) | _words(description)
    flags = []
    if items:
        shared = set.intersection(*(set(i) for i in items))
        for key in sorted(shared - set(value_keys)):
            if all(isinstance(i[key], bool) for i in items) and len({i[key] for i in items}) == 2:
                if _words(key) and _words(key) <= words:
                    flags.append(key)
    rules: list[Rule] = []
    for group in ((groups, ()) if groups else ((),)):
        for flag in [*flags, None]:
            for drop_failed in (True, False):
                rules.append((group, flag, drop_failed))
    return list(dict.fromkeys(rules))


def _apply(items: list[dict[str, Any]], rule: Rule) -> list[dict[str, Any]]:
    groups, flag, drop_failed = rule
    return [
        i
        for i in items
        if all(i.get(k) in vals for k, vals in groups)
        and (flag is None or i.get(flag) is True)
        and not (drop_failed and _is_failed(i))
    ]


def _values_for(items: list[dict[str, Any]], key: str) -> list[float] | None:
    values = []
    for item in items:
        if not isinstance(item, dict) or key not in item:
            return None
        raw = item[key]
        if isinstance(raw, bool):
            values.append(1.0 if raw else 0.0)
        elif isinstance(raw, (int, float)) and math.isfinite(float(raw)):
            values.append(float(raw))
        else:
            return None
    return values or None


_EXACT = 1e-9


def _tolerance(target: float, rounded: bool) -> float:
    """How far a per-item mean may sit from a reported value and still reproduce it.

    Metrics files normally hold full-precision floats, so the first pass is exact up to float
    error. The second pass (``rounded``) accepts a value written with 2-6 decimals (0.9336) as
    rounded, within half a unit in its last place; short exact values (0.0, 1.0, 0.5) stay exact.
    """
    exact = _EXACT * max(1.0, abs(target))
    if not rounded:
        return exact
    text = repr(float(target))
    decimals = len(text.split(".")[1]) if "." in text and "e" not in text else 0
    return 0.5 * 10.0**-decimals + exact if 2 <= decimals <= 6 else exact


Found = tuple[list[dict[str, Any]], list[float]]
Choice = tuple[Rule, str]


@dataclass
class _Selection:
    """The per-item rows behind one metric.

    ``found`` holds each resolved variant's items and values and ``rules`` the (rule, field) that
    produced them. ``ambiguous`` names variants whose rows reproduce the reported value over
    several different item sets, so their n cannot be known. ``binary`` says every candidate
    value is 0 or 1 (a proportion), which the ceiling/floor notes need even when n is withheld.
    """

    found: dict[str, Found] = field(default_factory=dict)
    rules: dict[str, Choice] = field(default_factory=dict)
    ambiguous: set[str] = field(default_factory=set)
    binary: bool = False


def _signature(found: Found) -> tuple[tuple[int, ...], tuple[float, ...]]:
    items, values = found
    return tuple(id(i) for i in items), tuple(values)


def _is_binary(hits: list[Found]) -> bool:
    return bool(hits) and all(set(values) <= {0.0, 1.0} for _, values in hits)


def _select_items(
    items_by_variant: dict[str, list[dict[str, Any]]], metric: str, targets: dict[str, float], description: str = ""
) -> _Selection:
    """Per-item values behind ``metric`` for each variant.

    Values are accepted only when their mean reproduces the variant's reported value, so a
    stratum-level metric never inherits the all-items accuracy's interval or test. A rule
    (group filters, flag, failed-item handling, field) is chosen for all variants together,
    which keeps item sets comparable. When several rules reproduce every value but select
    different items (a floor or ceiling is reached with or without failed items), the item set
    is unknown and the variants are marked ambiguous rather than resolved by rule order.
    Only when no rule fits every variant does each variant get its own rule; ``rules`` records
    it so that only variants sharing a rule are paired.
    """
    with_items = {name: items for name, items in items_by_variant.items() if items}
    if not with_items:
        return _Selection()
    union = [i for items in with_items.values() for i in items]
    named = {
        _norm(v) for k, vals in _group_keep(union, metric).items() for v in vals if _norm(v) not in _DEFAULT_GROUP_VALUES
    }
    keys = _value_keys(metric, named)
    choices = [(rule, key) for rule in _candidate_rules(union, metric, description, keys) for key in keys]
    subsets: dict[tuple[str, Rule], list[dict[str, Any]]] = {}

    def hit(name: str, choice: Choice, rounded: bool) -> Found | None:
        rule, key = choice
        if (name, rule) not in subsets:
            subsets[name, rule] = _apply(with_items[name], rule)
        subset = subsets[name, rule]
        values = _values_for(subset, key)
        target = targets[name]
        if not values or target is None:
            return None
        return (subset, values) if abs(float(np.mean(values)) - target) <= _tolerance(target, rounded) else None

    for rounded in (False, True):
        joint = []
        for choice in choices:
            found = {name: hit(name, choice, rounded) for name in with_items}
            if all(found.values()):
                joint.append((choice, found))
        if joint:
            binary = _is_binary([f for _, found in joint for f in found.values()])  # type: ignore[misc]
            if len({tuple(_signature(f) for f in found.values()) for _, found in joint}) > 1:  # type: ignore[arg-type]
                return _Selection(ambiguous=set(with_items), binary=binary)
            choice, found = joint[0]
            return _Selection(found=found, rules={name: choice for name in found}, binary=binary)  # type: ignore[arg-type]
    out = _Selection()
    hits: list[Found] = []
    for name in with_items:
        for rounded in (False, True):
            own = [(choice, f) for choice in choices if (f := hit(name, choice, rounded))]
            if not own:
                continue
            hits.extend(f for _, f in own)
            if len({_signature(f) for _, f in own}) > 1:
                out.ambiguous.add(name)
            else:
                out.rules[name], out.found[name] = own[0]
            break
    out.binary = _is_binary(hits)
    return out


def _has_item_values(items: list[dict[str, Any]], metric: str) -> bool:
    return bool(items) and any(_values_for([i for i in items if not _is_failed(i)], key) for key in _value_keys(metric, set()))


_SEED_KEYS = ("seed", "run_seed", "trial_seed")
# Fields that identify an item's content; if they differ for one id across seeds, the
# id names different items per seed (generated data), not repeated trials of one item.
_CONTENT_KEYS = ("gold", "gold_answer", "answer", "target", "question", "question_text", "prompt", "entity", "attribute")


def _item_ids(items: list[dict[str, Any]]) -> list[str] | None:
    for key in _ITEM_ID_KEYS:
        if items and all(isinstance(i, dict) and key in i for i in items):
            ids = [str(i[key]) for i in items]
            seed_key = next((s for s in _SEED_KEYS if all(s in i for i in items)), None)
            if seed_key and len(set(ids)) < len(ids) and _ids_name_different_items(items, key, seed_key):
                return [f"{i[seed_key]}:{i[key]}" for i in items]
            return ids
    return None


def _ids_name_different_items(items: list[dict[str, Any]], key: str, seed_key: str) -> bool:
    content: dict[str, set[str]] = {}
    for item in items:
        signature = repr([item.get(k) for k in _CONTENT_KEYS if k in item])
        content.setdefault(str(item[key]), set()).add(signature)
    return any(len(signatures) > 1 for signatures in content.values())


def _per_id_means(ids: list[str], values: np.ndarray) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for key, value in zip(ids, values):
        groups.setdefault(key, []).append(float(value))
    return {key: float(np.mean(vals)) for key, vals in groups.items()}


def _rng(seed: int, *parts: str) -> np.random.Generator:
    """A generator for one quantity, so each interval and p-value depends only on its own data and the seed."""
    return np.random.default_rng([seed, zlib.crc32("\x1f".join(parts).encode())])


def bootstrap_ci(values: np.ndarray, rng: np.random.Generator, resamples: int, confidence: float) -> tuple[float, float]:
    if len(values) < 2:
        m = float(values.mean()) if len(values) else float("nan")
        return m, m
    idx = rng.integers(0, len(values), size=(resamples, len(values)))
    means = values[idx].mean(axis=1)
    alpha = (1 - confidence) / 2
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))


def sign_flip_p(diffs: np.ndarray, rng: np.random.Generator, resamples: int) -> float:
    if len(diffs) == 0 or np.allclose(diffs, 0):
        return 1.0
    observed = abs(diffs.mean())
    signs = rng.choice([-1.0, 1.0], size=(resamples, len(diffs)))
    null = np.abs((signs * diffs).mean(axis=1))
    # Add-one correction keeps the estimate valid (never exactly zero).
    return float((np.sum(null >= observed - 1e-12) + 1) / (resamples + 1))


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower())) - {""}


def pick_proposed(names: list[str], hint: str = "") -> str:
    """The proposed variant: 'proposed'/'ours' by name first, then a whole-token match with the method name."""
    for name in names:
        if name.lower() == "proposed":
            return name
    for name in names:
        if _tokens(name) & {"proposed", "ours"}:
            return name
    hint_tokens = _tokens(hint)
    if hint_tokens:
        matches = [n for n in names if _tokens(n) == hint_tokens]
        if matches:
            return matches[0]
    raise ValueError(
        "cannot tell which variant is the proposed method; name it 'proposed' (or include 'ours') in the metrics "
        f"file names. Variants: {', '.join(names)}"
    )


def _bound_notes(summaries: dict[str, dict[str, MetricSummary]], metrics: list[str], binary: dict[str, bool]) -> list[str]:
    """Flag proportion metrics where two or more variants sit at 0 or 1: the experiment cannot rank them."""
    notes = []
    for metric in metrics:
        values = {v: ms[metric].value for v, ms in summaries.items() if ms[metric].value is not None}
        if not binary.get(metric):
            continue
        for bound in (0.0, 1.0):
            at = sorted(v for v, x in values.items() if x == bound)
            if len(at) >= 2:
                notes.append(
                    f"{metric} is exactly {bound:g} for {', '.join(at)}: a ceiling/floor effect, so this experiment "
                    "cannot separate those variants on this metric"
                )
    return notes


# Words that end the name part of a planned metric's description ("Prompt tokens per query, ...").
_DESCRIPTION_BREAK = re.compile(r"[:;,(.]|\s(?:on|over|per|using|for|across|with|measured|computed|of)\s", re.I)


def map_planned_metrics(plan_metrics: list[str], reported: set[str]) -> dict[str, str]:
    """Map each planned metric to the reported metric that implements it: {planned text: metric name}.

    Plans may describe a metric in prose ("Exact-match accuracy on the latest value") while the
    metrics files use an identifier (exact_match_accuracy). A planned entry maps to the reported
    metric whose name words (minus mean/avg) all appear in the description's name part; the most
    specific such metric wins, ties map nothing, and each reported metric is claimed once.
    """
    out: dict[str, str] = {}
    claimed: set[str] = set()
    for text in plan_metrics:
        if text in reported:
            if text not in claimed:
                out[text] = text
                claimed.add(text)
            continue
        head = _words(_DESCRIPTION_BREAK.split(str(text), maxsplit=1)[0])
        scored = []
        for metric in reported - claimed:
            core = _words(metric) - _STAT_WORDS
            if core and core <= head:
                scored.append((len(core), metric))
        scored.sort(reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            out[text] = scored[0][1]
            claimed.add(scored[0][1])
    return out


def analyze(
    variants: dict[str, dict[str, Any]],
    *,
    plan_metrics: list[str],
    method_name: str = "",
    resamples: int = 2000,
    permutations: int = 5000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Analysis:
    if len(variants) < 2:
        raise ValueError("analysis needs at least two variants")
    names = sorted(variants)
    proposed = pick_proposed(names, method_name)
    names = [proposed] + [n for n in names if n != proposed]
    # Planned metrics are kept even when they look like settings (max_*, n_*); plans may name
    # them in prose, so resolve the prose against every numeric field before filtering.
    fields = set.intersection(
        *({k for k, v in variants[n].items() if isinstance(v, (int, float)) and not isinstance(v, bool)} for n in names)
    )
    keep = set(plan_metrics) | set(map_planned_metrics(plan_metrics, fields).values())
    numeric = {name: numeric_metrics(variants[name], keep=keep) for name in names}
    shared = set.intersection(*(set(m) for m in numeric.values()))
    planned = map_planned_metrics(plan_metrics, shared)
    described = {metric: text for text, metric in planned.items()}
    # Planned metrics first, then other metrics that differ between variants; metrics identical
    # for every variant (budgets, conformance flags, ...) carry no comparison and go last.
    first = list(dict.fromkeys(planned.values()))
    extras = sorted(shared - set(first))
    constant = [m for m in extras if len({round(numeric[n][m], 12) for n in names}) == 1]
    ordered = first + [m for m in extras if m not in constant] + constant
    notes = []
    missing = [m for m in plan_metrics if m not in planned]
    if missing:
        notes.append(f"planned metrics not reported by every variant: {', '.join(missing)}")
    if not ordered:
        raise ValueError("variants share no numeric metric; nothing can be compared")
    summaries: dict[str, dict[str, MetricSummary]] = {}
    per_item: dict[str, dict[str, np.ndarray]] = {}
    ids: dict[str, dict[str, list[str] | None]] = {}
    unmatched: set[str] = set()
    ambiguous: set[str] = set()
    rules: dict[str, dict[str, Any]] = {}
    binary: dict[str, bool] = {}
    items_by_variant = {}
    for name in names:
        items = variants[name].get("per_question") or []
        items = items if isinstance(items, list) else []
        items_by_variant[name] = [i for i in items if isinstance(i, dict)] if all(isinstance(i, dict) for i in items) else []
        summaries[name] = {}
        per_item[name] = {}
        ids[name] = {}
    for metric in ordered:
        targets = {name: numeric[name][metric] for name in names}
        selected = _select_items(items_by_variant, metric, targets, described.get(metric, ""))
        rules[metric] = selected.rules
        binary[metric] = selected.binary
        if selected.ambiguous:
            ambiguous.add(metric)
        for name in names:
            summary = MetricSummary(value=numeric[name][metric])
            found = selected.found.get(name)
            if found is None and name not in selected.ambiguous and _has_item_values(items_by_variant[name], metric):
                unmatched.add(metric)
            if found:
                used, values = found
                ids[name][metric] = _item_ids(used)
                arr = np.asarray(values, dtype=float)
                per_item[name][metric] = arr
                lo, hi = bootstrap_ci(arr, _rng(seed, "summary", metric, name), resamples, confidence)
                summary.n = len(arr)
                summary.mean = float(arr.mean())
                summary.std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
                summary.ci_low, summary.ci_high = lo, hi
            summaries[name][metric] = summary
    comparisons: list[Comparison] = []
    unpaired: set[str] = set()
    for baseline in names[1:]:
        for metric in ordered:
            a = per_item[proposed].get(metric)
            b = per_item[baseline].get(metric)
            if a is None or b is None:
                continue
            if rules[metric].get(proposed) != rules[metric].get(baseline):
                # The two values are computed over different item sets; pairing them would mislead.
                unpaired.add(metric)
                continue
            ia, ib = ids[proposed].get(metric), ids[baseline].get(metric)
            if ia and ib:
                # Repeated trials of the same item are averaged per item before pairing.
                mean_a = _per_id_means(ia, a)
                mean_b = _per_id_means(ib, b)
                common = [k for k in mean_a if k in mean_b]
                if len(common) < 2:
                    continue
                a_al = np.asarray([mean_a[k] for k in common])
                b_al = np.asarray([mean_b[k] for k in common])
            elif len(a) == len(b):
                a_al, b_al = a, b
            else:
                continue
            diffs = a_al - b_al
            lo, hi = bootstrap_ci(diffs, _rng(seed, "diff", metric, proposed, baseline), resamples, confidence)
            base_mean = float(b_al.mean())
            diff = float(diffs.mean())
            better = diff < 0 if lower_is_better(metric) else diff > 0
            comparisons.append(
                Comparison(
                    metric=metric,
                    proposed=proposed,
                    baseline=baseline,
                    n=len(diffs),
                    diff=diff,
                    ci_low=lo,
                    ci_high=hi,
                    p_value=sign_flip_p(diffs, _rng(seed, "sign", metric, proposed, baseline), permutations),
                    relative=(diff / abs(base_mean) * 100.0) if abs(base_mean) > 1e-12 else None,
                    better=better,
                )
            )
    if unmatched:
        notes.append(
            "per-item rows do not reproduce the reported value of "
            + ", ".join(sorted(unmatched))
            + "; those metrics are reported without intervals or paired tests"
        )
    if ambiguous:
        notes.append(
            "per-item rows reproduce the reported value of "
            + ", ".join(m for m in ordered if m in ambiguous)
            + " over several different item sets (for example with and without failed items); their n, intervals "
            "and paired tests are withheld"
        )
    if unpaired:
        notes.append(
            "variants report "
            + ", ".join(m for m in ordered if m in unpaired)
            + " over different item sets; those metrics are not compared pairwise"
        )
    if not comparisons:
        notes.append("no per-item data aligned across variants; paired tests were not computed")
    notes.extend(_bound_notes(summaries, ordered, binary))
    return Analysis(
        proposed=proposed,
        baselines=names[1:],
        metrics=ordered,
        variants=summaries,
        comparisons=comparisons,
        lower_is_better={m: lower_is_better(m) for m in ordered},
        notes=notes,
        confidence=confidence,
    )

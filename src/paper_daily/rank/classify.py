"""Split papers into principle / method / system / application / benchmark.

The point of this axis is the reading goal: papers that explain *why* something works
earn a place ahead of papers that report that something works. The signal is
deliberately shallow -- title and abstract keywords -- because it only has to sort a
ranked list, not be right about any single paper. Anything unmatched falls to
"method", the honest default for most conference output.
"""

from __future__ import annotations

import re

PRINCIPLE = (
    "we prove",
    "we show that",
    "theorem",
    "lemma",
    "provable",
    "provably",
    "convergence rate",
    "convergence of",
    "generalization bound",
    "generalisation bound",
    "sample complexity",
    "information-theoretic",
    "identifiability",
    "expressivity",
    "expressive power",
    "optimization landscape",
    "loss landscape",
    "implicit bias",
    "implicit regularization",
    "training dynamics",
    "learning dynamics",
    "neural tangent",
    "mean-field",
    "scaling law",
    "phase transition",
    "emergence of",
    "why do",
    "why does",
    "a theory of",
    "theoretical analysis",
    "on the role of",
    "rethinking",
    "revisiting",
    "what do",
    "what does",
    "how does",
    "an analysis of",
    "characterizing",
    "characterising",
    "inductive bias",
    "necessary and sufficient",
    "lower bound",
    "upper bound",
    "grokking",
    "double descent",
    "pac-bayes",
)

BENCHMARK = (
    "benchmark",
    "a dataset",
    "new dataset",
    "we release",
    "evaluation suite",
    "leaderboard",
    "testbed",
    "corpus of",
    "a large-scale dataset",
    "datasets and benchmarks",
    "evaluation framework",
    "a suite of",
)

SYSTEM = (
    "efficient inference",
    "inference engine",
    "serving",
    "distributed training",
    "memory-efficient",
    "kernel fusion",
    "compiler",
    "gpu kernel",
    "throughput",
    "latency",
    "quantization",
    "quantisation",
    "pipeline parallel",
    "tensor parallel",
    "training infrastructure",
)

APPLICATION = (
    "clinical",
    "medical imaging",
    "diagnosis",
    "patient",
    "radiology",
    "histopathology",
    "protein",
    "molecule",
    "molecular",
    "drug discovery",
    "genomics",
    "single-cell",
    "weather forecast",
    "climate",
    "remote sensing",
    "traffic forecasting",
    "recommendation system",
    "recommender",
    "financial",
    "stock",
    "e-commerce",
    "autonomous driving",
    "materials discovery",
    "astronomy",
)

_PRINCIPLE_RE = re.compile("|".join(re.escape(k) for k in PRINCIPLE))
_BENCHMARK_RE = re.compile("|".join(re.escape(k) for k in BENCHMARK))
_SYSTEM_RE = re.compile("|".join(re.escape(k) for k in SYSTEM))
_APPLICATION_RE = re.compile("|".join(re.escape(k) for k in APPLICATION))

# Titles that announce a resource rather than a finding. Checked before the keyword
# tally, because a benchmark paper's abstract is full of "we show that ..." result
# language and would otherwise land in the principle bucket -- MathVista ranked as
# a principle paper until this rule existed.
_TITLE_BENCHMARK_RE = re.compile(
    r"\bbenchmark|\bdataset\b|\bevaluating\b|\bevaluation\b|\btestbed\b"
    r"|\bleaderboard\b|\bcorpus\b|\bhow well do\b|\ba suite of\b"
)

# How much each type is worth when ranking. Principle papers are the reading goal;
# nothing is excluded outright, so a landmark benchmark can still win on other signals.
TYPE_WEIGHT = {
    "principle": 1.00,
    "method": 0.60,
    "system": 0.45,
    "application": 0.35,
    "benchmark": 0.20,
}


def classify(title: str, abstract: str | None, track: str | None = None) -> tuple[str, float]:
    """Return (type, confidence).

    Title hits count double in the tally: a paper that announces its theoretical
    intent in the title almost always delivers one.
    """
    if track and "datasets" in track.lower():
        return "benchmark", 1.0

    t = (title or "").lower()
    a = (abstract or "").lower()

    if _TITLE_BENCHMARK_RE.search(t):
        return "benchmark", 0.9

    scores = {
        "principle": 2 * len(_PRINCIPLE_RE.findall(t)) + len(_PRINCIPLE_RE.findall(a)),
        "benchmark": 2 * len(_BENCHMARK_RE.findall(t)) + len(_BENCHMARK_RE.findall(a)),
        "system": 2 * len(_SYSTEM_RE.findall(t)) + len(_SYSTEM_RE.findall(a)),
        "application": 2 * len(_APPLICATION_RE.findall(t)) + len(_APPLICATION_RE.findall(a)),
    }
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "method", 0.3
    total = sum(scores.values()) or 1
    return best, round(scores[best] / total, 3)

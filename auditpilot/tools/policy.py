"""Policy retrieval (the 'RAG' step): find the clause that supports or contradicts a payment pattern.

Retrieval is TF-IDF first (scikit-learn). The embedder sits behind a tiny interface (fit / score), so swapping in
embeddings later means replacing TfidfEmbedder only; nothing else changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .common import data_dir, result, safe_tool

CLAUSE_HEADING = re.compile(r"^##\s+(\d+\.\d+)\s+(.+?)\s*$", re.MULTILINE)
QUOTE_MAX_CHARS = 240


@dataclass(frozen=True)
class Clause:
    clause_id: str
    title: str
    text: str


def split_clauses(policy_text: str) -> list[Clause]:
    """Split policy.md into clauses at '## <number> <title>' headings."""
    matches = list(CLAUSE_HEADING.finditer(policy_text))
    clauses = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(policy_text)
        clauses.append(Clause(m.group(1), m.group(2), policy_text[m.end():end].strip()))
    return clauses


class TfidfEmbedder:
    """Swap point: replace with an embeddings-based class exposing the same fit() and score()."""

    def __init__(self) -> None:
        self._vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self._matrix = None

    def fit(self, documents: list[str]) -> "TfidfEmbedder":
        self._matrix = self._vec.fit_transform(documents)
        return self

    def score(self, query: str) -> list[float]:
        return list(cosine_similarity(self._vec.transform([query]), self._matrix)[0])


EmbedderFactory = TfidfEmbedder


@lru_cache(maxsize=4)
def _index(policy_text: str) -> tuple[list[Clause], TfidfEmbedder]:
    clauses = split_clauses(policy_text)
    return clauses, EmbedderFactory().fit([f"{c.title}. {c.text}" for c in clauses])


def short_quote(text: str, limit: int = QUOTE_MAX_CHARS) -> str:
    """The first sentence(s) of a clause, verbatim, up to `limit` characters."""
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if out and len(out) + 1 + len(sentence) > limit:
            break
        out = f"{out} {sentence}".strip()
    return out[:limit]


@safe_tool
def retrieve_policy(query: str, k: int = 3) -> dict:
    """Retrieve the k most relevant clauses of the finance policy (data/policy.md) for a question.

    Use this before raising any policy finding: the finding must cite the clause id and a short quote returned here.
    Example queries: "who approves a payment above Rs 50,000", "approving your own payment",
    "splitting a payment to stay under the limit", "vendor bank account same as employee", "Sunday payment".

    Returns {"test", "flagged_ids", "stats", "notes"}; stats.results is a list of {clause_id, title, quote, score}
    ordered best first. flagged_ids is always empty.
    """
    policy_path = data_dir() / "policy.md"
    if not policy_path.exists():
        return result("retrieve_policy", [], {"status": "FAILED", "reasons": ["policy.md not found"]},
                      "policy.md not found")
    clauses, embedder = _index(policy_path.read_text(encoding="utf-8"))
    k = max(1, min(int(k), len(clauses)))
    scores = embedder.score(query)
    order = sorted(range(len(clauses)), key=lambda i: (-scores[i], clauses[i].clause_id))[:k]
    results = [{"clause_id": clauses[i].clause_id, "title": clauses[i].title,
                "quote": short_quote(clauses[i].text), "score": round(float(scores[i]), 4)} for i in order]
    return result("retrieve_policy", [], {"query": query, "k": k, "results": results},
                  f"Top clause for the query: {results[0]['clause_id']} {results[0]['title']}.")

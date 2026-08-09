"""Persistent BM25 + dense LSA indexes with reciprocal-rank fusion and reranking."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from ultrafast_knowledge.evidence_pipeline.query import tokenize
from ultrafast_knowledge.evidence_pipeline.schemas import HybridIndexHit
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore


class ScientificIndexNotReady(RuntimeError):
    pass


class LSADenseEncoder:
    name = "contextual-tfidf-lsa-v1"

    def fit_transform(self, texts: list[str]) -> tuple[dict[str, Any], np.ndarray]:
        if not texts:
            raise ValueError("cannot build dense index without texts")
        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            max_features=4096,
            sublinear_tf=True,
        )
        tfidf = vectorizer.fit_transform(texts)
        maximum = min(64, tfidf.shape[0] - 1, tfidf.shape[1] - 1)
        if maximum >= 2:
            svd = TruncatedSVD(n_components=maximum, random_state=42)
            vectors = svd.fit_transform(tfidf)
            components = svd.components_.tolist()
            mode = "lsa"
        else:
            vectors = tfidf.toarray()
            components = []
            mode = "tfidf_dense"
        vectors = normalize(vectors, norm="l2")
        model = {
            "mode": mode,
            "vocabulary": {
                str(term): int(index)
                for term, index in vectorizer.vocabulary_.items()
            },
            "idf": vectorizer.idf_.tolist(),
            "components": components,
            "ngram_range": [1, 2],
        }
        return model, np.asarray(vectors, dtype=np.float64)

    def transform(self, text: str, model: dict[str, Any]) -> np.ndarray:
        vocabulary = {str(key): int(value) for key, value in model["vocabulary"].items()}
        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=tuple(model.get("ngram_range") or (1, 2)),
            vocabulary=vocabulary,
            sublinear_tf=True,
        )
        vectorizer.idf_ = np.asarray(model["idf"], dtype=np.float64)
        vector = vectorizer.transform([text])
        components = np.asarray(model.get("components") or [], dtype=np.float64)
        dense = vector @ components.T if model.get("mode") == "lsa" else vector.toarray()
        normalized = normalize(np.asarray(dense), norm="l2")
        return normalized[0]


class BM25Scorer:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def score(self, query: str, documents: list[str]) -> list[float]:
        tokenized = [tokenize(item) for item in documents]
        query_terms = list(dict.fromkeys(tokenize(query)))
        if not tokenized or not query_terms:
            return [0.0] * len(documents)
        average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
        document_frequency = Counter(
            term for terms in tokenized for term in set(terms)
        )
        scores: list[float] = []
        total = len(tokenized)
        for terms in tokenized:
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                df = document_frequency[term]
                idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * len(terms) / max(average_length, 1.0)
                )
                score += idf * frequency * (self.k1 + 1.0) / denominator
            scores.append(score)
        return scores


class HybridScientificIndex:
    def __init__(
        self,
        store: ScientificIndexStore,
        *,
        dense_encoder: LSADenseEncoder | None = None,
        bm25: BM25Scorer | None = None,
    ) -> None:
        self.store = store
        self.dense_encoder = dense_encoder or LSADenseEncoder()
        self.bm25 = bm25 or BM25Scorer()

    def rebuild(self, index_name: str) -> str:
        items = self.store.index_items(index_name)
        if not items:
            raise ValueError(f"cannot build empty {index_name} index")
        texts = [str(item["retrieval_text"]) for item in items]
        model, matrix = self.dense_encoder.fit_transform(texts)
        revision = hashlib.sha256(
            "\n".join(
                f"{item['item_id']}:{hashlib.sha256(text.encode()).hexdigest()}"
                for item, text in zip(items, texts, strict=True)
            ).encode()
        ).hexdigest()[:20]
        vectors = [
            {**item, "vector": matrix[index].tolist()}
            for index, item in enumerate(items)
        ]
        self.store.replace_index(
            index_name,
            revision,
            self.dense_encoder.name,
            model,
            vectors,
        )
        return revision

    def query(
        self,
        index_name: str,
        query_text: str,
        *,
        top_k: int,
        paper_ids: set[str] | None = None,
        document_version_ids: set[str] | None = None,
    ) -> list[HybridIndexHit]:
        state = self.store.index_state(index_name)
        if state is None:
            raise ScientificIndexNotReady(f"persistent {index_name} index is not built")
        items = self.store.index_items(index_name)
        stored_vectors = self.store.index_vectors(index_name, str(state["revision"]))
        current_ids = {str(item["item_id"]) for item in items}
        indexed_ids = {str(item["item_id"]) for item in stored_vectors}
        if current_ids != indexed_ids or len(items) != int(state["item_count"]):
            raise ScientificIndexNotReady(
                f"persistent {index_name} index is stale; rebuild after document ingestion"
            )
        if paper_ids is not None:
            items = [item for item in items if str(item["paper_id"]) in paper_ids]
        if document_version_ids is not None:
            items = [
                item
                for item in items
                if str(item["document_version_id"]) in document_version_ids
            ]
        if not items:
            return []
        documents = [str(item["retrieval_text"]) for item in items]
        bm25_scores = self.bm25.score(query_text, documents)
        vectors_by_id = {
            str(item["item_id"]): item
            for item in stored_vectors
        }
        query_vector = self.dense_encoder.transform(query_text, state["encoder_model"])
        dense_scores: list[float] = []
        for item in items:
            stored = vectors_by_id.get(str(item["item_id"]))
            if stored is None:
                dense_scores.append(-1.0)
                continue
            vector = np.asarray(stored["vector"], dtype=np.float64)
            dense_scores.append(float(vector @ query_vector) if len(vector) == len(query_vector) else -1.0)
        bm25_rank = _ranks(bm25_scores)
        dense_rank = _ranks(dense_scores)
        query_terms = set(tokenize(query_text))
        maximum_bm25 = max(bm25_scores) or 1.0
        output: list[HybridIndexHit] = []
        for index, item in enumerate(items):
            rrf = 1.0 / (60 + bm25_rank[index]) + 1.0 / (60 + dense_rank[index])
            document_terms = set(tokenize(documents[index]))
            coverage = len(query_terms.intersection(document_terms)) / max(1, len(query_terms))
            rerank = (
                rrf
                + 0.20 * bm25_scores[index] / maximum_bm25
                + 0.20 * max(0.0, dense_scores[index])
                + 0.10 * coverage
            )
            output.append(
                HybridIndexHit(
                    item_id=str(item["item_id"]),
                    paper_id=str(item["paper_id"]),
                    document_version_id=str(item["document_version_id"]),
                    block_id=item.get("block_id"),
                    score=rrf,
                    bm25_score=bm25_scores[index],
                    dense_score=dense_scores[index],
                    rerank_score=rerank,
                    rank_routes=["bm25", "dense_lsa", "rrf", "deterministic_rerank"],
                )
            )
        return sorted(output, key=lambda item: item.rerank_score, reverse=True)[:top_k]


def _ranks(scores: list[float]) -> dict[int, int]:
    ordered = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    return {item_index: rank for rank, item_index in enumerate(ordered, 1)}

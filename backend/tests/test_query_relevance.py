import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.api.v1.query import _filter_by_similarity, _select_diverse_chunks
from app.schemas.query import QueryRequest


class QueryRelevanceTests(unittest.TestCase):
    def test_filters_chunks_below_threshold_and_preserves_order(self):
        chunks = [
            {"id": "strong", "distance": 0.1},
            {"id": "weak", "distance": 0.8},
            {"id": "boundary", "distance": 0.75},
        ]

        result = _filter_by_similarity(chunks, min_similarity=0.25)

        self.assertEqual([chunk["id"] for chunk in result], ["strong", "boundary"])

    def test_accepts_per_query_similarity_override(self):
        request = QueryRequest(query="What changed?", min_similarity=0.6)

        self.assertEqual(request.min_similarity, 0.6)

    def test_rejects_similarity_outside_cosine_range(self):
        with self.assertRaises(ValidationError):
            QueryRequest(query="What changed?", min_similarity=1.01)

    def test_prefers_chunks_from_different_documents(self):
        chunks = [
            {"id": "a1", "document_id": "a"},
            {"id": "a2", "document_id": "a"},
            {"id": "a3", "document_id": "a"},
            {"id": "b1", "document_id": "b"},
            {"id": "c1", "document_id": "c"},
        ]

        result = _select_diverse_chunks(chunks, top_k=4, max_per_document=2)

        self.assertEqual([chunk["id"] for chunk in result], ["a1", "a2", "b1", "c1"])

    def test_backfills_when_only_one_document_is_available(self):
        chunks = [
            {"id": "a1", "document_id": "a"},
            {"id": "a2", "document_id": "a"},
            {"id": "a3", "document_id": "a"},
        ]

        result = _select_diverse_chunks(chunks, top_k=3, max_per_document=1)

        self.assertEqual([chunk["id"] for chunk in result], ["a1", "a2", "a3"])


if __name__ == "__main__":
    unittest.main()

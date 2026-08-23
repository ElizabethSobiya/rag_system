import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.services.vector_store import _MAX_EF_SEARCH, _ef_search_sql


class EfSearchStatementTests(unittest.TestCase):
    def test_uses_configured_value_when_it_covers_the_candidate_pool(self):
        self.assertEqual(
            _ef_search_sql(100, candidate_k=40),
            "SET LOCAL hnsw.ef_search = 100",
        )

    def test_raises_breadth_to_the_candidate_pool_size(self):
        # pgvector returns fewer rows than the LIMIT when ef_search is below it.
        self.assertEqual(
            _ef_search_sql(100, candidate_k=240),
            "SET LOCAL hnsw.ef_search = 240",
        )

    def test_clamps_to_the_supported_maximum(self):
        self.assertEqual(
            _ef_search_sql(50_000, candidate_k=40),
            f"SET LOCAL hnsw.ef_search = {_MAX_EF_SEARCH}",
        )

    def test_stays_within_the_supported_minimum(self):
        self.assertEqual(
            _ef_search_sql(0, candidate_k=0),
            "SET LOCAL hnsw.ef_search = 1",
        )

    def test_emits_only_integers(self):
        # The value is interpolated into SQL, so it must never carry raw input.
        statement = _ef_search_sql(100, candidate_k=40)
        self.assertTrue(statement.rsplit("= ", 1)[1].isdigit())


if __name__ == "__main__":
    unittest.main()

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.services.chunker import chunk_pages


class ChunkPagesTests(unittest.TestCase):
    def test_rejects_overlap_equal_to_chunk_size(self):
        with self.assertRaisesRegex(ValueError, "overlap must be smaller"):
            chunk_pages([("one two three four", 1)], chunk_size=2, overlap=2)

    def test_rejects_overlap_larger_than_chunk_size(self):
        with self.assertRaisesRegex(ValueError, "overlap must be smaller"):
            chunk_pages([("one two three four", 1)], chunk_size=2, overlap=3)

    def test_zero_overlap_is_respected(self):
        chunks = chunk_pages(
            [("one two three four", 1)],
            chunk_size=2,
            overlap=0,
        )

        self.assertEqual([chunk.token_count for chunk in chunks], [2, 2])

    def test_rejects_non_positive_chunk_size(self):
        with self.assertRaisesRegex(ValueError, "chunk_size must be greater than zero"):
            chunk_pages([("content", 1)], chunk_size=0, overlap=0)


if __name__ == "__main__":
    unittest.main()

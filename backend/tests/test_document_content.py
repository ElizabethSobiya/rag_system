import os
import unittest
import uuid

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.services.vector_store import _CHUNK_JOIN_SEPARATOR, get_document_content


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _RecordingSession:
    """Minimal AsyncSession stand-in that records every statement executed."""

    def __init__(self, row):
        self._row = row
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return _Result(self._row)


def _row(**overrides):
    row = {
        "id": uuid.uuid4(),
        "filename": "q2.pdf",
        "file_type": "pdf",
        "status": "ready",
        "content": "first chunk\n\nsecond chunk",
        "chunk_count": 2,
    }
    row.update(overrides)
    return row


class DocumentContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_content_and_count_in_one_round_trip(self):
        # Reassembly used to cost a metadata query plus a row per chunk.
        db = _RecordingSession(_row())

        result = await get_document_content(db, doc_id=uuid.uuid4())

        self.assertEqual(len(db.statements), 1)
        self.assertEqual(result["content"], "first chunk\n\nsecond chunk")
        self.assertEqual(result["chunk_count"], 2)

    async def test_joins_chunks_in_index_order(self):
        db = _RecordingSession(_row())

        await get_document_content(db, doc_id=uuid.uuid4())

        sql, params = db.statements[0]
        self.assertIn("string_agg", sql)
        self.assertIn("ORDER BY c.chunk_index", sql)
        self.assertEqual(params["separator"], _CHUNK_JOIN_SEPARATOR)

    async def test_reports_a_document_with_no_chunks_as_empty(self):
        # The LEFT JOIN keeps the document row, so a still-processing file is
        # distinguishable from one that does not exist.
        db = _RecordingSession(_row(status="processing", content="", chunk_count=0))

        result = await get_document_content(db, doc_id=uuid.uuid4())

        self.assertIsNotNone(result)
        self.assertEqual(result["content"], "")
        self.assertEqual(result["chunk_count"], 0)

    async def test_returns_none_for_an_unknown_document(self):
        db = _RecordingSession(None)

        self.assertIsNone(await get_document_content(db, doc_id=uuid.uuid4()))


if __name__ == "__main__":
    unittest.main()

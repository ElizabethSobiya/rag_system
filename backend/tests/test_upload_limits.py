import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.api.v1 import documents


class UploadLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_caps_read_at_one_byte_over_limit(self):
        upload = AsyncMock()
        upload.read.return_value = b"content"

        result = await documents._read_upload(upload)

        self.assertEqual(result, b"content")
        upload.read.assert_awaited_once_with(documents.MAX_UPLOAD_BYTES + 1)

    async def test_rejects_oversized_upload(self):
        upload = AsyncMock()
        upload.read.return_value = b"oversized"

        with patch.object(documents, "MAX_UPLOAD_BYTES", 5):
            with self.assertRaises(HTTPException) as raised:
                await documents._read_upload(upload)

        self.assertEqual(raised.exception.status_code, 413)

    async def test_rejects_empty_upload(self):
        upload = AsyncMock()
        upload.read.return_value = b""

        with self.assertRaises(HTTPException) as raised:
            await documents._read_upload(upload)

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

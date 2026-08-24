import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.schemas.query import QueryRequest
from app.services.llm import build_chat_history, condense_question, select_recent_turns


def _turns(count: int) -> list[dict]:
    return [{"question": f"q{i}", "answer": f"a{i}"} for i in range(count)]


class SelectRecentTurnsTests(unittest.TestCase):
    def test_keeps_the_most_recent_turns(self):
        result = select_recent_turns(_turns(10), max_turns=3)

        self.assertEqual([turn["question"] for turn in result], ["q7", "q8", "q9"])

    def test_returns_everything_when_under_the_limit(self):
        self.assertEqual(len(select_recent_turns(_turns(2), max_turns=6)), 2)

    def test_drops_all_history_when_the_limit_is_zero(self):
        self.assertEqual(select_recent_turns(_turns(4), max_turns=0), [])

    def test_does_not_alias_the_caller_list(self):
        history = _turns(2)

        select_recent_turns(history, max_turns=6).clear()

        self.assertEqual(len(history), 2)


class BuildChatHistoryTests(unittest.TestCase):
    def test_renders_alternating_user_and_assistant_messages(self):
        result = build_chat_history(_turns(2), max_turns=6)

        self.assertEqual(
            result,
            [
                {"role": "user", "content": "q0"},
                {"role": "assistant", "content": "a0"},
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
            ],
        )

    def test_empty_history_produces_no_messages(self):
        self.assertEqual(build_chat_history([], max_turns=6), [])


class CondenseQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_the_rewrite_when_there_is_no_history(self):
        with patch("app.services.llm._client") as client:
            result = await condense_question("What changed?", [])

        self.assertEqual(result, "What changed?")
        client.chat.completions.create.assert_not_called()

    async def test_returns_the_rewritten_question(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=" What did the Q2 report say? "))]
        )
        with patch("app.services.llm._client") as client:
            client.chat.completions.create = AsyncMock(return_value=completion)
            result = await condense_question("What about that one?", _turns(1))

        self.assertEqual(result, "What did the Q2 report say?")

    async def test_falls_back_to_the_original_question_on_an_empty_rewrite(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="   "))]
        )
        with patch("app.services.llm._client") as client:
            client.chat.completions.create = AsyncMock(return_value=completion)
            result = await condense_question("What about that one?", _turns(1))

        self.assertEqual(result, "What about that one?")

    async def test_falls_back_when_the_model_returns_no_choices(self):
        with patch("app.services.llm._client") as client:
            client.chat.completions.create = AsyncMock(
                return_value=SimpleNamespace(choices=[])
            )
            result = await condense_question("What about that one?", _turns(1))

        self.assertEqual(result, "What about that one?")


class RetrievalUsesCondensedQueryTests(unittest.IsolatedAsyncioTestCase):
    """The rewritten question, not the raw follow-up, must drive retrieval."""

    async def test_condensed_question_reaches_embedding_and_search(self):
        from app.api.v1 import query as query_api

        request = QueryRequest(
            query="What about the second one?",
            history=[{"question": "List the reports", "answer": "Q1 and Q2."}],
        )
        chunk = {
            "id": "c1", "document_id": "d1", "distance": 0.1,
            "filename": "q2.pdf", "page_number": 1, "rrf_score": 0.5,
        }

        with (
            patch.object(query_api, "condense_question", AsyncMock(return_value="What did the Q2 report say?")),
            patch.object(query_api, "embed_query", AsyncMock(return_value=[0.0])) as embed,
            patch.object(query_api, "search_similar_chunks", AsyncMock(return_value=[chunk])) as search,
        ):
            chunks, search_query = await query_api._get_chunks(request, db=None)

        self.assertEqual(search_query, "What did the Q2 report say?")
        embed.assert_awaited_once_with("What did the Q2 report say?")
        self.assertEqual(search.await_args.kwargs["query"], "What did the Q2 report say?")
        self.assertEqual(len(chunks), 1)

    async def test_standalone_question_is_searched_unchanged(self):
        from app.api.v1 import query as query_api

        request = QueryRequest(query="What did the Q2 report say?")
        chunk = {
            "id": "c1", "document_id": "d1", "distance": 0.1,
            "filename": "q2.pdf", "page_number": 1, "rrf_score": 0.5,
        }

        with (
            patch.object(query_api, "embed_query", AsyncMock(return_value=[0.0])),
            patch.object(query_api, "search_similar_chunks", AsyncMock(return_value=[chunk])) as search,
        ):
            _, search_query = await query_api._get_chunks(request, db=None)

        self.assertEqual(search_query, "What did the Q2 report say?")
        self.assertEqual(search.await_args.kwargs["query"], "What did the Q2 report say?")


class QueryRequestHistoryTests(unittest.TestCase):
    def test_history_defaults_to_empty(self):
        self.assertEqual(QueryRequest(query="What changed?").history, [])

    def test_accepts_prior_turns(self):
        request = QueryRequest(
            query="What about the second one?",
            history=[{"question": "List the reports", "answer": "Q1 and Q2."}],
        )

        self.assertEqual(request.history[0].question, "List the reports")

    def test_rejects_a_turn_with_a_blank_answer(self):
        with self.assertRaises(ValidationError):
            QueryRequest(
                query="What about it?",
                history=[{"question": "List the reports", "answer": "   "}],
            )

    def test_rejects_an_unbounded_conversation(self):
        with self.assertRaises(ValidationError):
            QueryRequest(query="What about it?", history=_turns(21))


if __name__ == "__main__":
    unittest.main()

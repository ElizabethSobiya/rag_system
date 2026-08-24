"""GPT-4o generation with citation assembly."""
from openai import AsyncOpenAI

from app.core.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

_SYSTEM_PROMPT = """\
You are a precise question-answering assistant. Answer the user's question using ONLY
the provided context excerpts. If the context does not contain enough information to
answer, say so clearly. Do not fabricate information.

Earlier turns of the conversation may appear before the question. Use them to
interpret what is being asked, but ground every claim in the provided excerpts —
never in an earlier answer.

For each fact or claim in your answer, reference the relevant excerpt by its [N] marker.
"""

_CONDENSE_PROMPT = """\
Rewrite the user's latest question so that it stands on its own, without the
conversation that came before it. Resolve references such as "it", "that one", or
"the second one" using the earlier turns.

If the question is already self-contained, return it unchanged. Never answer it.
Return only the rewritten question, with no preamble.
"""


def select_recent_turns(history: list[dict], max_turns: int) -> list[dict]:
    """Keep the most recent turns; older context is dropped before prompting."""
    if max_turns <= 0:
        return []
    return list(history[-max_turns:])


def build_chat_history(history: list[dict], max_turns: int) -> list[dict]:
    """Render prior turns as the alternating chat messages the API expects."""
    messages: list[dict] = []
    for turn in select_recent_turns(history, max_turns):
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    return messages


async def condense_question(query: str, history: list[dict]) -> str:
    """
    Rewrite a follow-up into a standalone question for retrieval.

    Retrieval embeds this text, so an unresolved "what about the second one?" would
    otherwise be matched against the corpus on its own. Any failure falls back to the
    original query rather than blocking the answer.
    """
    turns = select_recent_turns(history, settings.max_history_turns)
    if not turns:
        return query

    response = await _client.chat.completions.create(
        model=settings.chat_model,
        temperature=0,
        messages=[
            {"role": "system", "content": _CONDENSE_PROMPT},
            *build_chat_history(turns, settings.max_history_turns),
            {"role": "user", "content": query},
        ],
    )
    if not response.choices:
        return query
    return (response.choices[0].message.content or "").strip() or query


def _build_context_block(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        page_info = f", page {chunk['page_number']}" if chunk.get("page_number") else ""
        parts.append(
            f"[{i}] Source: {chunk['filename']}{page_info}\n{chunk['content']}"
        )
    return "\n\n---\n\n".join(parts)


async def generate_answer(
    query: str, chunks: list[dict], history: list[dict] | None = None
) -> dict:
    """
    Call GPT-4o with retrieved chunks as context.
    Returns {"answer": str, "citations": list[dict]}.
    """
    context = _build_context_block(chunks)
    user_message = f"Context:\n\n{context}\n\n---\n\nQuestion: {query}"

    response = await _client.chat.completions.create(
        model=settings.chat_model,
        temperature=settings.chat_temperature,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            *build_chat_history(history or [], settings.max_history_turns),
            {"role": "user", "content": user_message},
        ],
    )

    if not response.choices:
        raise RuntimeError("LLM returned empty response")
    answer_text = response.choices[0].message.content or ""

    citations = []
    for i, chunk in enumerate(chunks, start=1):
        # Include citation if the marker appears in the answer
        marker = f"[{i}]"
        citations.append(
            {
                "index": i,
                "filename": chunk["filename"],
                "page_number": chunk.get("page_number"),
                "excerpt": chunk["content"][:300],
                "similarity": round(1 - float(chunk["distance"]), 4),
                "referenced": marker in answer_text,
            }
        )

    return {"answer": answer_text, "citations": citations}


async def generate_answer_stream(
    query: str, chunks: list[dict], history: list[dict] | None = None
):
    """Yield answer text tokens, then the same citation payload used by the JSON API."""
    context = _build_context_block(chunks)
    stream = await _client.chat.completions.create(
        model=settings.chat_model,
        temperature=settings.chat_temperature,
        stream=True,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            *build_chat_history(history or [], settings.max_history_turns),
            {"role": "user", "content": f"Context:\n\n{context}\n\n---\n\nQuestion: {query}"},
        ],
    )
    answer_parts: list[str] = []
    try:
        async for event in stream:
            if not event.choices:
                continue
            token = event.choices[0].delta.content or ""
            if token:
                answer_parts.append(token)
                yield {"type": "delta", "text": token}
    except Exception as exc:
        yield {"type": "error", "error": str(exc)}
        return
    answer = "".join(answer_parts)
    citations = []
    for i, chunk in enumerate(chunks, start=1):
        citations.append({
            "index": i,
            "filename": chunk["filename"],
            "page_number": chunk.get("page_number"),
            "excerpt": chunk["content"][:300],
            "similarity": round(1 - float(chunk["distance"]), 4),
            "referenced": f"[{i}]" in answer,
        })
    yield {"type": "complete", "answer": answer, "citations": citations}

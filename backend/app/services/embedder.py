"""OpenAI embedding helpers."""
import asyncio

from openai import AsyncOpenAI

from app.core.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

# OpenAI allows up to 2048 inputs per request; use a safe batch size
_BATCH_SIZE = 512


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in batches. Returns embeddings in the same order."""
    if not texts:
        return []

    all_embeddings: list[list[float]] = []
    batches = [texts[i : i + _BATCH_SIZE] for i in range(0, len(texts), _BATCH_SIZE)]

    async def embed_batch(batch: list[str]) -> list[list[float]]:
        response = await _client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    results = await asyncio.gather(*[embed_batch(b) for b in batches])
    for batch_result in results:
        all_embeddings.extend(batch_result)

    return all_embeddings


async def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    response = await _client.embeddings.create(
        model=settings.embedding_model,
        input=[text],
    )
    return response.data[0].embedding

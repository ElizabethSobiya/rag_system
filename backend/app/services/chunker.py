"""Tiktoken-based sliding-window chunker with page number tracking."""
from collections import Counter
from dataclasses import dataclass

import tiktoken

from app.core.config import settings

_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class ChunkData:
    content: str
    token_count: int
    page_number: int | None
    chunk_index: int


def chunk_pages(
    pages: list[tuple[str, int]],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[ChunkData]:
    """
    Given a list of (text, page_number) tuples, tokenize everything, apply a
    sliding window, and return ChunkData objects with majority-vote page assignment.
    """
    chunk_size = settings.chunk_size_tokens if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap_tokens if overlap is None else overlap

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0:
        raise ValueError("overlap cannot be negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    # Build a flat token list paired with page numbers
    all_tokens: list[int] = []
    token_pages: list[int] = []  # page_number for each token position

    for text, page_num in pages:
        tokens = _ENCODING.encode(text)
        all_tokens.extend(tokens)
        token_pages.extend([page_num] * len(tokens))

    if not all_tokens:
        return []

    chunks: list[ChunkData] = []
    start = 0
    idx = 0

    while start < len(all_tokens):
        end = min(start + chunk_size, len(all_tokens))
        chunk_tokens = all_tokens[start:end]
        chunk_page_nums = token_pages[start:end]

        # Majority-vote page number
        page_counter = Counter(chunk_page_nums)
        majority_page = page_counter.most_common(1)[0][0]

        content = _ENCODING.decode(chunk_tokens)

        chunks.append(
            ChunkData(
                content=content,
                token_count=len(chunk_tokens),
                page_number=majority_page,
                chunk_index=idx,
            )
        )
        idx += 1

        if end == len(all_tokens):
            break
        start = end - overlap

    return chunks

"""Tiktoken-based sliding-window chunker with page number tracking."""
from bisect import bisect_right
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

    # Build a flat token list and run-length page boundaries for efficient lookup
    all_tokens: list[int] = []
    # Store cumulative token boundaries and corresponding page numbers
    page_boundaries: list[int] = []  # cumulative token count at end of each page
    page_numbers: list[int] = []     # page number for each boundary

    for text, page_num in pages:
        tokens = _ENCODING.encode(text)
        all_tokens.extend(tokens)
        page_boundaries.append(len(all_tokens))
        page_numbers.append(page_num)

    if not all_tokens:
        return []

    def _majority_page(start: int, end: int) -> int:
        """Find majority page number for token range [start, end) using bisect."""
        counts: Counter[int] = Counter()
        pos = start
        # Find the first boundary that covers tokens starting at 'pos'
        boundary_idx = bisect_right(page_boundaries, pos)
        while pos < end and boundary_idx < len(page_boundaries):
            segment_end = min(page_boundaries[boundary_idx], end)
            counts[page_numbers[boundary_idx]] += segment_end - pos
            pos = segment_end
            boundary_idx += 1
        return counts.most_common(1)[0][0]

    chunks: list[ChunkData] = []
    start = 0
    idx = 0

    while start < len(all_tokens):
        end = min(start + chunk_size, len(all_tokens))
        chunk_tokens = all_tokens[start:end]

        majority_page = _majority_page(start, end)

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

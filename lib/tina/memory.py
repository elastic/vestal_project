"""MemoryStore interface for track 1.4.

The learner implements remember() and recall() backed by cortex-tina-memory.
This module defines the interface; the implementation is the learner's work.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MemoryStore(ABC):
    """
    Base class for Tina's working memory.

    Backed by the cortex-tina-memory Elasticsearch index so memory
    stays on the same stack as everything else in this module.

    Implement remember() and recall() in your notebook.
    """

    # ── YOUR WORK ──
    @abstractmethod
    def remember(self, turn: int, content: dict[str, Any]) -> None:
        """
        Store a memory for this turn.

        Args:
            turn:    1-based turn number in the conversation.
            content: dict with keys you decide are worth keeping.
                     Must include at least {"entities": [...], "summary": str}.
        """

    # ── YOUR WORK ──
    @abstractmethod
    def recall(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        """
        Retrieve the k most relevant memories.

        Args:
            query: the current user message or entity to look up.
            k:     number of memories to retrieve.

        Returns:
            list of stored content dicts, most relevant first.
        """

    def flush(self) -> None:
        """Optional: clear all memories for this session. Default no-op."""

"""Loader protocol and normalised Trace shape.

Every source (Langfuse, Excel, future: OTEL, JSONL) must produce `Trace` objects
with this shape. The dashboard only ever talks to this normalised structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Protocol


@dataclass(slots=True)
class Message:
    """One turn in a conversation."""

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: datetime | None = None


@dataclass(slots=True)
class Trace:
    """A normalised trace, source-agnostic.

    The dashboard treats every trace as this shape regardless of where it came from.
    Loaders are responsible for mapping their native format into Trace instances.
    """

    id: str
    """Stable trace ID. For Langfuse-origin traces this is the Langfuse trace-id.
    For Excel-only traces this is whatever ID the Excel column carries.
    This is the join key between annotations and source data."""

    messages: list[Message]
    """Ordered list of turns. May be empty if the source only exposes a summary."""

    sources: list[str] = field(default_factory=list)
    """Reference URLs / passage identifiers the bot cited, if any."""

    metadata: dict = field(default_factory=dict)
    """Source-specific extras (tenant, category, question-id, etc). Opaque to the UI."""

    created_at: datetime | None = None
    """When the trace was recorded, if known."""

    @property
    def user_question(self) -> str:
        """Convenience: the first user turn as a single string, empty if none."""
        for m in self.messages:
            if m.role == "user":
                return m.content
        return ""

    @property
    def bot_answer(self) -> str:
        """Convenience: the last assistant turn, empty if none."""
        for m in reversed(self.messages):
            if m.role == "assistant":
                return m.content
        return ""


class Loader(Protocol):
    """Protocol every trace source must implement."""

    def list_trace_ids(self) -> list[str]:
        """Return all available trace IDs. Cheap; used to populate the dashboard index."""
        ...

    def get(self, trace_id: str) -> Trace | None:
        """Fetch one full trace by ID. Called on demand when the user opens a trace.

        Returns None if the trace isn't found in this source. Raise for transport errors
        (Langfuse down, file missing) so the dashboard can surface the problem.
        """
        ...

    def get_many(self, trace_ids: Iterable[str]) -> dict[str, Trace]:
        """Optional batch fetch. Default implementation falls back to per-id calls."""
        return {tid: t for tid in trace_ids if (t := self.get(tid)) is not None}

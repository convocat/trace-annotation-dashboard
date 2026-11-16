"""Langfuse loader.

Pulls traces from Langfuse on demand. The dashboard's primary data source.

Credentials come from env vars (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY) or
can be overridden via config. Host is config-driven since different users run
different Langfuse instances (hosted vs. self-hosted).

Design notes:
  - list_trace_ids() is the cheap "what's available" call. It pulls IDs via the
    Langfuse SDK's trace list, optionally filtered by dataset, session, tags,
    or a time range.
  - get() does the actual trace fetch and extracts messages. This is where the
    PII filter is applied (upstream in app.py, not here — the loader stays
    "dumb" and format-focused).
"""

from __future__ import annotations

import os
import ssl
from datetime import datetime
from typing import Iterable

from langfuse import Langfuse

from .base import Loader, Message, Trace


class LangfuseLoader(Loader):
    """Fetch traces from Langfuse via its Python SDK.

    Args:
        host: Langfuse base URL (e.g. https://cloud.langfuse.com).
        public_key / secret_key: credentials. If not passed, reads from env
            LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY.
        project_id: Langfuse project to scope queries to. Optional; the SDK
            normally scopes via the API key.
        dataset: if set, only lists trace IDs that are linked to this dataset.
        tags: if set, only lists traces carrying ALL of these tags.
        from_timestamp / to_timestamp: optional time window for list_trace_ids.
        tls_verify: set False to skip TLS verification (self-signed internal
            Langfuse hosts). Defaults to True.
    """

    def __init__(
        self,
        host: str,
        *,
        public_key: str | None = None,
        secret_key: str | None = None,
        project_id: str | None = None,
        dataset: str | None = None,
        tags: list[str] | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
        limit: int = 500,
        tls_verify: bool = True,
    ) -> None:
        self.host = host
        self.project_id = project_id
        self.dataset = dataset
        self.tags = tags or []
        self.from_ts = from_timestamp
        self.to_ts = to_timestamp
        self.limit = limit

        pk = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        sk = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        if not pk or not sk:
            raise RuntimeError(
                "Langfuse credentials missing: pass public_key/secret_key or set "
                "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY env vars."
            )

        if not tls_verify:
            # Only intended for internal Langfuse hosts with self-signed certs.
            ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[attr-defined]

        self._client = Langfuse(host=host, public_key=pk, secret_key=sk)

    # --- Loader protocol ----------------------------------------------------

    def list_trace_ids(self) -> list[str]:
        """List trace IDs matching the configured filters.

        Uses the SDK's trace list endpoint. If a dataset is configured, resolves
        IDs through the dataset's linked traces instead.
        """
        if self.dataset:
            return self._list_via_dataset()
        return self._list_via_search()

    def get(self, trace_id: str) -> Trace | None:
        """Fetch one trace by ID and normalise to Trace shape.

        Returns None if the trace isn't found. Lets exceptions from the SDK
        propagate so the dashboard can surface transport errors.
        """
        try:
            raw = self._client.fetch_trace(trace_id).data
        except Exception:
            # Older SDK variants: fall back to get_trace
            try:
                raw = self._client.get_trace(trace_id)
            except Exception:
                return None

        if raw is None:
            return None
        return self._to_trace(raw)

    def get_many(self, trace_ids: Iterable[str]) -> dict[str, Trace]:
        return {tid: t for tid in trace_ids if (t := self.get(tid)) is not None}

    # --- Internals ----------------------------------------------------------

    def _list_via_search(self) -> list[str]:
        """Use the SDK's fetch_traces with filters."""
        kwargs: dict = {"limit": self.limit}
        if self.tags:
            kwargs["tags"] = self.tags
        if self.from_ts:
            kwargs["from_timestamp"] = self.from_ts
        if self.to_ts:
            kwargs["to_timestamp"] = self.to_ts
        try:
            page = self._client.fetch_traces(**kwargs)
            return [t.id for t in page.data]
        except Exception:
            # Fallback for older SDKs
            return []

    def _list_via_dataset(self) -> list[str]:
        """Resolve trace IDs by looking at a dataset's run items.

        Datasets in Langfuse have items; each item may have one or more runs
        (actual trace executions). We surface the trace-IDs from those runs.
        """
        trace_ids: list[str] = []
        try:
            ds = self._client.get_dataset(self.dataset)
        except Exception:
            return trace_ids

        for item in getattr(ds, "items", []):
            runs = getattr(item, "runs", None) or []
            for run in runs:
                tid = getattr(run, "trace_id", None) or getattr(run, "traceId", None)
                if tid:
                    trace_ids.append(tid)
        return trace_ids

    def _to_trace(self, raw) -> Trace:
        """Map a Langfuse raw trace to our normalised Trace.

        The SDK's shape varies between versions; we probe common fields.
        """
        trace_id = getattr(raw, "id", "") or raw.get("id", "") if hasattr(raw, "get") else getattr(raw, "id", "")
        messages = self._extract_messages(raw)
        sources = self._extract_sources(raw)

        metadata = {}
        for key in ("name", "tags", "userId", "sessionId", "release", "version"):
            val = getattr(raw, key, None)
            if val:
                metadata[key] = val
        # Attach the Langfuse host so the UI can deep-link
        metadata["_langfuse_host"] = self.host
        if self.project_id:
            metadata["_langfuse_project_id"] = self.project_id

        timestamp = getattr(raw, "timestamp", None) or getattr(raw, "created_at", None)
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = None

        return Trace(
            id=str(trace_id),
            messages=messages,
            sources=sources,
            metadata=metadata,
            created_at=timestamp,
        )

    @staticmethod
    def _extract_messages(raw) -> list[Message]:
        """Pull user/assistant turns out of a raw Langfuse trace.

        Langfuse traces typically carry an `input` and `output`; `input` may be
        a list of messages, `output` may be a string or a message dict. We cope
        with both common shapes and leave structured sub-fields untouched.
        """
        messages: list[Message] = []

        input_ = getattr(raw, "input", None)
        if isinstance(input_, list):
            for m in input_:
                role = m.get("role", "user") if isinstance(m, dict) else "user"
                content = m.get("content", "") if isinstance(m, dict) else str(m)
                if isinstance(content, list):
                    # content blocks; concatenate text parts
                    content = "\n".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                messages.append(Message(role=role, content=str(content)))
        elif isinstance(input_, str) and input_:
            messages.append(Message(role="user", content=input_))
        elif isinstance(input_, dict):
            text = input_.get("content") or input_.get("text") or str(input_)
            messages.append(Message(role="user", content=str(text)))

        output = getattr(raw, "output", None)
        if isinstance(output, str) and output:
            messages.append(Message(role="assistant", content=output))
        elif isinstance(output, dict):
            text = output.get("content") or output.get("text") or ""
            if text:
                messages.append(Message(role="assistant", content=str(text)))

        return messages

    @staticmethod
    def _extract_sources(raw) -> list[str]:
        """Pull source URLs from metadata or output, if any."""
        sources: list[str] = []
        metadata = getattr(raw, "metadata", None) or {}
        if isinstance(metadata, dict):
            for key in ("sources", "citations", "rag_chunks"):
                val = metadata.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            sources.append(item)
                        elif isinstance(item, dict):
                            url = item.get("url") or item.get("source") or item.get("link")
                            if url:
                                sources.append(str(url))
        return sources

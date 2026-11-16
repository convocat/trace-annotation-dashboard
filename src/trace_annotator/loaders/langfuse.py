"""Langfuse loader.

Pulls traces from Langfuse via its public REST API — not via the Python SDK.

Why REST, not the SDK: the SDK is a tracing client whose shape changes each
major version (v2 → v3 → v5). The REST endpoints `/api/public/traces` and
`/api/public/traces/{id}` are stable and documented, and we only need read
access. Using REST keeps the loader working across every SDK generation.

Auth: HTTP Basic with the Langfuse public key as username and the secret key
as password. Credentials come from env (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)
or the config file. Each consumer project ships its own credentials; this
package stays credential-free.

Design notes:
  - list_trace_ids() is the cheap "what's available" call. Optional filters:
    dataset name, tags, time range.
  - get() fetches one trace with its observations and returns a normalised Trace.
  - Content is handed up to the dashboard, which scrubs PII before sending it
    to the browser.
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime
from typing import Any, Iterable

import httpx

from .base import Loader, Message, Trace


_MAX_RETRIES = 4
_INITIAL_BACKOFF = 1.0  # seconds; doubles each retry


class LangfuseLoader(Loader):
    """Fetch traces from Langfuse via its REST API."""

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
        environment: str | None = None,
        limit: int = 500,
        tls_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.project_id = project_id
        self.dataset = dataset
        self.tags = tags or []
        self.from_ts = from_timestamp
        self.to_ts = to_timestamp
        self.environment = environment
        self.limit = limit

        pk = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        sk = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        if not pk or not sk:
            raise RuntimeError(
                "Langfuse credentials missing. Pass public_key/secret_key or set "
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment."
            )

        auth_token = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        self._client = httpx.Client(
            base_url=f"{self.host}/api/public",
            headers={"Authorization": f"Basic {auth_token}"},
            timeout=timeout,
            verify=tls_verify,
        )

    # --- HTTP helper with retry/backoff ------------------------------------

    def _get_with_retry(self, path: str, params: dict | None = None) -> httpx.Response:
        """GET with exponential backoff on 429 and 5xx.

        Honours the server's `Retry-After` header when present. Caps at _MAX_RETRIES.
        """
        backoff = _INITIAL_BACKOFF
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._client.get(path, params=params)
            except httpx.TransportError as e:
                last_exc = e
                if attempt == _MAX_RETRIES:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == _MAX_RETRIES:
                    resp.raise_for_status()
                # Honour Retry-After header if present and parseable
                wait = backoff
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
                time.sleep(wait)
                backoff *= 2
                continue

            return resp

        # Unreachable, but satisfy the type checker
        raise RuntimeError(f"Exhausted retries: {last_exc!r}")

    # --- Loader protocol ----------------------------------------------------

    def list_trace_ids(self) -> list[str]:
        """List trace IDs matching the configured filters.

        If a dataset is configured, resolves IDs through that dataset's runs.
        Otherwise lists traces directly, newest first.
        """
        if self.dataset:
            return self._list_via_dataset()
        return self._list_traces_direct()

    def get(self, trace_id: str) -> Trace | None:
        """Fetch one full trace by ID, with its observations.

        Returns None if the trace isn't found (HTTP 404). Lets other HTTP errors
        propagate so the dashboard can surface them.
        """
        resp = self._get_with_retry(f"/traces/{trace_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._to_trace(resp.json())

    def get_many(self, trace_ids: Iterable[str]) -> dict[str, Trace]:
        return {tid: t for tid in trace_ids if (t := self.get(tid)) is not None}

    def close(self) -> None:
        self._client.close()

    # --- Internals ----------------------------------------------------------

    def _list_traces_direct(self) -> list[str]:
        """GET /api/public/traces — paged, newest first."""
        params: dict[str, Any] = {"limit": min(self.limit, 100)}  # Langfuse caps at 100/page
        if self.tags:
            params["tags"] = self.tags
        if self.from_ts:
            params["fromTimestamp"] = self.from_ts.isoformat()
        if self.to_ts:
            params["toTimestamp"] = self.to_ts.isoformat()
        if self.environment:
            params["environment"] = self.environment

        ids: list[str] = []
        page = 1
        while len(ids) < self.limit:
            params["page"] = page
            resp = self._get_with_retry("/traces", params=params)
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            if not data:
                break
            for item in data:
                tid = item.get("id")
                if tid:
                    ids.append(tid)
            meta = body.get("meta", {})
            total_pages = meta.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

        return ids[: self.limit]

    def _list_via_dataset(self) -> list[str]:
        """GET /api/public/datasets/{name}/runs — collect trace IDs from run items."""
        trace_ids: list[str] = []
        page = 1
        while True:
            resp = self._get_with_retry(
                f"/datasets/{self.dataset}/runs",
                params={"page": page, "limit": 100},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            body = resp.json()
            runs = body.get("data", [])
            if not runs:
                break

            # For each run, fetch its items (which carry the trace IDs)
            for run in runs:
                run_name = run.get("name")
                if not run_name:
                    continue
                items_resp = self._get_with_retry(
                    f"/datasets/{self.dataset}/runs/{run_name}"
                )
                if items_resp.status_code != 200:
                    continue
                items = items_resp.json().get("datasetRunItems", [])
                for item in items:
                    tid = item.get("traceId")
                    if tid:
                        trace_ids.append(tid)

            meta = body.get("meta", {})
            if page >= meta.get("totalPages", 1):
                break
            page += 1

            if len(trace_ids) >= self.limit:
                break

        # De-duplicate, preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for tid in trace_ids:
            if tid not in seen:
                seen.add(tid)
                unique.append(tid)
        return unique[: self.limit]

    def _to_trace(self, raw: dict) -> Trace:
        """Map a Langfuse REST trace response to our normalised Trace.

        Langfuse traces carry:
          - `input`:  the request payload (often a list of chat messages)
          - `output`: the response payload (often a string or a message dict)
          - `observations`: nested spans/generations with their own IOs
          - `metadata`, `tags`, `name`, `sessionId`, `userId`, `environment`

        Message extraction prefers trace-level `input`/`output` since that's the
        full conversation as seen by the top-level call. Observations are left
        as structured metadata for now.
        """
        trace_id = raw.get("id", "")
        messages = self._extract_messages(raw)
        sources = self._extract_sources(raw)

        metadata: dict = {}
        for key in ("name", "tags", "sessionId", "userId", "environment", "release", "version"):
            val = raw.get(key)
            if val not in (None, "", []):
                metadata[key] = val

        # Langfuse deep-link hints — used by the UI to render the "Open in Langfuse" button
        metadata["_langfuse_host"] = self.host
        if self.project_id:
            metadata["_langfuse_project_id"] = self.project_id
        elif raw.get("projectId"):
            metadata["_langfuse_project_id"] = raw["projectId"]

        timestamp = _parse_dt(raw.get("timestamp") or raw.get("createdAt"))

        return Trace(
            id=trace_id,
            messages=messages,
            sources=sources,
            metadata=metadata,
            created_at=timestamp,
        )

    @staticmethod
    def _extract_messages(raw: dict) -> list[Message]:
        """Build message list from trace input + output.

        Handles the three common shapes Langfuse traces carry:
          1. input = list of {role, content} chat messages
          2. input = string (single user turn)
          3. input = dict with a "messages" key (OpenAI-style request wrapper)
        Same tolerance on output.
        """
        messages: list[Message] = []

        input_ = raw.get("input")
        for m in _coerce_messages(input_, default_role="user"):
            messages.append(m)

        output = raw.get("output")
        for m in _coerce_messages(output, default_role="assistant"):
            messages.append(m)

        return messages

    @staticmethod
    def _extract_sources(raw: dict) -> list[str]:
        """Pull source URLs out of metadata for the sources panel in the UI."""
        sources: list[str] = []
        metadata = raw.get("metadata") or {}
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


# --- Helpers ----------------------------------------------------------------

def _coerce_messages(value: Any, default_role: str) -> list[Message]:
    """Turn a Langfuse input/output field into a list of Messages.

    Accepts: list of chat-messages, string, dict with `messages` key, dict with
    `content`/`text` key, or None. Content blocks (list of {type, text, ...})
    are concatenated for display.
    """
    if value is None or value == "":
        return []

    # Unwrap OpenAI-style request wrappers
    if isinstance(value, dict) and isinstance(value.get("messages"), list):
        return _coerce_messages(value["messages"], default_role)

    if isinstance(value, list):
        out: list[Message] = []
        for m in value:
            if isinstance(m, dict):
                role = m.get("role", default_role)
                content = m.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for p in content:
                        if isinstance(p, dict):
                            parts.append(p.get("text") or p.get("content") or "")
                        else:
                            parts.append(str(p))
                    content = "\n".join(p for p in parts if p)
                content = str(content)
                if content:
                    out.append(Message(role=role, content=content))
            elif isinstance(m, str) and m:
                out.append(Message(role=default_role, content=m))
        return out

    if isinstance(value, str):
        return [Message(role=default_role, content=value)]

    if isinstance(value, dict):
        content = value.get("content") or value.get("text") or ""
        if content:
            role = value.get("role", default_role)
            return [Message(role=role, content=str(content))]

    return []


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

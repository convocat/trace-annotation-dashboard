"""Excel loader.

Reads annotation-import Excel files (e.g. human testers' exports) and normalises
them to the shared Trace shape. Each sheet can have its own column mapping via
the `schemas` config dict.

Trace IDs:
  - If the sheet has a `trace_id_col`, that value is used as the Trace ID — this
    is how Excel-origin annotations join back to a Langfuse trace.
  - Without a `trace_id_col`, a synthetic ID `{sheet}__{row_index}` is used. The
    dashboard then treats it as Excel-only (no Langfuse deep-link).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import openpyxl

from .base import Loader, Message, Trace


class ExcelLoader(Loader):
    """Load traces from an .xlsx. Configured per sheet via a schema dict.

    Schema format (one entry per sheet name):
        {
            "SheetName": {
                "question_cols": ["Q1", "Q2"],     # concatenated for multi-turn
                "answer_col": "Bot answer",         # optional; may be None
                "trace_id_col": "Trace ID",         # optional
                "meta_cols": ["ID", "Category"],    # shown as tags in the UI
                "context_cols": ["Rating", "Notes"] # shown in "prior review" block
            },
        }
    """

    def __init__(self, path: Path | str, schemas: dict[str, dict]) -> None:
        self.path = Path(path)
        self.schemas = schemas
        self._cache: dict[str, Trace] | None = None

    # --- Loader protocol ----------------------------------------------------

    def list_trace_ids(self) -> list[str]:
        self._load_if_needed()
        return list(self._cache.keys()) if self._cache else []

    def get(self, trace_id: str) -> Trace | None:
        self._load_if_needed()
        return self._cache.get(trace_id) if self._cache else None

    def get_many(self, trace_ids: Iterable[str]) -> dict[str, Trace]:
        self._load_if_needed()
        if not self._cache:
            return {}
        return {tid: self._cache[tid] for tid in trace_ids if tid in self._cache}

    # --- Internals ----------------------------------------------------------

    def _load_if_needed(self) -> None:
        if self._cache is not None:
            return
        self._cache = {}
        if not self.path.exists():
            return

        wb = openpyxl.load_workbook(self.path, data_only=True, read_only=True)
        try:
            for sheet_name in wb.sheetnames:
                if sheet_name not in self.schemas:
                    continue
                schema = self.schemas[sheet_name]
                ws = wb[sheet_name]
                self._read_sheet(sheet_name, ws, schema)
        finally:
            wb.close()

    def _read_sheet(self, sheet_name: str, ws, schema: dict) -> None:
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(c).strip() if c is not None else "" for c in next(rows)]
        except StopIteration:
            return

        # Normalise schema and header column names so trailing spaces don't matter.
        def _n(s: str) -> str:
            return s.strip() if isinstance(s, str) else s

        header_norm = [_n(h) for h in header]
        q_cols = [_n(c) for c in schema.get("question_cols", [])]
        a_col = _n(schema.get("answer_col")) if schema.get("answer_col") else None
        tid_col = _n(schema.get("trace_id_col")) if schema.get("trace_id_col") else None
        meta_cols = [_n(c) for c in schema.get("meta_cols", [])]
        ctx_cols = [_n(c) for c in schema.get("context_cols", [])]

        q_idx = [header_norm.index(c) for c in q_cols if c in header_norm]
        a_idx = header_norm.index(a_col) if a_col and a_col in header_norm else None
        tid_idx = header_norm.index(tid_col) if tid_col and tid_col in header_norm else None
        meta_idx = {c: header_norm.index(c) for c in meta_cols if c in header_norm}
        ctx_idx = {c: header_norm.index(c) for c in ctx_cols if c in header_norm}

        for row_num, row in enumerate(rows, start=2):
            q_parts = [_s(row[i]) for i in q_idx if i < len(row)]
            q_parts = [p for p in q_parts if p]
            if not q_parts:
                continue
            question = "\n\n".join(q_parts)

            answer = _s(row[a_idx]) if a_idx is not None and a_idx < len(row) else ""

            if tid_idx is not None and tid_idx < len(row):
                tid_val = _s(row[tid_idx])
                trace_id = tid_val or f"{sheet_name}__{row_num}"
            else:
                trace_id = f"{sheet_name}__{row_num}"

            messages: list[Message] = [Message(role="user", content=question)]
            if answer:
                messages.append(Message(role="assistant", content=answer))

            metadata = {"_source": sheet_name}
            for col, idx in meta_idx.items():
                if idx < len(row):
                    val = _s(row[idx])
                    if val:
                        metadata[col] = val
            # Prior review / context — distinguished so the UI can render it separately
            context: dict[str, str] = {}
            for col, idx in ctx_idx.items():
                if idx < len(row):
                    val = _s(row[idx])
                    if val:
                        context[col] = val
            if context:
                metadata["_context"] = context

            self._cache[trace_id] = Trace(
                id=trace_id,
                messages=messages,
                metadata=metadata,
            )


def _s(value) -> str:
    if value is None:
        return ""
    return str(value).strip()

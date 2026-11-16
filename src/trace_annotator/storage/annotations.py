"""Local annotation storage.

Annotations live in a single .xlsx keyed by trace-ID. Scores, notes, categories
and actions — all your own work product. Safe to keep locally: these are *your*
observations about traces, not the trace content itself.

The file is created on first write. It always opens in "Annotaties" sheet for
backward compatibility with the earlier single-file prototype.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


SHEET_NAME = "Annotations"

HEADERS = [
    "Trace ID",
    "Project",
    "Source",
    "Question excerpt",
    "Answer excerpt",
    "Pass/Fail",
    "Note",
    "Category",
    "Action",
    "Response",
    "Timestamp",
]

COL_WIDTHS = {
    "Trace ID": 35,
    "Project": 16,
    "Source": 28,
    "Question excerpt": 50,
    "Answer excerpt": 50,
    "Pass/Fail": 10,
    "Note": 50,
    "Category": 28,
    "Action": 36,
    "Response": 50,
    "Timestamp": 20,
}


@dataclass
class Annotation:
    """One annotation keyed by trace-ID."""

    trace_id: str
    project: str = ""
    source: str = ""
    question_excerpt: str = ""
    answer_excerpt: str = ""
    pass_fail: str = ""  # "pass" | "fail" | ""
    note: str = ""
    category: str = ""
    action: str = ""
    response: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_row(self) -> list:
        return [
            self.trace_id,
            self.project,
            self.source,
            self.question_excerpt[:500],
            self.answer_excerpt[:500],
            self.pass_fail,
            self.note,
            self.category,
            self.action,
            self.response,
            self.timestamp,
        ]

    def to_dict(self) -> dict:
        return asdict(self)


class AnnotationStore:
    """Append-or-update annotation store backed by a single .xlsx."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = RLock()

    # --- Public API ---------------------------------------------------------

    def load_all(self) -> dict[str, Annotation]:
        """Return every annotation keyed by trace-id. Empty dict if no file yet."""
        with self._lock:
            if not self.path.exists():
                return {}
            wb = openpyxl.load_workbook(self.path, data_only=True)
            try:
                ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
                out: dict[str, Annotation] = {}
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if not row or not row[0]:
                        continue
                    ann = Annotation(
                        trace_id=str(row[0]),
                        project=str(row[1] or ""),
                        source=str(row[2] or ""),
                        question_excerpt=str(row[3] or ""),
                        answer_excerpt=str(row[4] or ""),
                        pass_fail=str(row[5] or ""),
                        note=str(row[6] or ""),
                        category=str(row[7] or ""),
                        action=str(row[8] or ""),
                        response=str(row[9] or ""),
                        timestamp=str(row[10] or ""),
                    )
                    out[ann.trace_id] = ann
                return out
            finally:
                wb.close()

    def save(self, ann: Annotation) -> None:
        """Insert or update a single annotation keyed by trace-id."""
        with self._lock:
            self._ensure_file()
            wb = openpyxl.load_workbook(self.path)
            try:
                ws = wb[SHEET_NAME]
                ann.timestamp = datetime.now().isoformat(timespec="seconds")

                target_row = None
                for r in range(2, ws.max_row + 1):
                    if ws.cell(row=r, column=1).value == ann.trace_id:
                        target_row = r
                        break
                if target_row is None:
                    target_row = ws.max_row + 1

                data_font = Font(name="Arial", size=10)
                wrap = Alignment(wrap_text=True, vertical="top")
                for col_idx, value in enumerate(ann.to_row(), start=1):
                    cell = ws.cell(row=target_row, column=col_idx, value=value)
                    cell.font = data_font
                    cell.alignment = wrap

                wb.save(self.path)
            finally:
                wb.close()

    # --- Internals ----------------------------------------------------------

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = SHEET_NAME
        ws.append(HEADERS)
        self._style_header(ws)
        ws.freeze_panes = "A2"
        for col_idx, header in enumerate(HEADERS, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = COL_WIDTHS.get(header, 20)
        wb.save(self.path)
        wb.close()

    @staticmethod
    def _style_header(ws) -> None:
        fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        align = Alignment(wrap_text=True, vertical="center", horizontal="left")
        for col in range(1, len(HEADERS) + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = font
            cell.fill = fill
            cell.alignment = align
        ws.row_dimensions[1].height = 28

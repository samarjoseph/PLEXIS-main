"""
ResultRowRepository — CRUD for AnalysisResultRow.

Provides bulk creation and retrieval of per-row source evidence
for analytical operations.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from db.models.result_row import AnalysisResultRow

logger = logging.getLogger(__name__)


class ResultRowRepository:
    """
    Data access for analysis_result_rows.

    All write methods flush immediately but do NOT commit — the caller manages
    transaction boundaries (typically via db_session() context manager).
    """

    def bulk_create(
        self,
        db,
        operation_id: UUID,
        rows: List[Dict[str, Any]],
    ) -> List[AnalysisResultRow]:
        """
        Bulk-insert AnalysisResultRow records for one operation.

        Each dict in `rows` must contain:
            source_row_number (int) — 1-based spreadsheet row number
            dataframe_index   (int) — 0-based df index (optional)
            record_data_json  (dict) — full row values snapshot
            column_value      (any)  — analytical value for this row (optional)

        Returns the created ORM objects (id assigned after flush).
        """
        if not rows:
            return []

        objs: List[AnalysisResultRow] = []
        for row in rows:
            obj = AnalysisResultRow(
                operation_id=operation_id,
                source_row_number=int(row["source_row_number"]),
                dataframe_index=row.get("dataframe_index"),
                record_data_json=row.get("record_data_json") or {},
                column_value=row.get("column_value"),
            )
            db.add(obj)
            objs.append(obj)

        try:
            db.flush()
            logger.debug(
                "[ResultRowRepository] Created %d rows for operation %s",
                len(objs), operation_id,
            )
        except Exception as e:
            logger.error(
                "[ResultRowRepository] bulk_create failed for operation %s: %s",
                operation_id, e, exc_info=True,
            )
            raise
        return objs

    def get_by_operation(
        self,
        db,
        operation_id: UUID,
    ) -> List[AnalysisResultRow]:
        """Return all rows for the given operation, ordered by source_row_number."""
        return (
            db.query(AnalysisResultRow)
            .filter(AnalysisResultRow.operation_id == operation_id)
            .order_by(AnalysisResultRow.source_row_number)
            .all()
        )

    def get_by_operation_as_dicts(
        self,
        db,
        operation_id: UUID,
    ) -> List[Dict[str, Any]]:
        """Return rows as dicts ready for API serialization."""
        rows = self.get_by_operation(db, operation_id)
        return [r.to_dict() for r in rows]

    def count_by_operation(self, db, operation_id: UUID) -> int:
        """Return count of rows for this operation."""
        return (
            db.query(AnalysisResultRow)
            .filter(AnalysisResultRow.operation_id == operation_id)
            .count()
        )


result_row_repository = ResultRowRepository()

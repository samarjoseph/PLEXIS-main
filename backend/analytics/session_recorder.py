"""
SessionRecorder — persists AnalyticalResult to PostgreSQL.

This is a thin wrapper around analysis_session_service.record_operation().
It translates the in-memory AnalyticalResult into the DB schema.

Migration 003 addition:
    After persisting AnalysisOperation, also bulk-inserts AnalysisResultRow records
    for each matching row. source_row_number = dataframe_index + 1 (1-based).
"""
import logging
from uuid import UUID
from typing import Optional

from analytics.result import AnalyticalResult
from db.models.analysis_session import AnalysisSession
from db.models.operation import AnalysisOperation
from db.services.analysis_session_service import analysis_session_service
from db.repositories.operation_repository import operation_repository

logger = logging.getLogger(__name__)


class SessionRecorder:
    """
    Persists an AnalyticalResult to AnalysisOperation + AnalysisResultRow.

    Updates the extended fields added by migration 002:
        value_json, row_indices_json, matching_rows_json,
        dataset_fingerprint, verified, verification_details,
        plan_json, normalized_intent, query_text

    Added by migration 003:
        Bulk-inserts AnalysisResultRow records (one per matching row).
    """

    def record(
        self,
        db,
        result: AnalyticalResult,
        session: AnalysisSession,
    ) -> AnalysisOperation:
        """
        Persist the AnalyticalResult and return the AnalysisOperation.

        The caller is responsible for db.commit().
        """
        plan_dict = result.plan if isinstance(result.plan, dict) else {}

        op = operation_repository.create_operation(
            db,
            analysis_session_id=session.id,
            dataset_id=result.dataset_id or session.dataset_id,
            operation_type=(result.operation or "unknown").upper(),
            column_name=result.column,
            parameters_json={
                "query": result.query,
                "intent": result.normalized_intent,
                "plan": plan_dict,
            },
            result_json=result.to_persistence_dict(),
            status="completed",
        )

        # Set extended fields (migration 002)
        try:
            op.value_json = {"value": result.value}  # type: ignore[attr-defined]
            op.row_indices_json = result.row_indices    # type: ignore[attr-defined]
            op.matching_rows_json = result.matching_rows[:10]  # type: ignore[attr-defined]
            op.dataset_fingerprint = result.dataset_fingerprint  # type: ignore[attr-defined]
            op.verified = result.verified  # type: ignore[attr-defined]
            op.verification_details = result.verification_details  # type: ignore[attr-defined]
            op.plan_json = plan_dict  # type: ignore[attr-defined]
            op.normalized_intent = result.normalized_intent  # type: ignore[attr-defined]
            op.query_text = result.query  # type: ignore[attr-defined]
            db.flush()
        except Exception as e:
            logger.warning(
                "[SessionRecorder] Could not set extended fields (migration 002 pending?): %s", e
            )

        # Sync the analysis_id back to the result so the caller has the DB id
        result.analysis_id = op.id

        # ── Migration 003: bulk-insert AnalysisResultRow ─────────────────────
        # Each matching row gets a permanent source_row_number (1-based).
        # This is the canonical source identity for future Locate operations.
        self._persist_result_rows(db, op, result)
        # ─────────────────────────────────────────────────────────────────────

        logger.info(
            "[SessionRecorder] Persisted op id=%s type=%s verified=%s rows=%d",
            op.id, op.operation_type, result.verified, len(result.matching_rows),
        )
        return op

    def _persist_result_rows(
        self,
        db,
        op: AnalysisOperation,
        result: AnalyticalResult,
    ) -> None:
        """
        Bulk-insert AnalysisResultRow records for each matching row.

        source_row_number is derived from the row's _row_number field if present,
        otherwise falls back to dataframe_index + 1.

        Failures are logged but never propagated — they don't block the main pipeline.
        """
        matching_rows = result.matching_rows
        row_indices = result.row_indices

        if not matching_rows:
            return

        try:
            from db.repositories.result_row_repository import result_row_repository

            rows_to_insert = []
            for i, row_data in enumerate(matching_rows):
                # Prefer _row_number set by the executor (1-based)
                source_row_number = row_data.get("_row_number")
                if source_row_number is None:
                    # Fall back: use row_indices[i] as 0-based df index → +1 for 1-based
                    df_idx = row_indices[i] if i < len(row_indices) else i
                    source_row_number = int(df_idx) + 1
                else:
                    source_row_number = int(source_row_number)

                df_idx = row_indices[i] if i < len(row_indices) else None

                # Extract the column value for this row
                col_value = None
                if result.column and result.column in row_data:
                    col_value = row_data[result.column]

                # Strip internal _row_number from the stored record so it's clean
                clean_row = {k: v for k, v in row_data.items() if k != "_row_number"}

                rows_to_insert.append({
                    "source_row_number": source_row_number,
                    "dataframe_index": df_idx,
                    "record_data_json": clean_row,
                    "column_value": col_value,
                })

            result_row_repository.bulk_create(db, op.id, rows_to_insert)
            logger.debug(
                "[SessionRecorder] Inserted %d result rows for op %s",
                len(rows_to_insert), op.id,
            )
        except Exception as e:
            logger.error(
                "[SessionRecorder] _persist_result_rows failed for op %s: %s",
                op.id, e, exc_info=True,
            )
            # Non-fatal — don't re-raise


session_recorder = SessionRecorder()

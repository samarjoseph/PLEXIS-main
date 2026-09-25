"""
AnalyticsPipeline — canonical orchestrator for the Plexis analytical brain.

Flow:
  PlannerContext.build()
       ↓
  AnalyticalPlanner.plan()   [LLM, temp=0.0, max 3 repair attempts]
       ↓
  PlanValidator.validate()   [deterministic]
       ↓
  PandasExecutor.execute()   [deterministic, no LLM]
       ↓
  ResultVerifier.verify()    [deterministic, no LLM]
       ↓
  SessionRecorder.record()   [PostgreSQL persist]
       ↓
  AnalyticalResult           [canonical in-memory object]

Rules:
  - LLM is called ONLY in the Planner step
  - Executor and Verifier have ZERO LLM access
  - AnalyticalResult.value is ALWAYS from Pandas, never from LLM
  - If planning fails, return a structured failure — never hallucinate
  - The pipeline does NOT compose the final response — that is the Composer
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple
from uuid import UUID

import pandas as pd

from analytics.result import AnalyticalResult
from analytics.session_recorder import session_recorder
from executor.pandas_executor import pandas_executor, ExecutorResult
from planner.context import planner_context_builder
from planner.core import analytical_planner
from planner.schema import AnalyticalPlan
from planner.validator import plan_validator, PlanValidationResult
from verifier.result_verifier import result_verifier, VerifierResult

logger = logging.getLogger(__name__)


class AnalyticsPipeline:
    """
    Orchestrates the full analytical brain pipeline.

    One instance, stateless — all state is in AnalyticalResult and PostgreSQL.
    """

    def run(
        self,
        execution_context,  # core.context.ExecutionContext
        df: pd.DataFrame,
        db=None,
    ) -> AnalyticalResult:
        """
        Run the full analytical pipeline for one user query.

        Args:
            execution_context: Resolved ExecutionContext from core pipeline.
            df:                The active dataset DataFrame.
            db:                SQLAlchemy session (for persistence + context loading).

        Returns:
            AnalyticalResult — always returns, never raises.
            On failure: result.verified = False, result.value = None.
        """
        query = execution_context.message or ""
        user_id = getattr(execution_context, "user_id", None)
        chat_id = getattr(execution_context, "chat_id", None)
        dataset_id = getattr(execution_context, "dataset_id", None)
        dataset_fingerprint = getattr(execution_context, "dataset_fingerprint", None)

        logger.info("[Pipeline] Starting for query: %s", query[:80])

        # Shared result scaffolding
        result = AnalyticalResult(
            user_id=user_id,
            chat_id=chat_id,
            dataset_id=dataset_id,
            dataset_fingerprint=dataset_fingerprint,
            query=query,
        )

        # ----------------------------------------------------------------
        # Step 1: Build planner context
        # Pass df directly so column types come from Pandas dtype (authoritative)
        # ----------------------------------------------------------------
        try:
            planner_ctx = planner_context_builder.build(
                execution_context, db=db, df=df
            )
        except Exception as e:
            logger.error("[Pipeline] PlannerContext build failed: %s", e, exc_info=True)
            result.verification_details = {"error": "planner_context_failed", "detail": str(e)}
            return result

        columns = planner_ctx.get("columns", [])
        column_types = planner_ctx.get("column_types", {})

        if not columns:
            logger.warning("[Pipeline] No columns in planner context — cannot plan.")
            result.verification_details = {"error": "no_schema"}
            return result

        # ----------------------------------------------------------------
        # Step 2: Plan  [LLM, temperature=0.0]
        # ----------------------------------------------------------------
        plan: Optional[AnalyticalPlan] = analytical_planner.plan(query, planner_ctx)

        if plan is None:
            logger.warning("[Pipeline] Planner returned None after max attempts.")
            result.verification_details = {"error": "planner_failed"}
            return result

        result.normalized_intent = plan.intent
        result.operation = plan.operation
        result.column = plan.target_column
        result.plan = plan.raw

        logger.info(
            "[PlannerOutput] intent=%s operation=%s column=%s steps=%d",
            plan.intent, plan.operation, plan.target_column, len(plan.plan or []),
        )

        # ----------------------------------------------------------------
        # Step 3: Validate plan  [deterministic]
        # ----------------------------------------------------------------
        # Log the exact context used for validation
        target_col = plan.target_column
        resolved_type = column_types.get(target_col, "unknown") if target_col else "n/a"
        logger.info(
            "[PlannerValidationContext] column=%s canonical_type=%s operation=%s",
            target_col, resolved_type, plan.operation,
        )

        validation: PlanValidationResult = plan_validator.validate(
            plan=plan,
            columns=columns,
            column_types=column_types,
            dataset_fingerprint=dataset_fingerprint,
        )

        if not validation.valid:
            logger.warning(
                "[Pipeline] Plan validation failed: %s — %s",
                validation.error_code, validation.error_message,
            )
            result.verification_details = {
                "error": "validation_failed",
                "code": validation.error_code,
                "message": validation.error_message,
            }
            return result

        logger.info(
            "[PlannerValidationContext] column=%s canonical_type=%s operation=%s valid=true",
            target_col, resolved_type, plan.operation,
        )

        # ----------------------------------------------------------------
        # Step 4: Execute  [Pandas, no LLM]
        # ----------------------------------------------------------------
        exec_result: ExecutorResult = pandas_executor.execute(plan, df)

        if not exec_result.success:
            logger.warning("[Pipeline] Executor failed: %s", exec_result.error)
            result.verification_details = {"error": "executor_failed", "detail": exec_result.error}
            return result

        result.value = exec_result.value
        result.row_indices = exec_result.row_indices
        result.matching_rows = exec_result.matching_rows

        logger.info("[Pipeline] Executor: value=%s indices=%d", result.value, len(result.row_indices))

        # ----------------------------------------------------------------
        # Step 5: Verify  [deterministic, no LLM]
        # ----------------------------------------------------------------
        verify_result: VerifierResult = result_verifier.verify(exec_result, plan, df)

        result.verified = verify_result.verified
        result.verification_details = verify_result.details or {}
        if verify_result.error_message:
            result.verification_details["error"] = verify_result.error_message

        if not result.verified:
            logger.error(
                "[Pipeline] Verification FAILED: expected=%s actual=%s",
                verify_result.expected, verify_result.actual,
            )
            # Return with verified=False — the caller must NOT present this as fact
            return result

        logger.info("[Pipeline] Verified: %s", result.verified)

        # ----------------------------------------------------------------
        # Step 6: Persist  [PostgreSQL]
        # ----------------------------------------------------------------
        # Persistence requires real FK-valid UUIDs for both chat_id and
        # dataset_id in the analysis_sessions table.
        #
        # When the frontend hasn't created a DB chat (chatId is null on the
        # conversation object), we auto-create one so the FK constraint is
        # satisfied and analysis operations are always persisted.
        if db is not None and dataset_id:
            try:
                import uuid as _uuid
                from db.repositories.chat_repository import chat_repository
                from db.services.analysis_session_service import analysis_session_service

                persist_chat_id = chat_id

                # Resolve or create a valid DB chat
                if persist_chat_id:
                    # Validate it's a real UUID
                    try:
                        persist_chat_id = _uuid.UUID(str(persist_chat_id))
                    except (ValueError, AttributeError):
                        persist_chat_id = None

                if not persist_chat_id:
                    # Auto-create a DB chat for this session
                    chat = chat_repository.create_chat(
                        db,
                        user_id=user_id or _uuid.UUID('00000000-0000-0000-0000-000000000000'),
                        title="Auto: Analysis Session",
                        current_dataset_id=_uuid.UUID(str(dataset_id)),
                    )
                    persist_chat_id = chat.id
                    # Expose back to the calling context so the frontend gets it
                    execution_context.chat_id = str(chat.id)
                    logger.info(
                        "[Pipeline] Auto-created DB chat id=%s for persistence",
                        chat.id,
                    )

                # Ensure dataset_id is a valid UUID
                persist_dataset_id = _uuid.UUID(str(dataset_id))

                session = analysis_session_service.get_or_restore_session(
                    db, persist_chat_id, persist_dataset_id, user_id
                )
                op = session_recorder.record(db, result, session)
                # Sync the DB-assigned UUID back so frontend gets the real analysis_id
                result.analysis_id = op.id
                db.commit()
                logger.info("[Pipeline] Persisted op id=%s chat_id=%s", op.id, persist_chat_id)
            except Exception as e:
                logger.error("[Pipeline] Persistence failed: %s", e, exc_info=True)
                try:
                    db.rollback()
                except Exception:
                    pass
                # Persistence failure does NOT invalidate the analytical result
        else:
            logger.warning("[Pipeline] Skipping persistence (no db/dataset_id).")

        return result

    # -------------------------------------------------------------------------
    # Helpers for building EngineResult from AnalyticalResult
    # -------------------------------------------------------------------------

    def build_narrative(self, result: AnalyticalResult, dataset_name: str = "the dataset") -> str:
        """
        Build a grounded narrative from a verified AnalyticalResult.

        The LLM Composer MUST use this value rather than recomputing.
        """
        if not result.verified or result.value is None:
            return ""

        col = result.column or "value"
        val = result.value
        op = result.operation

        # Format the narrative based on operation type
        if op in ("max", "min"):
            label = "highest" if op == "max" else "lowest"
            name_parts = []
            for row in result.matching_rows[:1]:
                # Find a likely name column
                for name_col in ("name", "Name", "full_name", "Full_Name", "employee"):
                    if row.get(name_col):
                        name_parts.append(str(row[name_col]))
                        break
            if name_parts:
                return (
                    f"In **{dataset_name}**, the {label} **{col}** is **{val}** "
                    f"(record: {name_parts[0]})."
                )
            return f"In **{dataset_name}**, the {label} **{col}** is **{val}**."

        if op in ("mean", "median"):
            label = "average" if op == "mean" else "median"
            return f"The {label} **{col}** in **{dataset_name}** is **{val}**."

        if op == "sum":
            return f"The total **{col}** in **{dataset_name}** is **{val}**."

        if op == "count":
            return f"There are **{val}** rows in **{dataset_name}**."

        if op == "std":
            return f"The standard deviation of **{col}** is **{val}**."

        # Default
        return f"**{col}** → **{val}** (operation: {op})"


# Singleton
analytics_pipeline = AnalyticsPipeline()

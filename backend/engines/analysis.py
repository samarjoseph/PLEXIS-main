"""
AnalysisEngine — the analytical execution engine for Plexis.

Handles DATA_OPERATION intents from the MasterRouter.

CORRECTED ARCHITECTURE (Phase 4):
  The AnalysisEngine now delegates ALL analytical computation to the pipeline:
    AnalyticsPipeline → Planner → Validator → Executor → Verifier → PostgreSQL

  The Capability registry is kept as a FAST PATH for operations that have
  a direct, unambiguous mapping and don't need LLM planning.
  e.g., if context.operation == "MAX" and column is already resolved.

  But the PRIMARY path for all natural-language queries is now the pipeline.

Separation of concerns:
  - Router: WHAT kind of request (DATA_OPERATION)
  - Pipeline/Planner: WHAT the operation means (max(age))
  - Executor: COMPUTE the answer (65)
  - Verifier: CONFIRM the answer
  - Composer: EXPLAIN the answer (never change it)
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

import pandas as pd

from engines.base import BaseEngine, EngineResult
from analytics.result import AnalyticalResult

if TYPE_CHECKING:
    from core.context import ExecutionContext

logger = logging.getLogger(__name__)


class AnalysisEngine(BaseEngine):
    """
    Handles DATA_OPERATION intents.

    Primary path: AnalyticsPipeline (planner → executor → verifier)
    """

    @property
    def engine_name(self) -> str:
        return "analysis"

    def can_handle(self, context: "ExecutionContext") -> bool:
        return getattr(context, "intent", None) in ("analysis", "DATA_OPERATION", "data_operation")

    def handle(self, context: "ExecutionContext") -> EngineResult:
        logger.info("[AnalysisEngine] Handling DATA_OPERATION: %s", context.message[:80])

        # ── Step 1: Resolve DataFrame ─────────────────────────────────────────────
        df = self._resolve_dataframe(context)
        if df is None:
            return EngineResult(
                answer="I don't have a dataset to analyze. Please upload one first.",
                source="analysis",
                success=False,
                should_compose=False,
            )

        # ── Step 2: Run the analytical pipeline ───────────────────────────────
        try:
            db = self._get_db()
            from analytics.pipeline import analytics_pipeline
            result: AnalyticalResult = analytics_pipeline.run(context, df, db=db)
        except Exception as e:
            logger.error("[AnalysisEngine] Pipeline error: %s", e, exc_info=True)
            return EngineResult(
                answer="An error occurred during analysis.",
                source="analysis",
                success=False,
                should_compose=False,
            )

        # ── Step 3: Handle pipeline failure ───────────────────────────────────
        if result.value is None and not result.verified:
            err = result.verification_details.get("error", "unknown")
            logger.warning("[AnalysisEngine] Pipeline could not compute result: %s", err)

            # Try capability fallback for simple cases
            engine_result = self._capability_fallback(context, df)
            if engine_result:
                return engine_result

            # If planning failed completely, tell the user honestly
            if err == "planner_failed":
                return EngineResult(
                    answer=(
                        "I couldn't reliably interpret that analytical request. "
                        "Could you rephrase it? For example: 'what is the highest age?'"
                    ),
                    source="analysis",
                    success=False,
                    should_compose=False,
                )
            return EngineResult(
                answer="",
                source="analysis",
                success=True,
                should_compose=True,  # Let LLM try for non-analytical failures
                facts={"query": context.message},
            )

        # ── Step 4: Build EngineResult from verified AnalyticalResult ────────
        dataset_name = getattr(context, "dataset_filename", "the dataset") or "the dataset"
        from analytics.pipeline import analytics_pipeline
        narrative = analytics_pipeline.build_narrative(result, dataset_name)

        engine_result = EngineResult(
            answer=narrative,
            source="analysis",
            provider="system",
            success=True,
            # should_compose=False — the narrative is grounded, LLM must NOT recompute
            # should_compose=True — LLM composes a natural response using the facts
            # We use should_compose=True but pass VERIFIED facts to prevent hallucination.
            should_compose=True,
            facts={
                "value": result.value,
                "operation": result.operation,
                "column": result.column,
                "matching_rows": result.matching_rows[:3],
                "row_indices": result.row_indices[:5],
                "verified": result.verified,
                "dataset_name": dataset_name,
                "analysis_id": str(result.analysis_id),
            },
            metadata={
                "analysis_id": str(result.analysis_id),
                "verified": result.verified,
                "operation": result.operation,
                "column": result.column,
            },
        )

        # Attach analysis_id to context so it can be included in the response
        context.analysis_id = str(result.analysis_id)
        # Attach full result so chat.py can build the result block without a DB round-trip
        context.analytical_result = result

        return engine_result

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _resolve_dataframe(self, context: "ExecutionContext") -> Optional[pd.DataFrame]:
        """L1 (in-memory registry) → L2 (PostgreSQL restore)."""
        dataset_id = getattr(context, "dataset_id", None)

        if dataset_id:
            try:
                from datasets.registry import dataset_registry
                entry = dataset_registry.get(str(dataset_id))
                if entry and hasattr(entry, "dataframe") and entry.dataframe is not None:
                    logger.debug("[AnalysisEngine] L1 hit: dataset_id=%s", dataset_id)
                    return entry.dataframe
            except Exception as e:
                logger.warning("[AnalysisEngine] DatasetRegistry error: %s", e)

        if dataset_id:
            try:
                db = self._get_db()
                from db.services.dataset_service import dataset_service
                user_id = getattr(context, "user_id", None)
                df = dataset_service.restore_dataset_df(db, dataset_id, user_id)
                if df is not None:
                    logger.info("[AnalysisEngine] L2 restore: dataset_id=%s", dataset_id)
                    return df
            except Exception as e:
                logger.error("[AnalysisEngine] L2 restore failed: %s", e, exc_info=True)

        return None

    def _get_db(self):
        """Get the current SQLAlchemy session."""
        try:
            from db.session import get_db
            return get_db()
        except Exception as e:
            logger.warning("[AnalysisEngine] _get_db failed: %s", e)
            return None

    def _capability_fallback(
        self,
        context: "ExecutionContext",
        df: pd.DataFrame,
    ) -> Optional[EngineResult]:
        """
        Fallback to the Capability registry for simple unambiguous operations.
        Used when the planner fails but we have high-confidence context signals.
        """
        try:
            from capabilities.registry import capability_registry
            from capabilities.base import CapabilityResult

            capability = capability_registry.resolve(context)
            if capability is None:
                return None

            logger.info(
                "[AnalysisEngine] Capability fallback: %s", capability.capability_id
            )
            cap_result: CapabilityResult = capability.execute(context, df)

            if not cap_result.success:
                return None

            has_hint = bool(cap_result.narrative_hint)
            return EngineResult(
                answer=cap_result.narrative_hint if has_hint else "",
                source="analysis",
                provider="system",
                success=True,
                facts=cap_result.facts,
                evidence=cap_result.evidence,
                should_compose=not has_hint,
                metadata={"capability_fallback": capability.capability_id},
            )
        except Exception as e:
            logger.warning("[AnalysisEngine] Capability fallback error: %s", e)
            return None


analysis_engine = AnalysisEngine()

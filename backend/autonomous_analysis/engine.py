"""
autonomous_analysis/engine.py

Top-level orchestrator for the Autonomous Dataset Investigation Engine.

This runs OUTSIDE the upload critical path. The upload completes as soon as
the DKO is ready. This engine is triggered afterwards in a background thread
and streams progressive findings via a separate SSE endpoint.

Pipeline:
  DKO → DatasetSummaryBuilder
      → CandidateGenerator
      → CandidateFilter (hard → score → MMR → top-K)
      → InvestigationPlanner (LLM #1)
      → AutonomousExecutor (deterministic, budget-aware)
      → ResultValidator
      → InterpretationEngine (LLM #2 per result)
      → InsightSynthesizer (cross-finding)
      → PresentationBuilder (N results → M sections)
      → InvestigationReport

Rules:
  - Never blocks the upload SSE flow
  - Partial results are preserved on timeout or failure
  - Every numerical finding is grounded in deterministic evidence
  - The LLM never computes authoritative results
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from autonomous_analysis.contracts import (
    AnalysisCandidate,
    AnalysisBudget,
    InvestigationPlan,
    InvestigationReport,
    InvestigationResult,
    SectionGroup,
)
from autonomous_analysis.dataset_summary_builder import dataset_summary_builder
from autonomous_analysis.candidate_generator import candidate_generator
from autonomous_analysis.candidate_filter import candidate_filter
from autonomous_analysis.investigation_planner import investigation_planner
from autonomous_analysis.autonomous_executor import autonomous_executor
from autonomous_analysis.result_validator import result_validator
from autonomous_analysis.investigation_cache import investigation_cache
from dataset_intelligence.models_v2 import DatasetKnowledgeObject

logger = logging.getLogger(__name__)


class InvestigationEvent:
    """A single SSE event emitted during investigation."""

    __slots__ = ("event_type", "data")

    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data

    def to_sse(self) -> str:
        return f"event: {self.event_type}\ndata: {json.dumps(self.data, default=str)}\n\n"


class AutonomousInvestigationEngine:
    """
    Orchestrates the full autonomous investigation pipeline.

    Usage:
        1. Call `start_background(dataset_id, dko, df)` after upload completes.
           This starts the investigation in a daemon thread.
        2. Call `stream_events(dataset_id)` to get a generator of SSE events.
        3. Call `get_report(dataset_id)` to get the cached report (if complete).
    """

    def __init__(self):
        # Active investigation state keyed by dataset_id
        self._active: Dict[str, dict] = {}
        self._lock = threading.Lock()

    # ─── Public API ───────────────────────────────────────────────────────────

    def start_background(
        self,
        dataset_id: str,
        dko: DatasetKnowledgeObject,
        df: pd.DataFrame,
    ) -> None:
        """Start investigation in a background thread. Non-blocking."""
        with self._lock:
            if dataset_id in self._active and self._active[dataset_id].get("running"):
                logger.info("[InvestigationEngine] Already running for %s", dataset_id)
                return

            state = {
                "running": True,
                "events": [],      # List[InvestigationEvent]
                "report": None,    # InvestigationReport dict when done
                "started_at": time.time(),
                "waiters": [],     # threading.Event objects for SSE consumers
            }
            self._active[dataset_id] = state

        thread = threading.Thread(
            target=self._run_pipeline,
            args=(dataset_id, dko, df),
            daemon=True,
            name=f"investigation-{dataset_id[:8]}",
        )
        thread.start()
        logger.info("[InvestigationEngine] Background investigation started for %s", dataset_id)

    def stream_events(self, dataset_id: str):
        """
        Generator that yields InvestigationEvent objects as they arrive.
        Blocks between events. Terminates when investigation is done.
        """
        state = self._active.get(dataset_id)
        if state is None:
            # Check cache
            cached = investigation_cache.get_report(
                self._get_fingerprint(dataset_id)
            )
            if cached:
                yield InvestigationEvent("investigation", {"status": "cached"})
                yield InvestigationEvent("investigation_done", cached)
                return
            yield InvestigationEvent("investigation", {"status": "not_started"})
            return

        idx = 0
        while True:
            # Yield any new events
            while idx < len(state["events"]):
                yield state["events"][idx]
                idx += 1

            # Check if done
            if not state["running"]:
                # Yield any remaining events
                while idx < len(state["events"]):
                    yield state["events"][idx]
                    idx += 1
                break

            # Wait for new events (with timeout to prevent infinite hang)
            waiter = threading.Event()
            state["waiters"].append(waiter)
            waiter.wait(timeout=5.0)

    def get_report(self, dataset_id: str) -> Optional[dict]:
        """Get the completed investigation report, or None if not done."""
        state = self._active.get(dataset_id)
        if state and state.get("report"):
            return state["report"]

        # Fall back to cache
        fp = self._get_fingerprint(dataset_id)
        if fp:
            return investigation_cache.get_report(fp)
        return None

    def is_running(self, dataset_id: str) -> bool:
        state = self._active.get(dataset_id)
        return bool(state and state.get("running"))

    # ─── Pipeline ─────────────────────────────────────────────────────────────

    def _run_pipeline(
        self,
        dataset_id: str,
        dko: DatasetKnowledgeObject,
        df: pd.DataFrame,
    ) -> None:
        """Run the full investigation pipeline. Called in a background thread."""
        state = self._active[dataset_id]
        fingerprint = dko.fingerprint

        try:
            self._emit(state, "investigation", {"status": "starting"})

            # ── Step 1: Check cache ───────────────────────────────────────
            cached = investigation_cache.get_report(fingerprint)
            if cached:
                self._emit(state, "investigation_done", cached)
                state["report"] = cached
                return

            # ── Step 2: Build dataset summary ─────────────────────────────
            self._emit(state, "investigation", {"status": "building_summary"})
            summary = dataset_summary_builder.build(dko)

            # ── Step 3: Generate candidates ───────────────────────────────
            self._emit(state, "investigation", {"status": "generating_candidates"})
            candidates = candidate_generator.generate(dko)
            logger.info(
                "[InvestigationEngine] %d candidates generated for %s",
                len(candidates), dataset_id,
            )

            if not candidates:
                report = InvestigationReport.failed_report(
                    dataset_id, fingerprint, dko.dataset_name,
                    "No analysis candidates could be generated"
                )
                self._finalize(state, report, fingerprint)
                return

            # ── Step 4: Compute budget ────────────────────────────────────
            budget = candidate_filter.compute_budget(dko)
            self._emit(state, "investigation", {
                "status": "filtering_candidates",
                "total_candidates": len(candidates),
                "budget": budget.to_dict(),
            })

            # ── Step 5: Filter + rank + diversity-select ──────────────────
            ranked = candidate_filter.filter_and_rank(candidates, dko, budget)
            logger.info(
                "[InvestigationEngine] %d candidates after filter → %d selected",
                len(candidates), len(ranked),
            )

            if not ranked:
                report = InvestigationReport.failed_report(
                    dataset_id, fingerprint, dko.dataset_name,
                    "All candidates were filtered out"
                )
                self._finalize(state, report, fingerprint)
                return

            # ── Step 6: LLM Investigation Planner ─────────────────────────
            self._emit(state, "investigation", {"status": "planning"})
            plan = investigation_planner.plan(summary, ranked, budget, fingerprint)

            if not plan:
                report = InvestigationReport.failed_report(
                    dataset_id, fingerprint, dko.dataset_name,
                    "Investigation planner failed to produce a plan"
                )
                self._finalize(state, report, fingerprint)
                return

            self._emit(state, "investigation", {
                "status": "executing",
                "planned_investigations": len(plan.investigations),
                "complexity_tier": budget.complexity_tier,
            })

            # ── Step 7: Execute investigations ────────────────────────────
            candidates_dict = {c.candidate_id: c for c in ranked}
            results = autonomous_executor.execute_plan(
                plan, candidates_dict, df, dko, budget
            )

            # ── Step 8: Validate results ──────────────────────────────────
            validated_results: List[InvestigationResult] = []
            for result in results:
                validated = result_validator.validate(result)
                validated_results.append(validated)

                # Emit progressive finding events
                if validated.status == "success":
                    self._emit(state, "finding_ready", {
                        "candidate_id": validated.candidate_id,
                        "analysis_type": validated.analysis_type.value,
                        "columns": validated.columns,
                        "status": "success",
                    })

            successful = [r for r in validated_results if r.status == "success"]
            failed = [r for r in validated_results if r.status == "failed"]
            logger.info(
                "[InvestigationEngine] Execution: %d success, %d failed",
                len(successful), len(failed),
            )

            # ── Step 9: Interpret results (LLM #2) ───────────────────────
            self._emit(state, "investigation", {"status": "interpreting"})
            dataset_context = {
                "name": dko.dataset_name,
                "domain": summary.get("dataset", {}).get("domain", "general"),
            }

            # Lazy import to avoid circular deps at module load
            from autonomous_analysis.interpretation_engine import interpretation_engine

            for result in successful:
                try:
                    interpretation = interpretation_engine.interpret(result, dataset_context)
                    result.interpretation = interpretation
                except Exception as e:
                    logger.warning(
                        "[InvestigationEngine] Interpretation failed for %s: %s",
                        result.candidate_id, e,
                    )
                    result.interpretation = (
                        f"Analysis of {', '.join(result.columns)} "
                        f"({result.analysis_type.value}) completed."
                    )

            # ── Step 10: Synthesize cross-finding insights ────────────────
            self._emit(state, "investigation", {"status": "synthesizing"})
            synthesis_text = ""
            synthesis_insights = []

            if len(successful) >= 3:
                try:
                    from autonomous_analysis.insight_synthesizer import insight_synthesizer
                    synthesis_text, synthesis_insights = insight_synthesizer.synthesize(
                        successful, dataset_context
                    )
                except Exception as e:
                    logger.warning("[InvestigationEngine] Synthesis failed: %s", e)

            # ── Step 11: Build presentation ───────────────────────────────
            self._emit(state, "investigation", {"status": "building_presentation"})
            from autonomous_analysis.presentation_builder import presentation_builder

            section_groups = presentation_builder.build(
                successful, synthesis_insights, dataset_context
            )

            # ── Step 12: Assemble report ──────────────────────────────────
            report = InvestigationReport(
                dataset_id=dataset_id,
                dataset_fingerprint=fingerprint,
                dataset_name=dko.dataset_name,
                status="complete" if successful else "partial",
                section_groups=section_groups,
                synthesis_text=synthesis_text,
                total_investigations=len(validated_results),
                successful_investigations=len(successful),
                failed_investigations=len(failed),
                complexity_tier=budget.complexity_tier,
                generated_at=datetime.now(timezone.utc).isoformat(),
                llm_planner_model=plan.llm_model,
            )

            self._finalize(state, report, fingerprint)

        except Exception as e:
            logger.error(
                "[InvestigationEngine] Pipeline failed for %s: %s",
                dataset_id, e, exc_info=True,
            )
            report = InvestigationReport.failed_report(
                dataset_id,
                dko.fingerprint,
                dko.dataset_name,
                f"Investigation pipeline error: {str(e)}",
            )
            self._finalize(state, report, dko.fingerprint)

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _emit(self, state: dict, event_type: str, data: dict) -> None:
        """Emit an event and wake all waiting SSE consumers."""
        event = InvestigationEvent(event_type, data)
        state["events"].append(event)
        for waiter in state.get("waiters", []):
            waiter.set()
        state["waiters"] = []

    def _finalize(
        self,
        state: dict,
        report: InvestigationReport,
        fingerprint: str,
    ) -> None:
        """Finish the investigation: cache, emit done, mark not running."""
        report_dict = report.to_dict()
        state["report"] = report_dict

        # Cache
        investigation_cache.save_report(fingerprint, report_dict)

        # Emit done event
        self._emit(state, "investigation_done", report_dict)

        # Mark complete
        state["running"] = False

        logger.info(
            "[InvestigationEngine] Investigation complete: %d/%d successful, tier=%s",
            report.successful_investigations,
            report.total_investigations,
            report.complexity_tier,
        )

    def _get_fingerprint(self, dataset_id: str) -> Optional[str]:
        """Try to get fingerprint from active state or registry."""
        state = self._active.get(dataset_id)
        if state and state.get("report"):
            return state["report"].get("dataset_fingerprint")
        try:
            from datasets.registry import dataset_registry
            entry = dataset_registry.get_by_id(dataset_id)
            if entry and hasattr(entry, "fingerprint"):
                return entry.fingerprint
        except Exception:
            pass
        return dataset_id  # fallback: use dataset_id as key


# Module-level singleton
autonomous_investigation_engine = AutonomousInvestigationEngine()

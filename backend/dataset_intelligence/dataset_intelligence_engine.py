"""
Dataset Intelligence Engine — Main Orchestrator

This is the top-level entry point for the Dataset Intelligence Engine.
It orchestrates all 11 stages in sequence, managing data flow between them.

Usage:
    from dataset_intelligence import DatasetIntelligenceEngine

    engine = DatasetIntelligenceEngine()
    dko = engine.analyze(df, dataset_name="sales_data.csv")

The returned DatasetKnowledgeObject is the complete intelligence profile
of the dataset, ready to be consumed by all Plexis subsystems.

Performance:
  - Stages 1-9 are deterministic Python (fast, <5s for most datasets)
  - Stage 10 assembles the DKO (instantaneous)
  - Stage 11 makes one LLM call (typically 2-5s)
  - Results are cached by schema fingerprint (subsequent calls are instant)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

from .cache_manager import cache_manager
from .capability_detector import capability_detector
from .dataset_memory_builder import dataset_memory_builder
from .domain_detector import domain_detector
from .insight_engine import insight_engine
from .knowledge_synthesizer import knowledge_synthesizer
from .presentation_engine import presentation_engine
from .models_v2 import DatasetKnowledgeObject
from .question_predictor import question_predictor
from .quality_intelligence import quality_intelligence_stage
from .relationship_intelligence import relationship_intelligence_stage
from .schema_intelligence import schema_intelligence_stage
from .semantic_intelligence import semantic_intelligence_stage
from .statistical_intelligence import statistical_intelligence_stage
from .utils import compute_schema_fingerprint

logger = logging.getLogger(__name__)


class DatasetIntelligenceEngine:
    """
    The Dataset Intelligence Engine.

    Runs a 11-stage pipeline that transforms a raw DataFrame into
    a fully structured DatasetKnowledgeObject (DKO).

    The DKO is the single, authoritative intelligence object about the dataset.
    Every Plexis subsystem should consume this object instead of re-analyzing the data.

    Pipeline stages:
      1. Schema Intelligence        — Column type classification
      2. Statistical Intelligence   — Deep statistical profiling
      3. Quality Intelligence       — Data quality assessment
      4. Relationship Intelligence  — Correlation and relationship detection
      5. Semantic Intelligence      — Business concept mapping
      6. Domain Detection           — Business domain inference
      7. Capability Detection       — Supported analysis types
      8. Question Prediction        — Likely user questions
      9. Insight Engine             — Prioritized human-readable insights
      10. Knowledge Synthesis       — DKO assembly
      11. LLM Presentation          — Natural language presentation generation
    """

    def __init__(self, skip_presentation: bool = False):
        """
        Args:
            skip_presentation: If True, skips Stage 11 (useful for testing/dev).
                               The DKO will still be complete but will use the
                               deterministic fallback presentation.
        """
        self.skip_presentation = skip_presentation

    def analyze(
        self,
        df: pd.DataFrame,
        dataset_name: str,
        use_cache: bool = True,
        skip_presentation: bool = False,
    ) -> DatasetKnowledgeObject:
        """
        Run the full Dataset Intelligence pipeline on the provided DataFrame.

        Args:
            df: The uploaded dataset as a pandas DataFrame.
            dataset_name: The filename or identifier of the dataset.
            use_cache: Whether to check/populate the DKO cache.
                       Set to False to force a fresh analysis.
            skip_presentation: If True, skips Stage 11 (LLM presentation).
                               Used by the upload endpoint when streaming
                               Stage 11 separately via SSE.

        Returns:
            A complete DatasetKnowledgeObject.
        """
        start_time = time.time()

        # Compute schema fingerprint (used as cache key)
        fingerprint = compute_schema_fingerprint(df)
        logger.info(
            f"DatasetIntelligenceEngine: starting analysis for '{dataset_name}' "
            f"(fingerprint={fingerprint}, rows={len(df):,}, cols={len(df.columns)})"
        )

        # --- Cache Check ---
        if use_cache:
            cached_dko = cache_manager.get(fingerprint)
            if cached_dko is not None:
                elapsed = time.time() - start_time
                logger.info(
                    f"DatasetIntelligenceEngine: cache hit for '{dataset_name}' "
                    f"(returned in {elapsed:.3f}s)"
                )
                return cached_dko

        # --- Stage 1: Schema Intelligence ---
        t = time.time()
        schemas = schema_intelligence_stage.analyze(df)
        logger.debug(f"Stage 1 (Schema): {time.time() - t:.2f}s")

        # --- Stage 2: Statistical Intelligence ---
        t = time.time()
        column_stats = statistical_intelligence_stage.analyze(df, schemas)
        logger.debug(f"Stage 2 (Statistics): {time.time() - t:.2f}s")

        # --- Stage 3: Quality Intelligence ---
        t = time.time()
        quality = quality_intelligence_stage.analyze(df, schemas, column_stats)
        logger.debug(f"Stage 3 (Quality): {time.time() - t:.2f}s")

        # --- Stage 4: Relationship Intelligence ---
        t = time.time()
        relationships = relationship_intelligence_stage.analyze(df, schemas, column_stats)
        logger.debug(f"Stage 4 (Relationships): {time.time() - t:.2f}s")

        # --- Stage 5: Semantic Intelligence ---
        t = time.time()
        semantics = semantic_intelligence_stage.analyze(schemas)
        logger.debug(f"Stage 5 (Semantics): {time.time() - t:.2f}s")

        # --- Stage 6: Domain Detection ---
        t = time.time()
        domain = domain_detector.detect(dataset_name, semantics)
        logger.debug(f"Stage 6 (Domain): {time.time() - t:.2f}s")

        # --- Stage 7: Capability Detection ---
        t = time.time()
        capabilities = capability_detector.detect(semantics)
        logger.debug(f"Stage 7 (Capabilities): {time.time() - t:.2f}s")

        # --- Stage 8: Question Prediction ---
        t = time.time()
        predicted_questions = question_predictor.predict(semantics, capabilities, domain)
        logger.debug(f"Stage 8 (Questions): {time.time() - t:.2f}s")

        # --- Stage 9: Insight Engine ---
        t = time.time()
        insights = insight_engine.generate(
            schemas=schemas,
            column_stats=column_stats,
            quality=quality,
            relationships=relationships,
            semantics=semantics,
            domain=domain,
            capabilities=capabilities,
        )
        logger.debug(f"Stage 9 (Insights): {time.time() - t:.2f}s")

        # --- Stage 10: Knowledge Synthesis ---
        t = time.time()
        dko = knowledge_synthesizer.synthesize(
            df=df,
            dataset_name=dataset_name,
            fingerprint=fingerprint,
            schemas=schemas,
            column_stats=column_stats,
            quality=quality,
            relationships=relationships,
            semantics=semantics,
            domain=domain,
            capabilities=capabilities,
            predicted_questions=predicted_questions,
            insights=insights,
        )
        logger.debug(f"Stage 10 (Synthesis): {time.time() - t:.2f}s")

        # --- Stage 11: Dataset Presentation Engine ---
        _skip = self.skip_presentation or skip_presentation
        if not _skip:
            t = time.time()
            # present() accumulates the full stream into a DatasetPresentation object
            # so the DKO can be cached with the complete text.
            pres = presentation_engine.present(dko)
            dko = knowledge_synthesizer.finalize(dko, pres)
            logger.debug(f"Stage 11 (Presentation): {time.time() - t:.2f}s")
        else:
            logger.info("DatasetIntelligenceEngine: skipping Stage 11 presentation")

        # --- Cache Save ---
        if use_cache:
            cache_manager.save(dko)

        total_time = time.time() - start_time
        logger.info(
            f"DatasetIntelligenceEngine: analysis complete for '{dataset_name}' in {total_time:.2f}s | "
            f"domain={dko.get_dataset_identity().probable_purpose} | "
            f"quality={dko.quality_report.overall_score if dko.quality_report else 0:.0f}/100 | "
            f"readiness={dko.quality_report.analysis_readiness if dko.quality_report else 'unknown'} | "
            f"insights={len(dko.insights)} | "
            f"questions={len(dko.predicted_questions)}"
        )
        return dko

    def present_stream(self, dko: DatasetKnowledgeObject):
        """
        Stream the dataset presentation as Markdown text chunks.
        Used directly by the SSE upload endpoint.
        Yields plain string chunks from the LLM without SSE formatting.
        """
        yield from presentation_engine.present_stream(dko)

    def get_context_summary(self, dko: DatasetKnowledgeObject) -> str:
        """Get the LLM-ready context summary for this DKO."""
        return dataset_memory_builder.build_context_summary(dko)

    def get_planner_context(self, dko: DatasetKnowledgeObject) -> dict:
        """Get the structured planner context dict for this DKO."""
        return dataset_memory_builder.build_planner_context(dko)

    def get_frontend_payload(self, dko: DatasetKnowledgeObject) -> dict:
        """Get the complete frontend Intelligence Dashboard payload."""
        return dataset_memory_builder.build_frontend_payload(dko)


# Module-level singleton
dataset_intelligence_engine = DatasetIntelligenceEngine()

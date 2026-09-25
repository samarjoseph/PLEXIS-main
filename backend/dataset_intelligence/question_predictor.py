"""
Dataset Intelligence Engine — Stage 8: Question Predictor

Predicts the top questions a user is likely to ask about this dataset
based on its semantic structure, capabilities, and domain.

These predictions are surfaced in the frontend and used by the Planner
to provide instant, relevant suggestions without requiring the user
to think of them first.

All prediction is deterministic — no LLM calls.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .models import (
    AnalysisCapability, CapabilitySet, DataDomain, DomainResult,
    PredictedQuestion, SemanticMap
)

logger = logging.getLogger(__name__)


class QuestionPredictor:
    """
    Stage 8 — Question Predictor

    Generates a ranked list of predicted user questions using:
      - Capability signals (what analyses are possible)
      - Semantic signals (which columns are metrics, dimensions, time)
      - Domain signals (finance questions differ from education questions)
      - Primary metric and primary date (highest-value targets for questions)

    Questions are deduplicated and ranked by estimated user interest.
    """

    MAX_QUESTIONS = 10

    def predict(
        self,
        semantics: SemanticMap,
        capabilities: CapabilitySet,
        domain: DomainResult,
    ) -> List[PredictedQuestion]:
        """
        Generate predicted user questions.

        Args:
            semantics: Stage 5 SemanticMap
            capabilities: Stage 7 CapabilitySet
            domain: Stage 6 DomainResult

        Returns:
            A list of PredictedQuestion objects, ranked by confidence.
        """
        logger.info("QuestionPredictor: generating predicted questions")
        questions: List[PredictedQuestion] = []

        metrics = semantics.metrics
        dimensions = semantics.dimensions
        time_cols = semantics.time_columns

        # Primary metric and primary date (highest priority targets)
        primary_metric = next(
            (n for n, c in semantics.columns.items() if c.is_primary_metric), None
        ) or (metrics[0] if metrics else None)

        primary_date = next(
            (n for n, c in semantics.columns.items() if c.is_primary_date), None
        ) or (time_cols[0] if time_cols else None)

        primary_dim = dimensions[0] if dimensions else None

        # --- Ranking Questions ---
        if primary_metric and capabilities.supports(AnalysisCapability.RANKING):
            questions.append(PredictedQuestion(
                question=f"What are the top 10 records by {primary_metric}?",
                category="ranking",
                confidence=0.95,
                relevant_columns=[primary_metric],
                suggested_chart="bar",
            ))
            questions.append(PredictedQuestion(
                question=f"What is the lowest {primary_metric} in the dataset?",
                category="ranking",
                confidence=0.80,
                relevant_columns=[primary_metric],
                suggested_chart="bar",
            ))

        # --- Aggregation Questions ---
        if primary_metric and capabilities.supports(AnalysisCapability.AGGREGATION):
            questions.append(PredictedQuestion(
                question=f"What is the total {primary_metric}?",
                category="aggregation",
                confidence=0.90,
                relevant_columns=[primary_metric],
                suggested_chart=None,
            ))
            questions.append(PredictedQuestion(
                question=f"What is the average {primary_metric}?",
                category="aggregation",
                confidence=0.85,
                relevant_columns=[primary_metric],
                suggested_chart=None,
            ))

        # --- Comparison Questions ---
        if primary_metric and primary_dim and capabilities.supports(AnalysisCapability.COMPARISON):
            questions.append(PredictedQuestion(
                question=f"Compare {primary_metric} by {primary_dim}",
                category="comparison",
                confidence=0.90,
                relevant_columns=[primary_metric, primary_dim],
                suggested_chart="bar",
            ))
            if len(dimensions) > 1:
                questions.append(PredictedQuestion(
                    question=f"Which {primary_dim} has the highest {primary_metric}?",
                    category="comparison",
                    confidence=0.88,
                    relevant_columns=[primary_metric, primary_dim],
                    suggested_chart="bar",
                ))

        # --- Time Series Questions ---
        if primary_metric and primary_date and capabilities.supports(AnalysisCapability.TIME_SERIES):
            questions.append(PredictedQuestion(
                question=f"Show {primary_metric} over time",
                category="trend",
                confidence=0.92,
                relevant_columns=[primary_metric, primary_date],
                suggested_chart="line",
            ))
            questions.append(PredictedQuestion(
                question=f"What is the monthly trend of {primary_metric}?",
                category="trend",
                confidence=0.82,
                relevant_columns=[primary_metric, primary_date],
                suggested_chart="line",
            ))

        # --- Distribution Questions ---
        if primary_metric and capabilities.supports(AnalysisCapability.DISTRIBUTION):
            questions.append(PredictedQuestion(
                question=f"What is the distribution of {primary_metric}?",
                category="distribution",
                confidence=0.75,
                relevant_columns=[primary_metric],
                suggested_chart="histogram",
            ))

        # --- Correlation Questions ---
        if len(metrics) >= 2 and capabilities.supports(AnalysisCapability.CORRELATION):
            questions.append(PredictedQuestion(
                question=f"Is there a correlation between {metrics[0]} and {metrics[1]}?",
                category="correlation",
                confidence=0.70,
                relevant_columns=metrics[:2],
                suggested_chart="scatter",
            ))

        # --- Domain-Specific Questions ---
        domain_questions = self._get_domain_questions(domain.domain, metrics, dimensions, time_cols, primary_metric, primary_dim, primary_date)
        questions.extend(domain_questions)

        # Sort by confidence and deduplicate
        questions = self._deduplicate(questions)
        questions.sort(key=lambda q: q.confidence, reverse=True)

        logger.info(f"QuestionPredictor: generated {len(questions[:self.MAX_QUESTIONS])} predicted questions")
        return questions[:self.MAX_QUESTIONS]

    def _get_domain_questions(
        self,
        domain: DataDomain,
        metrics: List[str],
        dimensions: List[str],
        time_cols: List[str],
        primary_metric: Optional[str],
        primary_dim: Optional[str],
        primary_date: Optional[str],
    ) -> List[PredictedQuestion]:
        """Generate domain-specific questions based on dataset type."""
        questions = []

        if domain == DataDomain.RETAIL_SALES:
            if primary_metric:
                questions.append(PredictedQuestion(
                    question="Which product category generates the most revenue?",
                    category="comparison",
                    confidence=0.85,
                    relevant_columns=metrics[:1] + dimensions[:1],
                    suggested_chart="bar",
                ))
            if primary_date:
                questions.append(PredictedQuestion(
                    question="What is the sales growth rate year over year?",
                    category="trend",
                    confidence=0.80,
                    relevant_columns=metrics[:1] + time_cols[:1],
                    suggested_chart="line",
                ))

        elif domain == DataDomain.HR:
            questions.append(PredictedQuestion(
                question="What is the average salary by department?",
                category="comparison",
                confidence=0.88,
                relevant_columns=metrics[:1] + dimensions[:1],
                suggested_chart="bar",
            ))
            questions.append(PredictedQuestion(
                question="Which department has the highest headcount?",
                category="ranking",
                confidence=0.82,
                relevant_columns=dimensions[:1],
                suggested_chart="bar",
            ))

        elif domain == DataDomain.EDUCATION:
            if primary_metric:
                questions.append(PredictedQuestion(
                    question=f"What is the average {primary_metric} by class?",
                    category="comparison",
                    confidence=0.88,
                    relevant_columns=[primary_metric] + dimensions[:1],
                    suggested_chart="bar",
                ))
            questions.append(PredictedQuestion(
                question="Who are the top 10 performing students?",
                category="ranking",
                confidence=0.86,
                relevant_columns=metrics[:1],
                suggested_chart="bar",
            ))

        elif domain == DataDomain.HEALTHCARE:
            if dimensions:
                questions.append(PredictedQuestion(
                    question="What is the patient distribution by diagnosis?",
                    category="distribution",
                    confidence=0.82,
                    relevant_columns=dimensions[:1],
                    suggested_chart="pie",
                ))

        elif domain == DataDomain.FINANCE:
            if primary_metric and primary_date:
                questions.append(PredictedQuestion(
                    question="What is the portfolio performance over time?",
                    category="trend",
                    confidence=0.84,
                    relevant_columns=[primary_metric, primary_date],
                    suggested_chart="line",
                ))

        return questions

    def _deduplicate(self, questions: List[PredictedQuestion]) -> List[PredictedQuestion]:
        """Remove near-duplicate questions."""
        seen_questions = set()
        unique = []
        for q in questions:
            key = q.question.lower().strip()
            if key not in seen_questions:
                seen_questions.add(key)
                unique.append(q)
        return unique


question_predictor = QuestionPredictor()

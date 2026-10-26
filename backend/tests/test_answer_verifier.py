"""
Unit and regression tests for AnswerVerifier (Answer Verification Engine).

Tests all required failure modes, edge cases, semantic bounds, and presentation recovery:
1. Incorrect mean
2. Incorrect median
3. Swapped group labels
4. Missing required metric
5. Incorrect percentage
6. Valid rounded numbers (precision tolerance)
7. Harmless stylistic differences
8. Unsupported causal claims
9. Wrong dataset version
10. False transformation/mutation claims
11. Missing evidence / indeterminate state
12. Bounded repair from authoritative deterministic narrative
13. Deliberately altered LLM presentation error (independent of execution correctness)
"""

import pytest
from core.context import ExecutionContext
from engines.base import EngineResult
from verifier.answer_verifier import (
    AnswerVerifier,
    AnswerVerificationResult,
    VerificationStatus,
    VerificationFinding,
    answer_verifier,
)


@pytest.fixture
def sample_facts():
    return {
        "computed_answer": "For churned customers, the mean tenure is 17.98 months with a median of 10.0 months (IQR: 29.0). For non-churned customers, the mean tenure is 37.57 months with a median of 38.0 months (IQR: 46.0). The absolute difference in medians is 28.0 months.",
        "dataset_dimensions": {
            "row_count": 7043,
            "column_count": 21,
            "total_cells": 147903,
            "total_missing_cells": 11,
            "complete_cells": 147892,
            "duplicate_rows": 0,
        },
        "operations": [
            {
                "operation": "binary_indicator_comparison",
                "column": "tenure",
                "details": {
                    "churned": {
                        "count": 1869,
                        "mean": 17.98,
                        "median": 10.0,
                        "std": 19.53,
                        "q1": 2.0,
                        "q3": 31.0,
                        "iqr": 29.0,
                        "min": 1.0,
                        "max": 72.0,
                    },
                    "non-churned": {
                        "count": 5174,
                        "mean": 37.57,
                        "median": 38.0,
                        "std": 24.11,
                        "q1": 15.0,
                        "q3": 61.0,
                        "iqr": 46.0,
                        "min": 0.0,
                        "max": 72.0,
                    },
                    "abs_difference_in_means": 19.59,
                    "abs_difference_in_medians": 28.0,
                },
                "summary": "Mean tenure is 17.98 vs 37.57.",
            }
        ],
    }


class TestAnswerVerifierFidelity:
    """Tests numerical fidelity and tolerance checking."""

    def test_detects_incorrect_mean(self, sample_facts):
        verifier = AnswerVerifier()
        # Authoritative means are 17.98 and 37.57. Claiming 52.3 is a hallucination.
        answer = "The mean tenure for churned customers was 52.3 months, while non-churned was 37.57 months."
        res = verifier.verify("Compare tenure mean", answer, sample_facts, auto_repair=False)
        assert res.status == VerificationStatus.FAIL
        assert any("52.3" in f.message for f in res.findings)

    def test_detects_incorrect_median(self, sample_facts):
        verifier = AnswerVerifier()
        # Authoritative medians are 10.0 and 38.0. Claiming 25.0 is unsupported.
        answer = "The median tenure for churned customers was 25.0 months and non-churned was 38.0 months."
        res = verifier.verify("Compare median tenure", answer, sample_facts, auto_repair=False)
        assert res.status == VerificationStatus.FAIL
        assert any("25" in f.message for f in res.findings)

    def test_detects_incorrect_percentage(self):
        verifier = AnswerVerifier()
        facts = {
            "metrics": {"churn_rate": 0.265, "churn_pct": 26.5},
            "operations": [{"operation": "rate", "value": 0.265}],
        }
        # True rate is 26.5%. Hallucinating 58.4%
        answer = "The observed churn rate in the customer cohort is 58.4%."
        res = verifier.verify("What is the churn rate?", answer, facts)
        assert res.status == VerificationStatus.FAIL
        assert any("58.4%" in f.message for f in res.findings)

    def test_accepts_valid_rounded_number(self, sample_facts):
        verifier = AnswerVerifier()
        # 17.98 rounded to 18.0 or 18; 37.57 rounded to 37.6
        answer = "Churned customers had an average tenure of 18.0 months, while retained customers averaged 37.6 months."
        res = verifier.verify("Compare tenure", answer, sample_facts)
        assert res.status == VerificationStatus.PASS

    def test_accepts_harmless_stylistic_differences(self, sample_facts):
        verifier = AnswerVerifier()
        answer = (
            "An analytical review of the dataset indicates that customers who departed had an average "
            "tenure of 17.98 months (median: 10.0 months). Conversely, active subscribers exhibited a "
            "notably longer average tenure of 37.57 months (median: 38.0 months)."
        )
        res = verifier.verify("Compare tenure", answer, sample_facts)
        assert res.status == VerificationStatus.PASS


class TestSemanticAndRequiredContent:
    """Tests group label mapping, required metric checklists, and causal guards."""

    def test_detects_swapped_group_labels(self, sample_facts):
        verifier = AnswerVerifier()
        # Swapping: churned (18.0) is attributed to 37.6 and non-churned to 18.0
        answer = "Churned customers had an average tenure of 37.6 months, while non-churned had 18.0 months."
        res = verifier.verify("Compare tenure across groups", answer, sample_facts, auto_repair=False)
        assert res.status == VerificationStatus.FAIL
        assert any(f.category == "semantic_label" for f in res.findings)

    def test_detects_missing_required_metric(self, sample_facts):
        verifier = AnswerVerifier()
        # Query asks for mean, median, and interquartile range. Answer provides mean and median but drops IQR.
        query = "Report mean, median, and interquartile range for tenure across cohorts."
        answer = "The mean tenure is 17.98 months and the median is 10.0 months for churned customers."
        res = verifier.verify(query, answer, sample_facts, auto_repair=False)
        # Missing required metric is repairable
        assert any(f.category == "required_content" and f.field_or_metric == "iqr" for f in res.findings)

    def test_detects_unsupported_causal_claim(self):
        verifier = AnswerVerifier()
        facts = {
            "metrics": {"correlation": 0.42},
            "operations": [{"operation": "correlation", "value": 0.42}],
        }
        query = "What is the correlation between rainfall and delays?"
        answer = "The correlation coefficient is 0.42, which proves that rainfall causes flight delays."
        res = verifier.verify(query, answer, facts)
        assert any(f.category == "causality" for f in res.findings)

    def test_detects_wrong_dataset_version(self):
        verifier = AnswerVerifier()
        ctx = ExecutionContext(message="Test query")
        ctx.dataset_id = "ds_123"
        ctx.dataset_version = 1

        facts = {"metrics": {"row_count": 100}}
        answer = "Based on dataset version 4, there are 100 rows."
        res = verifier.verify("How many rows?", answer, facts, context=ctx)
        assert res.status == VerificationStatus.FAIL
        assert any(f.category == "provenance" for f in res.findings)

    def test_detects_false_mutation_claim(self):
        verifier = AnswerVerifier()
        ctx = ExecutionContext(message="Filter test")
        ctx.intent = "analysis"
        facts = {"metrics": {"filtered_count": 50}}
        answer = "I have deleted 50 rows from the dataset permanently."
        res = verifier.verify("Show filtered rows", answer, facts, context=ctx)
        assert res.status == VerificationStatus.FAIL
        assert any("mutation" in f.message.lower() for f in res.findings)

    def test_indeterminate_when_facts_missing(self):
        verifier = AnswerVerifier()
        # Empty facts dictionary for an analytical query
        res = verifier.verify("What is the average tenure?", "The average is 25.", facts={})
        assert res.status == VerificationStatus.INDETERMINATE


class TestBoundedRepairAndComposerIntegration:
    """Tests automatic bounded repair and ResponseComposer integration."""

    def test_repaired_answer_from_deterministic_narrative(self, sample_facts):
        verifier = AnswerVerifier()
        # Flawed draft containing a hallucinated number (99.9)
        answer = "The mean tenure for churned customers was 99.9 months."
        res = verifier.verify("Compare tenure", answer, sample_facts)
        # Because sample_facts['computed_answer'] is valid, verifier repairs it
        assert res.status == VerificationStatus.PASS
        assert res.is_repaired is True
        assert res.repaired_answer == sample_facts["computed_answer"]

    def test_deliberately_altered_llm_presentation_error(self, monkeypatch, sample_facts):
        """
        Demonstrate that the verification layer catches presentation errors
        independently of execution correctness when LLM output is altered.
        """
        from core.composer import ResponseComposer
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class MockLLMResponse:
            text: str
            provider: str = "mock_corrupter"
            success: bool = True
            error: Optional[str] = None

        class MockCorruptingProvider:
            def generate(self, req):
                # Deliberately outputting a hallucinated mean (999.0)
                return MockLLMResponse(
                    text="The mean tenure was 999.0 months for churned customers.",
                )

        composer = ResponseComposer()
        ctx = ExecutionContext(message="Compare tenure for churned and non-churned customers")
        ctx.intent = "analysis"

        engine_res = EngineResult(
            answer="",
            facts=sample_facts,
            should_compose=True,
        )

        monkeypatch.setattr("core.composer.provider_engine", MockCorruptingProvider())
        final_res = composer.compose(ctx, engine_res)

        # Verifier must catch the presentation corruption (999.0) and restore the verified narrative!
        assert "999.0" not in final_res.answer
        assert "17.98" in final_res.answer
        assert "37.57" in final_res.answer
        assert final_res.metadata.get("verification", {}).get("status") == "PASS"

"""
Fault-Injection and Hard Delivery Gate Tests for AnswerVerifier and ResponseComposer.

Verifies:
1. When an LLM answer hallucinates or corrupts a numerical claim, AnswerVerifier detects FAIL.
2. ResponseComposer's delivery gate intercepts the FAIL and replaces the corrupted draft with authoritative factual fallback.
3. The response metadata and evidence dictionary strictly enforce verified=False.
4. Correct answers with dictionary facts (from describe_column, frequency, etc.) pass verification.
"""

import pytest
from unittest.mock import MagicMock, patch

from core.context import ExecutionContext
from engines.base import EngineResult
from verifier.answer_verifier import answer_verifier, VerificationStatus
from core.composer import response_composer


def test_dict_evidence_ingestion_no_false_alarm():
    """Authoritative dictionary facts (e.g. describe_column) must be ingested properly."""
    facts = {
        "operations": [
            {
                "operation": "describe_column",
                "column": "total_amount",
                "value": {
                    "mean": 23722.77,
                    "median": 20456.0,
                    "min": 100.0,
                    "max": 99999.0,
                },
            }
        ],
        "computed_answer": "Mean is 23,722.77 and median is 20,456.00.",
    }
    answer = "The mean total amount is 23,722.77 and the median is 20,456.00 with minimum 100.00."

    res = answer_verifier.verify(
        query="What is the mean and median total amount?",
        answer=answer,
        facts=facts,
    )

    assert res.status == VerificationStatus.PASS
    assert len(res.verified_claims) >= 2


def test_fault_injection_hallucinated_number():
    """When the answer hallucinates a number not in facts, it must FAIL (auto_repair=False) and repair (auto_repair=True)."""
    facts = {
        "operations": [
            {
                "operation": "mean",
                "column": "total_amount",
                "value": 23722.77,
            }
        ],
        "computed_answer": "The average total amount is 23,722.77.",
    }
    # Corrupted / hallucinated number 49,850.50
    corrupted_answer = "The average total amount is 49,850.50 across all customers."

    # Raw verification without auto-repair MUST flag FAIL
    res = answer_verifier.verify(
        query="What is the average total amount?",
        answer=corrupted_answer,
        facts=facts,
        auto_repair=False,
    )

    assert res.status == VerificationStatus.FAIL
    assert any("49,850.5" in f.message or "Unsupported numerical claim" in f.message for f in res.findings)

    # Verification with auto-repair MUST catch the corruption and repair to authoritative value
    res_repaired = answer_verifier.verify(
        query="What is the average total amount?",
        answer=corrupted_answer,
        facts=facts,
        auto_repair=True,
    )
    assert res_repaired.is_repaired is True
    assert "23,722.77" in res_repaired.repaired_answer
    assert "49,850.50" not in res_repaired.repaired_answer


def test_response_composer_hard_delivery_gate_blocks_corrupted_answer():
    """ResponseComposer MUST block corrupted LLM drafts from reaching the user."""
    ctx = ExecutionContext(request_id="test_req", message="What is the average total amount?")
    ctx.intent = "analysis"

    facts = {
        "operations": [
            {
                "operation": "mean",
                "column": "total_amount",
                "value": 23722.77,
            }
        ],
        "computed_answer": "The average total amount is 23,722.77.",
    }

    evidence = MagicMock()
    evidence.verified = True
    evidence.to_dict.return_value = {"verified": True, "value": 23722.77}

    engine_res = EngineResult(
        answer="Draft",
        facts=facts,
        evidence=evidence,
        should_compose=True,
    )

    # Mock provider_engine to simulate an LLM hallucinating 99,999.99
    with patch("core.composer.provider_engine.generate") as mock_gen:
        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.text = "The calculated average total amount is 99,999.99 dollars."
        mock_resp.provider = "mock_hallucinating_llm"
        mock_gen.return_value = mock_resp

        final_res = response_composer.compose(ctx, engine_res)

        # Assert delivery gate intercepted the hallucination:
        # Corrupted answer '99,999.99' must NOT be in final_res.answer!
        assert "99,999.99" not in final_res.answer
        # Authoritative computed answer must be used instead
        assert "23,722.77" in final_res.answer
        assert final_res.metadata["verification"]["is_repaired"] is True


def test_response_composer_delivery_gate_unverified_flag_propagation():
    """When no computed answer is available and LLM output is corrupted, delivery is blocked and verified=False."""
    ctx = ExecutionContext(request_id="test_req_2", message="What is the average total amount?")
    ctx.intent = "analysis"

    # Facts with NO computed narrative and no matching values
    facts = {
        "operations": [],
    }

    evidence = {"verified": True, "value": 100.0}

    engine_res = EngineResult(
        answer="Draft",
        facts=facts,
        evidence=evidence,
        should_compose=True,
    )

    with patch("core.composer.provider_engine.generate") as mock_gen:
        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.text = "The total value is 5,432,100 units."
        mock_resp.provider = "mock_hallucinating_llm"
        mock_gen.return_value = mock_resp

        final_res = response_composer.compose(ctx, engine_res)

        # Assert delivery gate marked failure and flipped verified flag to False
        assert final_res.metadata["verification"]["status"] == "FAIL"
        assert final_res.evidence["verified"] is False
        assert "5,432,100" not in final_res.answer

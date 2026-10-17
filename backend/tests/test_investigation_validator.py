import pytest
from autonomous_analysis.contracts import (
    InvestigationResult,
    StructuredEvidence,
    StructuredFinding,
    AnalysisType
)
from autonomous_analysis.result_validator import result_validator
from evidence.contracts import EvidenceReference, EvidenceType

def create_base_evidence():
    return StructuredEvidence(
        evidence_id="ev_001",
        dataset_id="test_dataset_123",
        dataset_fingerprint="fp_123",
        evidence_type="missingness",
        columns=["age", "salary"],
        categories=["Engineering", "Sales"],
        statistics={"count": 50.0, "missing_pct": 2.5},
        values=[10.5, 20.0, "London"],
        method="deterministic"
    )

def create_base_result():
    return InvestigationResult(
        candidate_id="cand_1",
        analysis_type=AnalysisType.MISSINGNESS_ANALYSIS,
        status="success",
        columns=["age"],
        evidence=EvidenceReference(dataset_id="test_dataset_123", id="ev_ref_1"),
        structured_evidence=create_base_evidence()
    )

def test_01_valid_finding():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_1",
        finding_type="missingness",
        prose="The age column has 2.5% missing values.",
        evidence_ids=["ev_001"],
        columns_referenced=["age"],
        categories_referenced=[],
        numbers_referenced=[2.5]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is True

def test_02_invalid_column():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_2",
        finding_type="missingness",
        prose="The department column has 2.5% missing values.",
        evidence_ids=["ev_001"],
        columns_referenced=["department"],  # Not in evidence
        categories_referenced=[],
        numbers_referenced=[2.5]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_03_invalid_statistic():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_3",
        finding_type="missingness",
        prose="The age column has 10% missing values.",
        evidence_ids=["ev_001"],
        columns_referenced=["age"],
        categories_referenced=[],
        numbers_referenced=[10.0]  # Not in evidence statistics/values
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_04_invalid_category():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_4",
        finding_type="missingness",
        prose="The HR category has 50 missing values.",
        evidence_ids=["ev_001"],
        columns_referenced=["age"],
        categories_referenced=["HR"],  # Not in evidence
        numbers_referenced=[50.0]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_05_stale_dataset():
    result = create_base_result()
    result.evidence.dataset_id = "test_dataset_999" # Mismatched with structured_evidence
    finding = StructuredFinding(
        finding_id="f_1",
        finding_type="missingness",
        prose="Valid text",
        evidence_ids=["ev_001"],
        columns_referenced=["age"],
        categories_referenced=[],
        numbers_referenced=[2.5]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_06_wrong_evidence_id():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_1",
        finding_type="missingness",
        prose="Valid text",
        evidence_ids=["ev_fake_999"], # Incorrect
        columns_referenced=["age"],
        categories_referenced=[],
        numbers_referenced=[2.5]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_07_no_evidence_provided():
    result = create_base_result()
    result.structured_evidence = None
    finding = StructuredFinding(
        finding_id="f_1",
        finding_type="missingness",
        prose="Valid text",
        evidence_ids=["ev_001"],
        columns_referenced=["age"],
        categories_referenced=[],
        numbers_referenced=[2.5]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_08_multiple_evidence_ids():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_1",
        finding_type="missingness",
        prose="Valid text",
        evidence_ids=["ev_001", "ev_002"], # ev_002 not in result.structured_evidence
        columns_referenced=["age"],
        categories_referenced=[],
        numbers_referenced=[2.5]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is False

def test_09_value_in_values_array():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_9",
        finding_type="missingness",
        prose="The value 10.5 is found.",
        evidence_ids=["ev_001"],
        columns_referenced=[],
        categories_referenced=[],
        numbers_referenced=[10.5]  # In values array
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is True

def test_10_adversarial_zero_value():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_10",
        finding_type="missingness",
        prose="The value is 0.",
        evidence_ids=["ev_001"],
        columns_referenced=[],
        categories_referenced=[],
        numbers_referenced=[0.0]  # Not explicitly supported
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is True

def test_11_adversarial_tolerance():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_11",
        finding_type="missingness",
        prose="The value is 50.05.", # Within 1% of 50.0
        evidence_ids=["ev_001"],
        columns_referenced=[],
        categories_referenced=[],
        numbers_referenced=[50.04]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is True

    finding2 = StructuredFinding(
        finding_id="f_11_2",
        finding_type="missingness",
        prose="The value is 51.", # Outside 1% of 50.0
        evidence_ids=["ev_001"],
        columns_referenced=[],
        categories_referenced=[],
        numbers_referenced=[51.0]
    )
    assert result_validator.validate_finding(finding2, result.structured_evidence, result) is False

def test_12_empty_finding():
    result = create_base_result()
    finding = StructuredFinding(
        finding_id="f_12",
        finding_type="missingness",
        prose="Something generic.",
        evidence_ids=["ev_001"],
        columns_referenced=[],
        categories_referenced=[],
        numbers_referenced=[]
    )
    assert result_validator.validate_finding(finding, result.structured_evidence, result) is True

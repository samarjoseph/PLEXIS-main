"""
Comprehensive Test Suite for Generic Hypothetical Analysis Capability
Covers:
1. Executor execution vs independent Pandas reference across multiple operations, operators, and schemas.
2. Zero-row remaining subsets and 0-row exclusion subsets.
3. Dataframe immutability guarantee (verifying the source dataset is NEVER mutated).
4. End-to-end natural language pipeline (normalization -> routing -> planning -> execution -> verification -> narrative).
"""

import sys
import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock

# Ensure backend root is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from executor.pandas_executor import pandas_executor
from core.normalization import QueryNormalizer
from core.pipeline import ExecutionContext
from router.master_router import MasterRouter
from datasets.registry import dataset_registry, DatasetEntry
from planner.schema import AnalyticalPlan
from analytics.result import AnalyticalResult
from analytics.pipeline import analytics_pipeline


@pytest.fixture
def synthetic_df():
    """Generic synthetic multi-column dataset with numeric, binary, and categorical attributes."""
    np.random.seed(42)
    n = 200
    return pd.DataFrame({
        "emp_id": [f"E{i:03d}" for i in range(n)],
        "department": np.random.choice(["Engineering", "Sales", "Support", "Marketing"], size=n),
        "is_senior": np.random.choice([0, 1], size=n, p=[0.7, 0.3]),
        "performance_score": np.random.uniform(1.0, 5.0, size=n),
        "salary": np.random.uniform(40000, 150000, size=n),
        "overtime_hours": np.random.choice([0, 5, 10, 15, 20], size=n)
    })


@pytest.fixture
def retail_df():
    """Loads Sales_transactions_2022_2025.csv if available."""
    path = os.path.join(BASE_DIR, "storage", "uploads", "Sales_transactions_2022_2025.csv")
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


@pytest.fixture
def flight_df():
    """Loads india_flight_delay_model_input.csv if available."""
    path = r"c:\Users\samar\Downloads\archive (1)\india_flight_delay_model_input.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


# =============================================================================
# 1. INDEPENDENT PANDAS REFERENCE COMPARISON WITH NUMERICAL TOLERANCE
# =============================================================================

def _compute_pandas_reference(df: pd.DataFrame, target_col: str, metric: str,
                             cond_col: str, op: str, cond_val: any):
    """Independently computes expected value and counts using pure pandas slicing."""
    df_slice = df.copy()
    num_val = pd.to_numeric(pd.Series([cond_val]), errors="coerce").iloc[0]
    
    if pd.notna(num_val) and pd.api.types.is_numeric_dtype(df_slice[cond_col]):
        col_series = pd.to_numeric(df_slice[cond_col], errors="coerce")
        cmp_val = num_val
    else:
        col_series = df_slice[cond_col].astype(str).str.strip().str.lower()
        cmp_val = str(cond_val).strip().lower()

    if op == "==":
        mask = col_series == cmp_val
    elif op == "!=":
        mask = col_series != cmp_val
    elif op == ">":
        mask = col_series > cmp_val
    elif op == "<":
        mask = col_series < cmp_val
    elif op == ">=":
        mask = col_series >= cmp_val
    elif op == "<=":
        mask = col_series <= cmp_val
    else:
        mask = col_series == cmp_val

    affected_count = int(mask.sum())
    remaining_df = df_slice[~mask]
    remaining_count = len(remaining_df)

    if remaining_count == 0 or target_col not in remaining_df.columns:
        expected_val = 0.0 if metric == "sum" else (0 if metric in ("count", "row_count") else None)
    else:
        s = pd.to_numeric(remaining_df[target_col], errors="coerce").dropna()
        if s.empty:
            expected_val = 0.0 if metric == "sum" else (0 if metric in ("count", "row_count") else None)
        else:
            if metric == "mean":
                expected_val = float(s.mean())
            elif metric == "median":
                expected_val = float(s.median())
            elif metric == "sum":
                expected_val = float(s.sum())
            elif metric == "std":
                expected_val = float(s.std()) if len(s) > 1 else 0.0
            elif metric == "min":
                expected_val = float(s.min())
            elif metric == "max":
                expected_val = float(s.max())
            else:
                expected_val = len(remaining_df)

    return expected_val, affected_count, remaining_count


@pytest.mark.parametrize("cond_col,op,cond_val,target_col,metric", [
    ("is_senior", "==", 0, "salary", "mean"),
    ("is_senior", "==", 1, "salary", "median"),
    ("overtime_hours", ">", 10, "performance_score", "mean"),
    ("overtime_hours", "<=", 5, "salary", "sum"),
    ("performance_score", ">=", 4.0, "salary", "min"),
    ("department", "==", "Sales", "salary", "max"),
])
def test_synthetic_executor_matches_pandas_reference(synthetic_df, cond_col, op, cond_val, target_col, metric):
    """Verifies that pandas_executor._hypothetical exactly matches pure pandas reference on synthetic data."""
    params = {
        "action": "exclude",
        "column": target_col,
        "target_metric": metric,
        "exclude_condition": {
            "column": cond_col,
            "operator": op,
            "value": cond_val
        }
    }
    res = pandas_executor._hypothetical(synthetic_df, target_col, params)
    assert res.success is True
    val_dict = res.value

    exp_val, exp_affected, exp_remaining = _compute_pandas_reference(
        synthetic_df, target_col, metric, cond_col, op, cond_val
    )

    assert val_dict["affected_count"] == exp_affected, f"Affected count mismatch for {cond_col} {op} {cond_val}"
    assert val_dict["remaining_rows"] == exp_remaining, f"Remaining rows mismatch for {cond_col} {op} {cond_val}"

    if exp_val is None:
        assert val_dict["hypothetical_value"] is None
    else:
        assert np.isclose(val_dict["hypothetical_value"], exp_val, rtol=1e-5, atol=1e-5), \
            f"Numerical mismatch: got {val_dict['hypothetical_value']}, expected {exp_val}"


# =============================================================================
# 2. BOUNDARY TESTS: ZERO-ROW SUBSETS AND FULL-RETENTION SUBSETS
# =============================================================================

def test_zero_row_remaining_subset(synthetic_df):
    """When an exclusion condition filters out 100% of rows, remaining rows must be 0 and metric handles safely."""
    # Exclude salary >= 0 (matches all rows)
    params = {
        "action": "exclude",
        "column": "performance_score",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "salary",
            "operator": ">=",
            "value": 0
        }
    }
    res = pandas_executor._hypothetical(synthetic_df, "performance_score", params)
    assert res.success is True
    assert res.value["remaining_rows"] == 0
    assert res.value["affected_count"] == len(synthetic_df)
    assert res.value["hypothetical_value"] is None


def test_zero_rows_excluded_subset(synthetic_df):
    """When an exclusion condition matches 0 rows, all rows remain and original == hypothetical."""
    # Exclude salary < 0 (matches 0 rows)
    params = {
        "action": "exclude",
        "column": "salary",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "salary",
            "operator": "<",
            "value": 0
        }
    }
    res = pandas_executor._hypothetical(synthetic_df, "salary", params)
    assert res.success is True
    assert res.value["affected_count"] == 0
    assert res.value["remaining_rows"] == len(synthetic_df)
    assert np.isclose(res.value["hypothetical_value"], res.value["original_value"], rtol=1e-5, atol=1e-5)


# =============================================================================
# 3. DATAFRAME IMMUTABILITY GUARANTEE
# =============================================================================

def test_dataframe_immutability(synthetic_df):
    """Guarantees that executing hypothetical analysis NEVER mutates the input dataframe."""
    orig_hash = pd.util.hash_pandas_object(synthetic_df).sum()
    orig_shape = synthetic_df.shape
    orig_cols = list(synthetic_df.columns)
    orig_dtypes = list(synthetic_df.dtypes)

    params = {
        "action": "exclude",
        "column": "salary",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "department",
            "operator": "==",
            "value": "Sales"
        }
    }
    res = pandas_executor._hypothetical(synthetic_df, "salary", params)
    assert res.success is True

    # Assert source dataframe remains 100% unchanged
    after_hash = pd.util.hash_pandas_object(synthetic_df).sum()
    assert orig_hash == after_hash, "Source DataFrame was mutated by hypothetical analysis!"
    assert orig_shape == synthetic_df.shape, "Source DataFrame shape was altered!"
    assert orig_cols == list(synthetic_df.columns), "Source DataFrame columns were altered!"
    assert orig_dtypes == list(synthetic_df.dtypes), "Source DataFrame dtypes were altered!"


# =============================================================================
# 4. CROSS-DATASET EVALUATION (RETAIL & FLIGHT)
# =============================================================================

def test_retail_dataset_hypothetical(retail_df):
    """Tests hypothetical analysis on retail transactions schema (Sales_transactions_2022_2025.csv)."""
    if retail_df is None:
        pytest.skip("Retail dataset not found on disk.")

    # Exclude Return_Flag == 'Yes', calculate average Sales_Amount
    params = {
        "action": "exclude",
        "column": "Sales_Amount",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "Return_Flag",
            "operator": "==",
            "value": "Yes"
        }
    }
    res = pandas_executor._hypothetical(retail_df, "Sales_Amount", params)
    assert res.success is True
    exp_val, exp_aff, exp_rem = _compute_pandas_reference(retail_df, "Sales_Amount", "mean", "Return_Flag", "==", "Yes")
    assert res.value["affected_count"] == exp_aff
    assert res.value["remaining_rows"] == exp_rem
    assert np.isclose(res.value["hypothetical_value"], exp_val, rtol=1e-5, atol=1e-5)


def test_flight_dataset_q55_hypothetical(flight_df):
    """Tests hypothetical analysis on flight delay schema with numerical reference comparison."""
    if flight_df is None:
        pytest.skip("Flight dataset not found on disk.")

    # Q55: Exclude Peak_Hour == 0, calculate mean Departure_Delay
    params = {
        "action": "exclude",
        "column": "Departure_Delay",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "Peak_Hour",
            "operator": "==",
            "value": 0
        }
    }
    res = pandas_executor._hypothetical(flight_df, "Departure_Delay", params)
    assert res.success is True

    exp_val, exp_aff, exp_rem = _compute_pandas_reference(flight_df, "Departure_Delay", "mean", "Peak_Hour", "==", 0)
    assert res.value["affected_count"] == exp_aff, f"Expected {exp_aff} Peak_Hour==0 rows"
    assert res.value["remaining_rows"] == exp_rem, f"Expected {exp_rem} remaining rows"
    assert np.isclose(res.value["hypothetical_value"], exp_val, rtol=1e-5, atol=1e-5)
    # Confirm reference is approximately 50.61 min (not 0.0)
    assert np.isclose(res.value["hypothetical_value"], 50.6137, atol=0.01)


# =============================================================================
# 5. END-TO-END PIPELINE TESTS WITH NATURAL LANGUAGE PHRASING VARIATIONS
# =============================================================================

@pytest.mark.parametrize("query,expected_cond_col,expected_op,expected_val,expected_target,expected_metric", [
    (
        "If every row with is_senior = 0 were temporarily excluded, what would the average salary be?",
        "is_senior", "==", 0, "salary", "mean"
    ),
    (
        "What would the median salary be if all rows with department = Sales were excluded?",
        "department", "==", "Sales", "salary", "median"
    ),
    (
        "If every row with overtime_hours > 10 were temporarily removed from the dataset, what would the total salary be?",
        "overtime_hours", ">", 10, "salary", "sum"
    ),
    (
        "If all rows where performance_score < 2 were excluded, what would the resulting average salary be among the remaining rows?",
        "performance_score", "<", 2, "salary", "mean"
    )
])
def test_end_to_end_natural_language_pipeline(synthetic_df, query, expected_cond_col, expected_op,
                                             expected_val, expected_target, expected_metric):
    """
    Tests end-to-end pipeline:
    1. Normalization preserves operators and identifier boundaries.
    2. MasterRouter accurately interprets condition, operator, value, target metric, and target column.
    3. AnalyticalPlan executes successfully and verifies evidence.
    4. Narrative correctly incorporates computed values.
    """
    # Register dataset in registry
    entry = DatasetEntry(
        dataset_id="test_synthetic_id",
        filename="synthetic.csv",
        file_path="",
        upload_timestamp="",
        row_count=len(synthetic_df),
        column_count=len(synthetic_df.columns),
        file_fingerprint="synth_fp",
        schema_fingerprint="synth_sfp",
        dataframe=synthetic_df,
        profile={},
        schema_profile=[],
        column_profiles={}
    )
    dataset_registry.register(entry)

    ctx = ExecutionContext(
        session_id="test_session_nl",
        message=query,
        dataset_id="test_synthetic_id"
    )

    # 1. Normalization
    normalizer = QueryNormalizer()
    normalizer.normalize(ctx)
    assert ctx.normalized_query is not None

    # 2. Router classification
    router = MasterRouter()
    decision = router._analysis_fast_path(ctx, ctx.normalized_query)
    assert decision is not None, f"Router failed to match fast-path for: {query}"
    assert decision["intent"] in ("analysis", "DATA_OPERATION")
    assert len(decision["operations"]) == 1

    op = decision["operations"][0]
    assert op["type"] == "HYPOTHETICAL"
    assert op["column"] == expected_target
    assert op["target_metric"] == expected_metric

    excl = op["exclude_condition"]
    assert excl["column"] == expected_cond_col
    assert excl["operator"] == expected_op
    try:
        assert float(excl["value"]) == float(expected_val)
    except (ValueError, TypeError):
        assert str(excl["value"]).lower() == str(expected_val).lower()

    # 3. Pipeline execution
    plan = AnalyticalPlan(
        intent="hypothetical",
        operation="hypothetical",
        target_column=expected_target,
        parameters=op,
        plan=[]
    )
    result = pandas_executor.execute(plan, synthetic_df)
    assert result.success is True

    # 4. Independent reference assertion
    exp_val, exp_aff, exp_rem = _compute_pandas_reference(
        synthetic_df, expected_target, expected_metric, expected_cond_col, expected_op, expected_val
    )
    assert result.value["affected_count"] == exp_aff
    assert result.value["remaining_rows"] == exp_rem
    assert np.isclose(result.value["hypothetical_value"], exp_val, rtol=1e-5, atol=1e-5)

    # 5. Narrative formatting
    analytical_res = AnalyticalResult(
        operation="hypothetical",
        column=expected_target,
        value=result.value,
        verified=True
    )
    narrative = analytics_pipeline.build_narrative(analytical_res, "synthetic.csv")
    assert (
        f"{exp_val:.2f}" in narrative
        or f"{exp_val:,.2f}" in narrative
        or str(round(exp_val, 2)) in narrative
        or str(exp_val) in narrative
        or f"{exp_val:,.4f}" in narrative
    )


def test_q55_end_to_end_flight_query(flight_df):
    """End-to-end test of the exact Q55 query phrasing on flight data."""
    if flight_df is None:
        pytest.skip("Flight dataset not found on disk.")

    entry = DatasetEntry(
        dataset_id="flight_test_id",
        filename="india_flight_delay_model_input.csv",
        file_path="",
        upload_timestamp="",
        row_count=len(flight_df),
        column_count=len(flight_df.columns),
        file_fingerprint="flight_fp",
        schema_fingerprint="flight_sfp",
        dataframe=flight_df,
        profile={},
        schema_profile=[],
        column_profiles={}
    )
    dataset_registry.register(entry)

    query = (
        "If every row with Peak_Hour = 0 were temporarily excluded, "
        "what would the average Departure_Delay be among the remaining rows? "
        "Calculate this as a read-only hypothetical operation and leave the dataset unchanged."
    )
    ctx = ExecutionContext(
        session_id="q55_session",
        message=query,
        dataset_id="flight_test_id"
    )

    QueryNormalizer().normalize(ctx)
    router = MasterRouter()
    decision = router._analysis_fast_path(ctx, ctx.normalized_query)

    assert decision is not None
    op = decision["operations"][0]
    assert op["type"] == "HYPOTHETICAL"
    assert op["column"] == "Departure_Delay"
    assert op["target_metric"] == "mean"
    assert op["exclude_condition"]["column"] == "Peak_Hour"
    assert op["exclude_condition"]["operator"] == "=="
    assert op["exclude_condition"]["value"] == 0

    plan = AnalyticalPlan(
        intent="hypothetical",
        operation="hypothetical",
        target_column="Departure_Delay",
        parameters=op,
        plan=[]
    )
    result = pandas_executor.execute(plan, flight_df)
    assert result.success is True
    assert result.value["affected_count"] == 78708
    assert result.value["remaining_rows"] == 71292
    assert np.isclose(result.value["hypothetical_value"], 50.6137, atol=0.01)

    analytical_res = AnalyticalResult(
        operation="hypothetical",
        column="Departure_Delay",
        value=result.value,
        verified=True
    )
    narrative = analytics_pipeline.build_narrative(analytical_res, "india_flight_delay_model_input.csv")
    assert "50.6" in narrative


# =============================================================================
# 6. SUBSTANTIAL DELTA REGRESSION TESTS (ORIGINAL VS HYPOTHETICAL)
# =============================================================================

def test_substantial_delta_original_vs_hypothetical():
    """
    Verifies that when original_value and hypothetical_value differ substantially:
    1. Executor computes accurate hypothetical_value and preserves baseline original_value.
    2. Narrative explicitly distinguishes the two numbers and reports hypothetical_value
       as the result for remaining rows.
    """
    # 90 rows of 100, 10 rows of 1000 with flag=1.
    # Baseline mean = (90 * 100 + 10 * 1000) / 100 = 190.0
    # Hypothetical mean (excluding flag=1) = 100.0. Delta = -90.0.
    df = pd.DataFrame({
        "metric_col": [100.0] * 90 + [1000.0] * 10,
        "flag": [0] * 90 + [1] * 10
    })

    params = {
        "action": "exclude",
        "column": "metric_col",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "flag",
            "operator": "==",
            "value": 1
        }
    }
    res = pandas_executor._hypothetical(df, "metric_col", params)
    assert res.success is True
    val = res.value
    assert val["affected_count"] == 10
    assert val["remaining_rows"] == 90
    assert np.isclose(val["original_value"], 190.0)
    assert np.isclose(val["hypothetical_value"], 100.0)

    # Narrative verification
    analytical_res = AnalyticalResult(
        operation="hypothetical",
        column="metric_col",
        value=val,
        verified=True
    )
    narrative = analytics_pipeline.build_narrative(analytical_res, "test.csv")
    assert "100" in narrative
    assert "190" in narrative
    assert "resulting hypothetical mean of **metric_col** among the remaining rows is **100**" in narrative
    assert "baseline original mean was **190** before exclusion" in narrative


def test_substantial_delta_with_increase():
    """
    Verifies reverse delta where excluding low outliers substantially increases the metric.
    Baseline = 182.0, Hypothetical = 200.0.
    """
    # 90 rows of 200, 10 rows of 20 with flag='exclude_me'
    df = pd.DataFrame({
        "score": [200.0] * 90 + [20.0] * 10,
        "tag": ["keep"] * 90 + ["exclude_me"] * 10
    })

    params = {
        "action": "exclude",
        "column": "score",
        "target_metric": "mean",
        "exclude_condition": {
            "column": "tag",
            "operator": "==",
            "value": "exclude_me"
        }
    }
    res = pandas_executor._hypothetical(df, "score", params)
    assert res.success is True
    assert np.isclose(res.value["hypothetical_value"], 200.0)
    assert np.isclose(res.value["original_value"], 182.0)

    analytical_res = AnalyticalResult(
        operation="hypothetical",
        column="score",
        value=res.value,
        verified=True
    )
    narrative = analytics_pipeline.build_narrative(analytical_res, "test.csv")
    assert "200" in narrative
    assert "182" in narrative


# =============================================================================
# 7. STRICT METRIC AND SCHEMA CONTRACT VALIDATION (NO SILENT SUBSTITUTION)
# =============================================================================

def test_missing_target_column_rejected_explicitly():
    """Missing target column must fail with explicit error, never substitute row count."""
    df = pd.DataFrame({"col_a": [1, 2, 3], "flag": [0, 1, 0]})
    params = {
        "action": "exclude",
        "column": "nonexistent_target",
        "target_metric": "mean",
        "exclude_condition": {"column": "flag", "operator": "==", "value": 1}
    }
    res = pandas_executor._hypothetical(df, "nonexistent_target", params)
    assert res.success is False
    assert "Target column 'nonexistent_target' not found" in res.error


def test_missing_condition_column_rejected_explicitly():
    """Missing condition column must fail with explicit error, never silently accept."""
    df = pd.DataFrame({"col_a": [1, 2, 3], "flag": [0, 1, 0]})
    params = {
        "action": "exclude",
        "column": "col_a",
        "target_metric": "mean",
        "exclude_condition": {"column": "nonexistent_flag", "operator": "==", "value": 1}
    }
    res = pandas_executor._hypothetical(df, "col_a", params)
    assert res.success is False
    assert "Condition column 'nonexistent_flag' not found" in res.error


def test_unsupported_metric_rejected_explicitly():
    """Unsupported metrics must fail explicitly, never silently substitute len(df)."""
    df = pd.DataFrame({"col_a": [1, 2, 3], "flag": [0, 1, 0]})
    for bad_metric in ["variance", "geometric_mean", "skewness", "custom_func"]:
        params = {
            "action": "exclude",
            "column": "col_a",
            "target_metric": bad_metric,
            "metric": bad_metric,
            "exclude_condition": {"column": "flag", "operator": "==", "value": 1}
        }
        res = pandas_executor._hypothetical(df, "col_a", params)
        assert res.success is False
        assert f"Unsupported metric '{bad_metric}'" in res.error


def test_empty_or_all_nan_target_handled_safely():
    """When target column has all NaN values in remaining rows, return None for hypothetical_value."""
    df = pd.DataFrame({
        "col_a": [np.nan, np.nan, 10.0],
        "flag": [0, 0, 1]
    })
    params = {
        "action": "exclude",
        "column": "col_a",
        "target_metric": "mean",
        "exclude_condition": {"column": "flag", "operator": "==", "value": 1}
    }
    res = pandas_executor._hypothetical(df, "col_a", params)
    assert res.success is True
    assert res.value["remaining_rows"] == 2
    assert res.value["affected_count"] == 1
    assert res.value["hypothetical_value"] is None

    analytical_res = AnalyticalResult(
        operation="hypothetical",
        column="col_a",
        value=res.value,
        verified=True
    )
    narrative = analytics_pipeline.build_narrative(analytical_res, "test.csv")
    assert "no valid records exist to compute" in narrative


# =============================================================================
# 8. RESPONSE COMPOSER GROUNDING CONTRACT & NARRATIVE FALLBACK
# =============================================================================

def test_response_composer_falls_back_when_llm_omits_hypothetical_value(monkeypatch):
    """
    If the LLM response composer hallucinates and omits the computed hypothetical_value,
    ResponseComposer MUST fall back to the verified engine narrative to guarantee accuracy.
    """
    from core.composer import ResponseComposer
    from engines.base import EngineResult
    from providers.base import ProviderResponse

    composer = ResponseComposer()
    ctx = ExecutionContext(
        session_id="composer_test_session",
        message="What would the average salary be if flag=1 is excluded?",
        dataset_id="synth_test"
    )

    facts = {
        "operation": "hypothetical",
        "computed_answer": "In the hypothetical scenario (10 rows excluded, 90 rows remaining), the resulting hypothetical mean of **salary** among the remaining rows is **500** (baseline original mean was **100** before exclusion).",
        "operations": [
            {
                "operation": "hypothetical",
                "value": {
                    "hypothetical_value": 500.0,
                    "original_value": 100.0,
                    "metric": "mean",
                    "remaining_rows": 90,
                    "affected_count": 10
                }
            }
        ]
    }

    ctx.intent = "analysis"
    engine_res = EngineResult(
        answer="In the hypothetical scenario, the mean is 500.",
        facts=facts
    )

    class MockHallucinatingProvider:
        def generate(self, req):
            return ProviderResponse(
                text="Based on the dataset, the average salary among the remaining rows is 100.00.",
                model="mock_model",
                provider="mock_llm",
                latency_ms=120,
                success=True
            )

    monkeypatch.setattr("core.composer.provider_engine", MockHallucinatingProvider())

    final_res = composer.compose(ctx, engine_res)
    assert "500" in final_res.answer
    assert "resulting hypothetical mean" in final_res.answer


def test_response_composer_preserves_faithful_llm_response(monkeypatch):
    """
    When the LLM response correctly includes the hypothetical_value, ResponseComposer
    preserves the rich natural language response.
    """
    from core.composer import ResponseComposer
    from engines.base import EngineResult
    from providers.base import ProviderResponse

    composer = ResponseComposer()
    ctx = ExecutionContext(
        session_id="composer_test_session_faithful",
        message="What would the average salary be if flag=1 is excluded?",
        dataset_id="synth_test"
    )

    facts = {
        "operation": "hypothetical",
        "computed_answer": "In the hypothetical scenario, hypothetical mean is 500.",
        "operations": [
            {
                "operation": "hypothetical",
                "value": {
                    "hypothetical_value": 500.0,
                    "original_value": 100.0,
                    "metric": "mean",
                    "remaining_rows": 90,
                    "affected_count": 10
                }
            }
        ]
    }

    ctx.intent = "analysis"
    engine_res = EngineResult(
        answer="Hypothetical mean is 500.",
        facts=facts
    )

    faithful_text = (
        "If rows with flag=1 are excluded, the simulated average salary among the 90 remaining rows "
        "would be **500.00**, compared to the original baseline average of 100.00."
    )
    class MockFaithfulProvider:
        def generate(self, req):
            return ProviderResponse(
                text=faithful_text,
                model="mock_model",
                provider="mock_llm",
                latency_ms=105,
                success=True
            )

    monkeypatch.setattr("core.composer.provider_engine", MockFaithfulProvider())

    final_res = composer.compose(ctx, engine_res)
    assert final_res.answer == faithful_text


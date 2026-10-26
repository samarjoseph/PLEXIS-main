"""
Test suite for Cluster A: Multi-Dimensional Grouping & Grouped Binary Target Rates.

Verifies:
  1. Generic, dataset-agnostic abstractions across synthetic and domain datasets.
  2. Independent reference assertions calculated separately via Pandas.
  3. Schema validation, column existence checks, and type mismatch checks.
  4. Dataset immutability (DataFrames are never mutated in place).
  5. End-to-end routing, planning, execution, and narrative generation.
"""

import pytest
import pandas as pd
import numpy as np

from planner.schema import AnalyticalPlan
from planner.validator import PlanValidator
from executor.pandas_executor import PandasExecutor, ExecutorResult
from router.schema_validator import SchemaValidator
from analytics.pipeline import AnalyticsPipeline
from analytics.result import AnalyticalResult


@pytest.fixture
def synthetic_df():
    """Synthetic dataset with completely independent columns and types."""
    np.random.seed(42)
    n = 200
    departments = ["Engineering", "Sales", "Marketing", "HR"]
    roles = ["Junior", "Mid", "Senior"]
    ratings = [1, 2, 3, 4, 5]
    
    data = {
        "dept_name": np.random.choice(departments, n),
        "job_level": np.random.choice(roles, n),
        "is_promoted": np.random.choice([0, 1], n, p=[0.7, 0.3]),
        "is_remote": np.random.choice([0, 1], n, p=[0.5, 0.5]),
        "performance_score": np.random.uniform(50.0, 100.0, n).round(2),
        "tenure_months": np.random.randint(1, 120, n),
    }
    return pd.DataFrame(data)


@pytest.fixture
def executor():
    return PandasExecutor()


@pytest.fixture
def schema_validator():
    return SchemaValidator()


@pytest.fixture
def plan_validator():
    return PlanValidator()


def run_plan(executor, operation: str, col = None, df: pd.DataFrame = None, params: dict = None):
    plan = AnalyticalPlan(
        intent="DATA_OPERATION",
        operation=operation,
        target_column=col,
        parameters=params or {},
    )
    return executor.execute(plan, df)


# =============================================================================
# 1. CROSSTAB TESTS
# =============================================================================

def test_crosstab_synthetic(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {"column": "is_promoted", "group_by": "dept_name"}
    res = run_plan(executor, "crosstab", "is_promoted", synthetic_df, params=params)
    assert res.success is True
    assert isinstance(res.value, dict)
    
    # Independent reference assertion
    ref_ct = pd.crosstab(df_copy["dept_name"], df_copy["is_promoted"])
    ref_pct = pd.crosstab(df_copy["dept_name"], df_copy["is_promoted"], normalize="index") * 100.0
    
    for dept in ref_ct.index:
        assert dept in res.value
        assert res.value[dept]["count_0"] == int(ref_ct.loc[dept, 0])
        assert res.value[dept]["count_1"] == int(ref_ct.loc[dept, 1])
        assert res.value[dept]["pct_0"] == round(float(ref_pct.loc[dept, 0]), 2)
        assert res.value[dept]["pct_1"] == round(float(ref_pct.loc[dept, 1]), 2)
        
    # Immutability check
    pd.testing.assert_frame_equal(synthetic_df, df_copy)


def test_crosstab_missing_columns(executor, synthetic_df):
    params = {"column": "nonexistent_col", "group_by": "dept_name"}
    res = run_plan(executor, "crosstab", "nonexistent_col", synthetic_df, params=params)
    assert res.success is False
    assert "not found" in res.error.lower() or "requires valid" in res.error.lower()


# =============================================================================
# 2. GROUPED_RATE TESTS
# =============================================================================

def test_grouped_rate_synthetic(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {
        "target_column": "is_promoted",
        "group_by": "dept_name",
        "target_value": 1,
        "top_n": 3,
        "ascending": False,
    }
    res = run_plan(executor, "grouped_rate", "is_promoted", synthetic_df, params=params)
    assert res.success is True
    assert len(res.value) <= 3
    
    # Independent reference
    grp = df_copy.groupby("dept_name")["is_promoted"]
    num = grp.sum()
    den = grp.count()
    rate = (num / den).round(4)
    ref = pd.DataFrame({"num": num, "den": den, "rate": rate}).sort_values("rate", ascending=False).head(3)
    
    for dept in ref.index:
        assert dept in res.value
        assert res.value[dept]["numerator"] == int(ref.loc[dept, "num"])
        assert res.value[dept]["denominator"] == int(ref.loc[dept, "den"])
        assert res.value[dept]["rate"] == float(ref.loc[dept, "rate"])
        
    # Immutability check
    pd.testing.assert_frame_equal(synthetic_df, df_copy)


def test_grouped_rate_joint_conditions(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {
        "group_by": "dept_name",
        "conditions": [
            {"column": "is_promoted", "operator": "==", "value": 1},
            {"column": "is_remote", "operator": "==", "value": 1},
        ],
        "top_n": 4,
    }
    res = run_plan(executor, "grouped_rate", None, synthetic_df, params=params)
    assert res.success is True
    
    # Independent reference
    mask = (df_copy["is_promoted"] == 1) & (df_copy["is_remote"] == 1)
    ref_pos = df_copy[mask].groupby("dept_name").size()
    ref_tot = df_copy.groupby("dept_name").size()
    
    for dept, stats in res.value.items():
        expected_pos = int(ref_pos.get(dept, 0))
        expected_tot = int(ref_tot.get(dept, 0))
        assert stats["numerator"] == expected_pos
        assert stats["denominator"] == expected_tot
        expected_rate = round(expected_pos / expected_tot, 4) if expected_tot > 0 else 0.0
        assert stats["rate"] == expected_rate


# =============================================================================
# 3. TWO_FACTOR_AGGREGATION TESTS
# =============================================================================

def test_two_factor_aggregation_per_group_top(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {
        "group_by": "dept_name",
        "secondary_group": "job_level",
        "value_column": "performance_score",
        "metric": "mean",
        "per_group_top": True,
    }
    res = run_plan(executor, "two_factor_aggregation", "performance_score", synthetic_df, params=params)
    assert res.success is True
    assert isinstance(res.value, dict)
    
    # Independent reference
    for dept, sub in df_copy.groupby("dept_name"):
        means = sub.groupby("job_level")["performance_score"].mean()
        top_role = means.idxmax()
        expected_mean = round(float(means.loc[top_role]), 2)
        expected_count = int(sub[sub["job_level"] == top_role].shape[0])
        
        info = res.value[dept]
        assert info["highest_job_level"] == top_role
        assert info["mean_performance_score"] == expected_mean
        assert info["count"] == expected_count


def test_two_factor_aggregation_top_combinations(executor, synthetic_df):
    params = {
        "group_by": "dept_name",
        "secondary_group": "job_level",
        "value_column": "performance_score",
        "metric": "mean",
        "top_n": 5,
        "min_observations": 5,
        "per_group_top": False,
    }
    res = run_plan(executor, "two_factor_aggregation", "performance_score", synthetic_df, params=params)
    assert res.success is True
    assert isinstance(res.value, list)
    assert len(res.value) <= 5
    for item in res.value:
        assert "dept_name" in item
        assert "job_level" in item
        assert "mean_performance_score" in item
        assert item["count"] >= 5


# =============================================================================
# 4. GROUPED_BINARY_COMPARISON TESTS
# =============================================================================

def test_grouped_binary_comparison(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {
        "group_by": "dept_name",
        "binary_column": "is_remote",
        "value_column": "performance_score",
        "metric": "mean",
    }
    res = run_plan(executor, "grouped_binary_comparison", "performance_score", synthetic_df, params=params)
    assert res.success is True
    assert isinstance(res.value, dict)
    
    # Independent reference
    for dept, sub in df_copy.groupby("dept_name"):
        rem0 = sub[sub["is_remote"] == 0]["performance_score"]
        rem1 = sub[sub["is_remote"] == 1]["performance_score"]
        m0 = round(float(rem0.mean()), 2) if len(rem0) > 0 else 0.0
        m1 = round(float(rem1.mean()), 2) if len(rem1) > 0 else 0.0
        expected_diff = round(m1 - m0, 2)
        
        info = res.value[dept]
        assert info["is_remote_0_mean"] == m0
        assert info["is_remote_1_mean"] == m1
        assert info["difference"] == expected_diff


# =============================================================================
# 5. GROUPED_MULTI_STAT TESTS
# =============================================================================

def test_grouped_multi_stat(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {
        "group_by": "dept_name",
        "value_column": "performance_score",
        "target_column": "is_promoted",
    }
    res = run_plan(executor, "grouped_multi_stat", "performance_score", synthetic_df, params=params)
    assert res.success is True
    assert isinstance(res.value, dict)
    
    for dept, sub in df_copy.groupby("dept_name"):
        info = res.value[dept]
        assert info["mean_performance_score"] == round(float(sub["performance_score"].mean()), 2)
        assert info["median_performance_score"] == round(float(sub["performance_score"].median()), 2)
        assert info["count"] == len(sub)
        assert info["target_rate"] == round(float((sub["is_promoted"] == 1).mean()), 4)


# =============================================================================
# 6. BINNED_TARGET_RATE TESTS
# =============================================================================

def test_binned_target_rate(executor, synthetic_df):
    df_copy = synthetic_df.copy()
    params = {
        "bin_column": "performance_score",
        "target_column": "is_promoted",
        "value_column": "tenure_months",
        "bins": 4,
    }
    res = run_plan(executor, "binned_target_rate", "performance_score", synthetic_df, params=params)
    assert res.success is True
    assert isinstance(res.value, dict)
    assert len(res.value) == 4
    
    # Immutability check
    pd.testing.assert_frame_equal(synthetic_df, df_copy)


# =============================================================================
# 7. SCHEMA VALIDATOR TESTS
# =============================================================================

def test_schema_validator_cluster_a(schema_validator):
    cols = [
        {"name": "department", "type": "string"},
        {"name": "salary", "type": "numeric"},
        {"name": "is_manager", "type": "numeric"},
        {"name": "rating", "type": "numeric"},
    ]
    
    # 1. Valid CROSSTAB
    v1 = schema_validator.validate({
        "intent": "DATA_OPERATION",
        "operation": {"type": "CROSSTAB", "column": "is_manager", "group_by": "department"}
    }, columns=cols)
    assert v1.valid is True
    
    # 2. Missing column in CROSSTAB
    v2 = schema_validator.validate({
        "intent": "DATA_OPERATION",
        "operation": {"type": "CROSSTAB", "column": "ghost_column", "group_by": "department"}
    }, columns=cols)
    assert v2.valid is False
    assert v2.error_code == "COLUMN_NOT_FOUND"
    
    # 3. Non-numeric value column in TWO_FACTOR_AGGREGATION
    v3 = schema_validator.validate({
        "intent": "DATA_OPERATION",
        "operation": {
            "type": "TWO_FACTOR_AGGREGATION",
            "group_by": "department",
            "secondary_group": "is_manager",
            "value_column": "department", # invalid, string
        }
    }, columns=cols)
    assert v3.valid is False
    assert v3.error_code == "TYPE_MISMATCH"


# =============================================================================
# 8. PIPELINE & NARRATIVE GENERATION TESTS
# =============================================================================

def test_pipeline_narrative_cluster_a(synthetic_df):
    pipeline = AnalyticsPipeline()
    
    # Test CROSSTAB narrative
    res_crosstab = AnalyticalResult(
        value={"Sales": {"count_0": 40, "count_1": 10, "pct_0": 80.0, "pct_1": 20.0}},
        operation="crosstab",
        column="is_promoted",
        verified=True,
    )
    narrative = pipeline.build_narrative(res_crosstab, dataset_name="Staff Data")
    assert "Sales" in narrative
    assert "80.00%" in narrative
    assert "20.00%" in narrative
    
    # Test GROUPED_RATE narrative
    res_rate = AnalyticalResult(
        value={"Engineering": {"customer_count": 50, "numerator": 15, "negative_count": 35, "denominator": 50, "rate": 0.30, "percentage": 30.0}},
        operation="grouped_rate",
        column="is_promoted",
        details={"target_column": "is_promoted", "group_by": "dept_name"},
        verified=True,
    )
    narrative_rate = pipeline.build_narrative(res_rate, dataset_name="Staff Data")
    assert "Engineering" in narrative_rate
    assert "15 positive" in narrative_rate or "15" in narrative_rate
    assert "50 customers" in narrative_rate or "50" in narrative_rate
    assert "0.3000" in narrative_rate
    assert "30.00%" in narrative_rate

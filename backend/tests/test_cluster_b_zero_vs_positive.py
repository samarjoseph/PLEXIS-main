"""
Test Suite for Cluster B: Continuous Zero-vs-Positive Slicing (ZERO_VS_POSITIVE_COMPARISON)

Tests:
1. SchemaValidator handling of ZERO_VS_POSITIVE_COMPARISON (missing column, non-existent column, type mismatch, case normalization).
2. PlanValidator acceptance and integration with AnalyticalPlan.
3. PandasExecutor mathematical correctness against independent Pandas truth on synthetic data.
4. Dataset immutability during execution.
5. Adversarial column names (e.g. columns named 'mean', 'difference', 'count').
6. Pipeline narrative synthesis formatting.
"""

import pytest
import pandas as pd
import numpy as np

from router.schema_validator import SchemaValidator
from planner.schema import AnalyticalPlan, SUPPORTED_OPERATIONS
from planner.validator import PlanValidator
from executor.pandas_executor import PandasExecutor
from analytics.pipeline import AnalyticsPipeline
from analytics.result import AnalyticalResult


@pytest.fixture
def sample_columns():
    return [
        {"name": "Transaction_ID", "type": "string"},
        {"name": "Rainfall_mm", "type": "numeric"},
        {"name": "Previous_Delay", "type": "numeric"},
        {"name": "Departure_Delay", "type": "numeric"},
        {"name": "Category", "type": "categorical"},
    ]


@pytest.fixture
def synthetic_df():
    np.random.seed(42)
    # 100 zero rows, 200 positive rows
    n_zero = 100
    n_pos = 200
    df_zero = pd.DataFrame({
        "Rainfall_mm": [0.0] * n_zero,
        "Departure_Delay": np.random.normal(loc=20.0, scale=5.0, size=n_zero).round(2),
        "Category": ["A"] * (n_zero // 2) + ["B"] * (n_zero // 2),
    })
    df_pos = pd.DataFrame({
        "Rainfall_mm": np.random.uniform(low=0.1, high=50.0, size=n_pos).round(2),
        "Departure_Delay": np.random.normal(loc=35.0, scale=5.0, size=n_pos).round(2),
        "Category": ["A"] * (n_pos // 2) + ["B"] * (n_pos // 2),
    })
    df = pd.concat([df_zero, df_pos], ignore_index=True)
    return df


def test_supported_operations_registry():
    assert "zero_vs_positive_comparison" in SUPPORTED_OPERATIONS


def test_schema_validator_zero_vs_positive(sample_columns):
    validator = SchemaValidator()

    # Valid operation
    op = {
        "type": "ZERO_VS_POSITIVE_COMPARISON",
        "split_column": "rainfall_mm",
        "value_column": "departure_delay",
    }
    interpretation = {"intent": "DATA_OPERATION", "operation": op}
    res = validator.validate(interpretation, sample_columns)
    assert res.valid is True
    assert res.corrected_operation["split_column"] == "Rainfall_mm"
    assert res.corrected_operation["value_column"] == "Departure_Delay"

    # Missing split_column
    op_missing = {"type": "ZERO_VS_POSITIVE_COMPARISON", "value_column": "Departure_Delay"}
    res = validator.validate({"intent": "DATA_OPERATION", "operation": op_missing}, sample_columns)
    assert res.valid is False
    assert res.error_code == "MISSING_COLUMN"

    # Non-existent column
    op_bad_col = {
        "type": "ZERO_VS_POSITIVE_COMPARISON",
        "split_column": "non_existent",
        "value_column": "Departure_Delay",
    }
    res = validator.validate({"intent": "DATA_OPERATION", "operation": op_bad_col}, sample_columns)
    assert res.valid is False
    assert res.error_code == "COLUMN_NOT_FOUND"

    # Non-numeric split column
    op_non_num = {
        "type": "ZERO_VS_POSITIVE_COMPARISON",
        "split_column": "Category",
        "value_column": "Departure_Delay",
    }
    res = validator.validate({"intent": "DATA_OPERATION", "operation": op_non_num}, sample_columns)
    assert res.valid is False
    assert res.error_code == "TYPE_MISMATCH"


def test_plan_validator_zero_vs_positive():
    plan_validator = PlanValidator()
    columns = ["Rainfall_mm", "Departure_Delay", "Category"]
    types = {"Rainfall_mm": "numeric", "Departure_Delay": "numeric", "Category": "categorical"}

    plan = AnalyticalPlan(
        intent="zero_vs_positive_comparison",
        operation="zero_vs_positive_comparison",
        target_column="Departure_Delay",
        parameters={"split_column": "Rainfall_mm", "value_column": "Departure_Delay"},
    )
    res = plan_validator.validate(plan, columns, types)
    assert res.valid is True


def test_pandas_executor_synthetic_math(synthetic_df):
    executor = PandasExecutor()
    df_copy = synthetic_df.copy(deep=True)

    # Independent Pandas ground truth
    zero_mask = synthetic_df["Rainfall_mm"] == 0
    pos_mask = synthetic_df["Rainfall_mm"] > 0
    
    gt_zero_cnt = int(zero_mask.sum())
    gt_pos_cnt = int(pos_mask.sum())
    gt_zero_mean = round(float(synthetic_df.loc[zero_mask, "Departure_Delay"].mean()), 2)
    gt_pos_mean = round(float(synthetic_df.loc[pos_mask, "Departure_Delay"].mean()), 2)
    gt_zero_med = round(float(synthetic_df.loc[zero_mask, "Departure_Delay"].median()), 2)
    gt_pos_med = round(float(synthetic_df.loc[pos_mask, "Departure_Delay"].median()), 2)
    gt_diff_mean = round(gt_pos_mean - gt_zero_mean, 2)
    gt_diff_med = round(gt_pos_med - gt_zero_med, 2)

    plan = AnalyticalPlan(
        intent="zero_vs_positive_comparison",
        operation="zero_vs_positive_comparison",
        target_column="Departure_Delay",
        parameters={"split_column": "Rainfall_mm", "value_column": "Departure_Delay"},
    )
    exec_res = executor.execute(plan, synthetic_df)
    assert exec_res.success is True
    val = exec_res.value

    # Verify zero subset
    assert val["zero_subset"]["count"] == gt_zero_cnt
    assert val["zero_subset"]["mean"] == gt_zero_mean
    assert val["zero_subset"]["median"] == gt_zero_med

    # Verify positive subset
    assert val["positive_subset"]["count"] == gt_pos_cnt
    assert val["positive_subset"]["mean"] == gt_pos_mean
    assert val["positive_subset"]["median"] == gt_pos_med

    # Verify differences
    assert val["difference_in_means"] == gt_diff_mean
    assert val["difference_in_medians"] == gt_diff_med

    # Verify immutability
    pd.testing.assert_frame_equal(synthetic_df, df_copy)


def test_adversarial_physical_columns():
    """Verify operation works even when dataset has columns named 'mean', 'count', 'difference'."""
    executor = PandasExecutor()
    adv_df = pd.DataFrame({
        "difference": [0, 0, 5, 10, 15],
        "mean": [10.0, 20.0, 30.0, 40.0, 50.0],
        "count": [1, 2, 3, 4, 5],
    })

    plan = AnalyticalPlan(
        intent="zero_vs_positive_comparison",
        operation="zero_vs_positive_comparison",
        target_column="mean",
        parameters={"split_column": "difference", "value_column": "mean"},
    )
    res = executor.execute(plan, adv_df)
    assert res.success is True
    val = res.value
    # 2 rows with difference == 0 (values: 10.0, 20.0 -> mean 15.0)
    assert val["zero_subset"]["count"] == 2
    assert val["zero_subset"]["mean"] == 15.0
    # 3 rows with difference > 0 (values: 30.0, 40.0, 50.0 -> mean 40.0)
    assert val["positive_subset"]["count"] == 3
    assert val["positive_subset"]["mean"] == 40.0
    assert val["difference_in_means"] == 25.0


def test_pipeline_narrative_formatting():
    pipeline = AnalyticsPipeline()
    exec_val = {
        "split_column": "Rainfall_mm",
        "value_column": "Departure_Delay",
        "zero_subset": {"count": 57540, "mean": 41.40, "median": 45.00},
        "positive_subset": {"count": 92460, "mean": 43.45, "median": 47.00},
        "difference_in_means": 2.04,
        "difference_in_medians": 2.00,
    }
    ana_res = AnalyticalResult(
        verified=True,
        value=exec_val,
        operation="zero_vs_positive_comparison",
        column="Departure_Delay",
        details=exec_val,
    )
    narrative = pipeline.build_narrative(ana_res, "flights.csv")
    assert "57,540" in narrative
    assert "41.40" in narrative
    assert "45.00" in narrative
    assert "92,460" in narrative
    assert "43.45" in narrative
    assert "47.00" in narrative
    assert "2.04" in narrative
    assert "2.00" in narrative

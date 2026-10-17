"""
Test Suite for Cluster C: Binary Indicator Comparison (BINARY_INDICATOR_COMPARISON)

Tests:
1. SchemaValidator handling of BINARY_INDICATOR_COMPARISON (missing column, non-existent column, type mismatch, case normalization).
2. PlanValidator acceptance and integration with AnalyticalPlan.
3. PandasExecutor mathematical correctness against independent Pandas truth on synthetic data (numeric 0/1, boolean, string).
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
        {"name": "Peak_Hour", "type": "numeric"},
        {"name": "Is_Weekend", "type": "boolean"},
        {"name": "Departure_Delay", "type": "numeric"},
        {"name": "Category", "type": "categorical"},
    ]


@pytest.fixture
def synthetic_df():
    np.random.seed(42)
    n_0 = 120
    n_1 = 180
    df_0 = pd.DataFrame({
        "Peak_Hour": [0] * n_0,
        "Departure_Delay": np.random.normal(loc=30.0, scale=4.0, size=n_0).round(2),
        "Category": ["A"] * (n_0 // 2) + ["B"] * (n_0 // 2),
    })
    df_1 = pd.DataFrame({
        "Peak_Hour": [1] * n_1,
        "Departure_Delay": np.random.normal(loc=55.0, scale=4.0, size=n_1).round(2),
        "Category": ["A"] * (n_1 // 2) + ["B"] * (n_1 // 2),
    })
    return pd.concat([df_0, df_1], ignore_index=True)


def test_supported_operations_registry():
    assert "binary_indicator_comparison" in SUPPORTED_OPERATIONS


def test_schema_validator_binary_indicator(sample_columns):
    validator = SchemaValidator()

    # Valid operation
    op = {
        "type": "BINARY_INDICATOR_COMPARISON",
        "binary_column": "peak_hour",
        "value_column": "departure_delay",
    }
    interpretation = {"intent": "DATA_OPERATION", "operation": op}
    res = validator.validate(interpretation, sample_columns)
    assert res.valid is True
    assert res.corrected_operation["binary_column"] == "Peak_Hour"
    assert res.corrected_operation["value_column"] == "Departure_Delay"

    # Missing binary_column
    op_missing = {"type": "BINARY_INDICATOR_COMPARISON", "value_column": "Departure_Delay"}
    res = validator.validate({"intent": "DATA_OPERATION", "operation": op_missing}, sample_columns)
    assert res.valid is False
    assert res.error_code == "MISSING_COLUMN"

    # Non-existent column
    op_bad_col = {
        "type": "BINARY_INDICATOR_COMPARISON",
        "binary_column": "non_existent",
        "value_column": "Departure_Delay",
    }
    res = validator.validate({"intent": "DATA_OPERATION", "operation": op_bad_col}, sample_columns)
    assert res.valid is False
    assert res.error_code == "COLUMN_NOT_FOUND"

    # Non-numeric value column
    op_non_num = {
        "type": "BINARY_INDICATOR_COMPARISON",
        "binary_column": "Peak_Hour",
        "value_column": "Category",
    }
    res = validator.validate({"intent": "DATA_OPERATION", "operation": op_non_num}, sample_columns)
    assert res.valid is False
    assert res.error_code == "TYPE_MISMATCH"


def test_plan_validator_binary_indicator():
    plan_validator = PlanValidator()
    columns = ["Peak_Hour", "Departure_Delay", "Category"]
    types = {"Peak_Hour": "numeric", "Departure_Delay": "numeric", "Category": "categorical"}

    plan = AnalyticalPlan(
        intent="binary_indicator_comparison",
        operation="binary_indicator_comparison",
        target_column="Departure_Delay",
        parameters={"binary_column": "Peak_Hour", "value_column": "Departure_Delay"},
    )
    res = plan_validator.validate(plan, columns, types)
    assert res.valid is True


def test_pandas_executor_synthetic_math(synthetic_df):
    executor = PandasExecutor()
    df_copy = synthetic_df.copy(deep=True)

    # Independent Pandas ground truth
    mask_0 = synthetic_df["Peak_Hour"] == 0
    mask_1 = synthetic_df["Peak_Hour"] == 1

    gt_0_cnt = int(mask_0.sum())
    gt_1_cnt = int(mask_1.sum())
    gt_0_mean = round(float(synthetic_df.loc[mask_0, "Departure_Delay"].mean()), 2)
    gt_1_mean = round(float(synthetic_df.loc[mask_1, "Departure_Delay"].mean()), 2)
    gt_0_med = round(float(synthetic_df.loc[mask_0, "Departure_Delay"].median()), 2)
    gt_1_med = round(float(synthetic_df.loc[mask_1, "Departure_Delay"].median()), 2)
    gt_diff_mean = round(gt_1_mean - gt_0_mean, 2)
    gt_diff_med = round(gt_1_med - gt_0_med, 2)

    plan = AnalyticalPlan(
        intent="binary_indicator_comparison",
        operation="binary_indicator_comparison",
        target_column="Departure_Delay",
        parameters={"binary_column": "Peak_Hour", "value_column": "Departure_Delay"},
    )
    exec_res = executor.execute(plan, synthetic_df)
    assert exec_res.success is True
    val = exec_res.value

    # Verify group 0
    assert val["group_0"]["count"] == gt_0_cnt
    assert val["group_0"]["mean"] == gt_0_mean
    assert val["group_0"]["median"] == gt_0_med

    # Verify group 1
    assert val["group_1"]["count"] == gt_1_cnt
    assert val["group_1"]["mean"] == gt_1_mean
    assert val["group_1"]["median"] == gt_1_med

    # Verify differences
    assert val["difference_in_means"] == gt_diff_mean
    assert val["difference_in_medians"] == gt_diff_med

    # Verify contextual aliases
    assert val["peak_0_mean"] == gt_0_mean
    assert val["peak_1_mean"] == gt_1_mean

    # Verify immutability
    pd.testing.assert_frame_equal(synthetic_df, df_copy)


def test_adversarial_physical_columns():
    """Verify operation works even when dataset has columns named 'mean', 'count', 'difference'."""
    executor = PandasExecutor()
    adv_df = pd.DataFrame({
        "difference": [0, 0, 1, 1, 1],
        "mean": [15.0, 25.0, 40.0, 50.0, 60.0],
        "count": [1, 2, 3, 4, 5],
    })

    plan = AnalyticalPlan(
        intent="binary_indicator_comparison",
        operation="binary_indicator_comparison",
        target_column="mean",
        parameters={"binary_column": "difference", "value_column": "mean"},
    )
    res = executor.execute(plan, adv_df)
    assert res.success is True
    val = res.value
    # 2 rows with difference == 0 (mean 20.0)
    assert val["group_0"]["count"] == 2
    assert val["group_0"]["mean"] == 20.0
    # 3 rows with difference == 1 (mean 50.0)
    assert val["group_1"]["count"] == 3
    assert val["group_1"]["mean"] == 50.0
    assert val["difference_in_means"] == 30.0


def test_pipeline_narrative_formatting():
    pipeline = AnalyticsPipeline()
    exec_val = {
        "binary_column": "Peak_Hour",
        "value_column": "Departure_Delay",
        "group_0": {"label": "0", "count": 78708, "mean": 35.46, "median": 41.00},
        "group_1": {"label": "1", "count": 71292, "mean": 50.61, "median": 52.00},
        "difference_in_means": 15.15,
        "difference_in_medians": 11.00,
    }
    ana_res = AnalyticalResult(
        verified=True,
        value=exec_val,
        operation="binary_indicator_comparison",
        column="Departure_Delay",
        details=exec_val,
    )
    narrative = pipeline.build_narrative(ana_res, "flights.csv")
    assert "78,708" in narrative
    assert "35.46" in narrative
    assert "41.00" in narrative
    assert "71,292" in narrative
    assert "50.61" in narrative
    assert "52.00" in narrative
    assert "15.15" in narrative
    assert "11.00" in narrative

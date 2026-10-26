"""
Unit and Parity Tests for Compositional Planning Primitives:
- OVERALL_EVENT_RATE
- GROUP_METRIC_DIFFERENCE

Verifies execution under both PandasExecutor and DuckDBExecutor with 100% numerical parity.
"""

import pytest
import pandas as pd
import numpy as np

from executor.pandas_executor import PandasExecutor
from executor.duckdb_executor import DuckDBExecutor
from executor.hybrid_executor import HybridExecutor
from planner.schema import AnalyticalPlan


@pytest.fixture
def synthetic_df():
    """Synthetic dataset with known ground-truth metrics."""
    np.random.seed(42)
    n = 1000
    df = pd.DataFrame({
        "order_id": [f"ORD_{i:04d}" for i in range(n)],
        "payment_mode": np.random.choice(["Credit Card", "Debit Card", "UPI", "Cash"], n),
        "total_amount": np.random.exponential(scale=100.0, size=n).round(2),
        "refund_status": np.random.choice(["Refunded", "Completed"], n, p=[0.25, 0.75]),
        "customer_segment": np.random.choice(["Enterprise", "Consumer", "SMB"], n),
        "discount_applied": np.random.choice([0, 1], n, p=[0.6, 0.4]),
    })
    return df


@pytest.fixture
def pandas_exec():
    return PandasExecutor()


@pytest.fixture
def duckdb_exec():
    return DuckDBExecutor()


@pytest.fixture
def hybrid_exec():
    return HybridExecutor()


def test_overall_event_rate_pandas(pandas_exec, synthetic_df):
    """Test overall event rate under PandasExecutor."""
    plan = AnalyticalPlan(
        operation="overall_event_rate",
        target_column="refund_status",
        parameters={"target_column": "refund_status", "target_value": "Refunded"},
    )
    res = pandas_exec.execute(plan, synthetic_df)
    assert res.success is True
    assert res.operation == "overall_event_rate"

    # Compute expected
    expected_count = (synthetic_df["refund_status"] == "Refunded").sum()
    expected_pct = round(expected_count / len(synthetic_df) * 100.0, 2)
    assert res.value == expected_pct
    assert res.details["positive_count"] == int(expected_count)
    assert res.details["total_rows"] == len(synthetic_df)


def test_overall_event_rate_duckdb_parity(pandas_exec, duckdb_exec, synthetic_df):
    """Test numerical parity between Pandas and DuckDB for overall_event_rate."""
    plan = AnalyticalPlan(
        operation="overall_event_rate",
        target_column="refund_status",
        parameters={"target_column": "refund_status", "target_value": "Refunded"},
    )
    p_res = pandas_exec.execute(plan, synthetic_df)
    d_res = duckdb_exec.execute(plan, synthetic_df)

    assert p_res.success is True
    assert d_res.success is True
    assert p_res.value == d_res.value
    assert p_res.details["positive_count"] == d_res.details["positive_count"]
    assert p_res.details["total_rows"] == d_res.details["total_rows"]
    assert abs(p_res.details["rate"] - d_res.details["rate"]) < 1e-6


def test_group_metric_difference_median_parity(pandas_exec, duckdb_exec, synthetic_df):
    """Test difference in median total_amount between Credit Card and Debit Card."""
    plan = AnalyticalPlan(
        operation="group_metric_difference",
        target_column="total_amount",
        parameters={
            "value_column": "total_amount",
            "group_column": "payment_mode",
            "group_a": "Credit Card",
            "group_b": "Debit Card",
            "metric": "median",
            "absolute": True,
        },
    )
    p_res = pandas_exec.execute(plan, synthetic_df)
    d_res = duckdb_exec.execute(plan, synthetic_df)

    assert p_res.success is True
    assert d_res.success is True

    # Check parity
    assert p_res.details["group_a_count"] == d_res.details["group_a_count"]
    assert p_res.details["group_b_count"] == d_res.details["group_b_count"]
    assert p_res.details["group_a_value"] == d_res.details["group_a_value"]
    assert p_res.details["group_b_value"] == d_res.details["group_b_value"]
    assert p_res.details["abs_difference"] == d_res.details["abs_difference"]
    assert p_res.value == d_res.value


def test_group_metric_difference_mean_parity(pandas_exec, duckdb_exec, synthetic_df):
    """Test difference in mean total_amount between Enterprise and Consumer segments."""
    plan = AnalyticalPlan(
        operation="group_metric_difference",
        target_column="total_amount",
        parameters={
            "value_column": "total_amount",
            "group_column": "customer_segment",
            "group_a": "Enterprise",
            "group_b": "Consumer",
            "metric": "mean",
            "absolute": False,
        },
    )
    p_res = pandas_exec.execute(plan, synthetic_df)
    d_res = duckdb_exec.execute(plan, synthetic_df)

    assert p_res.success is True
    assert d_res.success is True
    assert p_res.details["group_a_count"] == d_res.details["group_a_count"]
    assert p_res.details["group_b_count"] == d_res.details["group_b_count"]
    assert abs(p_res.details["group_a_value"] - d_res.details["group_a_value"]) <= 0.01
    assert abs(p_res.details["group_b_value"] - d_res.details["group_b_value"]) <= 0.01
    assert abs(p_res.details["difference"] - d_res.details["difference"]) <= 0.01


def test_hybrid_executor_routing(hybrid_exec, synthetic_df):
    """Verify that HybridExecutor routes supported operations to DuckDB."""
    plan = AnalyticalPlan(
        operation="group_metric_difference",
        target_column="total_amount",
        parameters={
            "value_column": "total_amount",
            "group_column": "payment_mode",
            "group_a": "Credit Card",
            "group_b": "Debit Card",
            "metric": "median",
        },
    )
    assert hybrid_exec.duckdb_executor.can_handle(plan, synthetic_df) is True
    res = hybrid_exec.execute(plan, synthetic_df)
    assert res.success is True
    assert res.details.get("engine") == "duckdb"

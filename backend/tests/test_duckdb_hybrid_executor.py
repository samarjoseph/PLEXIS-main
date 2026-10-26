import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""
Automated tests for DuckDBExecutor and HybridExecutor in Plexis.

Covers:
  - Adapter execution of supported operations
  - Semantic parity with PandasExecutor
  - SQL safety and identifier quoting
  - Read-only preservation (zero mutation of DataFrame)
  - Thread isolation and concurrency
  - Hybrid routing and safe Pandas fallback
  - Feature toggle / rollback behavior
"""
import pytest
import pandas as pd
import numpy as np
import threading

from executor.duckdb_executor import duckdb_executor, DuckDBExecutor
from executor.pandas_executor import pandas_executor, PandasExecutor, ExecutorResult
from executor.hybrid_executor import hybrid_executor, HybridExecutor
from planner.schema import AnalyticalPlan


@pytest.fixture
def sample_df():
    """Create a realistic sample DataFrame with numeric, string, null, and binary columns."""
    return pd.DataFrame({
        "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "category": ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"],
        "sub_category": ["X", "X", "Y", "Y", "X", "Y", "X", "Y", "X", "Y"],
        "amount": [10.5, 20.0, 15.2, 30.1, 25.0, 40.5, 12.0, 35.5, 22.0, 50.0],
        "score": [100, 200, 150, 300, 250, 400, 120, 350, 220, 500],
        "nullable_val": [1.0, 2.0, None, 4.0, 5.0, None, 7.0, 8.0, 9.0, 10.0],
        "is_active": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        "status": ["Yes", "No", "Yes", "No", "Yes", "No", "Yes", "No", "Yes", "No"],
    })


# =============================================================================
# 1. Adapter & SQL Injection Safety Tests
# =============================================================================

def test_sql_identifier_quoting(sample_df):
    """Test that columns with spaces, quotes, and special characters are safely handled."""
    df_special = sample_df.copy()
    df_special['Column With Space'] = df_special['amount']
    df_special['Column"Quote'] = df_special['score']

    plan1 = AnalyticalPlan(operation="mean", target_column='Column With Space')
    assert duckdb_executor.can_execute(plan1, df_special) is True
    res1 = duckdb_executor.execute(plan1, df_special)
    assert res1.success is True
    assert res1.value == pytest.approx(df_special['amount'].mean(), rel=1e-3)

    plan2 = AnalyticalPlan(operation="mean", target_column='Column"Quote')
    assert duckdb_executor.can_execute(plan2, df_special) is True
    res2 = duckdb_executor.execute(plan2, df_special)
    assert res2.success is True
    assert res2.value == pytest.approx(df_special['score'].mean(), rel=1e-3)


def test_unsupported_operation_rejection(sample_df):
    """Unsupported operations should be rejected by can_execute."""
    plan = AnalyticalPlan(operation="some_unsupported_random_op", target_column="amount")
    assert duckdb_executor.can_execute(plan, sample_df) is False


def test_invalid_column_rejection(sample_df):
    """Plans referencing nonexistent columns should not execute."""
    plan = AnalyticalPlan(operation="mean", target_column="nonexistent_column_xyz")
    assert duckdb_executor.can_execute(plan, sample_df) is False


# =============================================================================
# 2. Semantic Parity Tests (DuckDB vs Pandas Reference)
# =============================================================================

@pytest.mark.parametrize("op", ["count", "mean", "sum", "min", "max", "median", "range"])
def test_scalar_parity(sample_df, op):
    """Compare scalar calculations between PandasExecutor and DuckDBExecutor."""
    plan = AnalyticalPlan(operation=op, target_column="amount")
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)

    assert pd_res.success is True
    assert duck_res.success is True
    assert duck_res.value == pytest.approx(pd_res.value, rel=1e-3)


def test_nunique_parity(sample_df):
    plan = AnalyticalPlan(operation="nunique", target_column="category")
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)
    assert pd_res.success is True
    assert duck_res.success is True
    assert duck_res.value == pd_res.value == 2


def test_missing_count_column_parity(sample_df):
    plan = AnalyticalPlan(operation="missing_count_column", target_column="nullable_val")
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)
    assert pd_res.success is True
    assert duck_res.success is True
    assert duck_res.value == pd_res.value == 2


@pytest.mark.parametrize("group_op", ["group_mean", "group_sum", "group_count", "group_min", "group_max", "group_median"])
def test_group_by_parity(sample_df, group_op):
    plan = AnalyticalPlan(
        operation=group_op,
        target_column="category",
        parameters={"group_by": "category", "value_column": "amount"}
    )
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)

    assert pd_res.success is True
    assert duck_res.success is True
    assert set(duck_res.value.keys()) == set(pd_res.value.keys())
    for k in pd_res.value:
        assert duck_res.value[k] == pytest.approx(pd_res.value[k], rel=1e-3)


def test_grouped_rate_parity(sample_df):
    plan = AnalyticalPlan(
        operation="grouped_rate",
        target_column="status",
        parameters={"group_by": "category", "target_value": "Yes", "sort_by": "rate"}
    )
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)

    assert pd_res.success is True
    assert duck_res.success is True
    assert set(duck_res.value.keys()) == set(pd_res.value.keys())
    for k in pd_res.value:
        assert duck_res.value[k]["rate"] == pytest.approx(pd_res.value[k]["rate"], rel=1e-3)
        assert duck_res.value[k]["numerator"] == pd_res.value[k]["numerator"]
        assert duck_res.value[k]["denominator"] == pd_res.value[k]["denominator"]


def test_two_factor_aggregation_parity(sample_df):
    plan = AnalyticalPlan(
        operation="two_factor_aggregation",
        target_column="amount",
        parameters={"group_by": "category", "secondary_group": "sub_category", "value_column": "amount", "metric": "mean"}
    )
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)

    assert pd_res.success is True
    assert duck_res.success is True
    assert len(duck_res.value) == len(pd_res.value)


def test_compound_filter_parity(sample_df):
    plan = AnalyticalPlan(
        operation="compound_filter",
        target_column="amount",
        parameters={
            "conditions": [
                {"column": "amount", "operator": ">=", "value": 20.0},
                {"column": "score", "operator": "<", "value": 450}
            ],
            "value_column": "amount",
            "target_column": "is_active"
        }
    )
    pd_res = pandas_executor.execute(plan, sample_df)
    duck_res = duckdb_executor.execute(plan, sample_df)

    assert pd_res.success is True
    assert duck_res.success is True
    assert duck_res.value["count"] == pd_res.value["count"]
    assert duck_res.value["total"] == pd_res.value["total"]
    assert duck_res.value["mean_value"] == pytest.approx(pd_res.value["mean_value"], rel=1e-2)


# =============================================================================
# 3. Read-Only Safety & Non-Mutation Tests
# =============================================================================

def test_dataframe_immutability(sample_df):
    """Ensure that DuckDB execution does not mutate original DataFrame."""
    df_copy = sample_df.copy(deep=True)
    plan = AnalyticalPlan(operation="mean", target_column="amount")
    duckdb_executor.execute(plan, sample_df)

    pd.testing.assert_frame_equal(sample_df, df_copy)


# =============================================================================
# 4. Concurrency & Isolation Tests
# =============================================================================

def test_thread_isolation():
    """Verify concurrent requests executing queries on different DataFrames do not leak."""
    results = {}

    def run_query(thread_id, val):
        df_t = pd.DataFrame({"x": [val] * 100})
        plan = AnalyticalPlan(operation="mean", target_column="x")
        res = duckdb_executor.execute(plan, df_t)
        results[thread_id] = res.value

    threads = [threading.Thread(target=run_query, args=(i, i * 10.0)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i in range(10):
        assert results[i] == pytest.approx(i * 10.0, rel=1e-3)


# =============================================================================
# 5. HybridExecutor Routing & Fallback Tests
# =============================================================================

def test_hybrid_executor_routing(sample_df):
    """Test that supported operations route to DuckDB and set engine=duckdb."""
    hybrid_executor.reset_stats()
    plan = AnalyticalPlan(operation="mean", target_column="amount")

    res = hybrid_executor.execute(plan, sample_df)
    assert res.success is True
    assert res.details.get("engine") == "duckdb"
    assert hybrid_executor.get_stats()["duckdb_executions"] >= 1


def test_hybrid_executor_unsupported_fallback(sample_df):
    """Test that unsupported operations safely route to Pandas."""
    hybrid_executor.reset_stats()
    # 'dataset_profile' is retained exclusively in Pandas
    plan = AnalyticalPlan(operation="dataset_profile")

    res = hybrid_executor.execute(plan, sample_df)
    assert res.success is True
    assert res.details.get("engine") == "pandas"
    assert hybrid_executor.get_stats()["pandas_executions"] >= 1


def test_hybrid_executor_feature_flag_disable(sample_df):
    """Test that setting DuckDB enabled to False routes all queries to Pandas."""
    hybrid_executor.reset_stats()
    hybrid_executor.set_duckdb_enabled(False)
    try:
        plan = AnalyticalPlan(operation="mean", target_column="amount")
        res = hybrid_executor.execute(plan, sample_df)
        assert res.success is True
        assert res.details.get("engine") == "pandas"
        assert hybrid_executor.get_stats()["duckdb_executions"] == 0
        assert hybrid_executor.get_stats()["pandas_executions"] == 1
    finally:
        hybrid_executor.reset_duckdb_override()

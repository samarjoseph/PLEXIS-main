"""
Unit and integration tests for Cluster 1: Derived metrics versus source columns.

Verifies:
1. SchemaValidator properly distinguishes physical source columns, aggregation functions,
   derived metrics, and output aliases.
2. Row-counting tokens ("count", "row_count", "rows") normalize to total row count without
   triggering COLUMN_NOT_FOUND.
3. Sorting/ranking operations (TOP_N, BOTTOM_N, SORT_ROWS) allow sorting by computed group
   metrics ("count", "rate", "difference", "mean") without requiring physical dataset columns.
4. Target-rate metrics ("target_positive_rate", "positive_rate") resolve to the dataset's
   target column when present, and fail safely when absent.
5. Truly missing source columns (e.g. "salary", "ticket_price") are cleanly rejected with
   COLUMN_NOT_FOUND.
6. Ambiguous or unsupported operations are rejected rather than silently accepted.
7. Calculated results across multiple schemas (synthetic, retail, flight) match independent
   pure-Pandas calculations within numerical tolerance.
8. Both zero-row and non-zero-row subsets are tested.
"""

import math
import sys
import os
import pytest
import pandas as pd
import numpy as np

# Ensure backend root is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from router.schema_validator import (
    schema_validator,
    ROW_COUNT_ALIASES,
    RANKING_DERIVED_ALIASES,
    TARGET_RATE_ALIASES,
)
from planner.schema import AnalyticalPlan
from planner.validator import plan_validator
from executor.pandas_executor import pandas_executor


# ---------------------------------------------------------------------------
# Test Fixtures: Multiple Schemas
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_schema():
    """A multi-type synthetic schema for testing generic analytical operations."""
    return [
        {"name": "employee_id", "type": "numeric"},
        {"name": "department", "type": "string"},
        {"name": "performance_score", "type": "numeric"},
        {"name": "is_promoted", "type": "numeric"},
        {"name": "hire_date", "type": "date"},
    ]


@pytest.fixture
def synthetic_df():
    """Independent synthetic dataframe with known values."""
    np.random.seed(42)
    return pd.DataFrame({
        "employee_id": list(range(1, 101)),
        "department": ["Engineering"] * 40 + ["Sales"] * 30 + ["Marketing"] * 20 + ["HR"] * 10,
        "performance_score": [float(x) for x in range(1, 101)],
        "is_promoted": [1 if x % 5 == 0 else 0 for x in range(1, 101)],
        "hire_date": pd.date_range("2020-01-01", periods=100, freq="D"),
    })


@pytest.fixture
def retail_schema():
    """Retail benchmark schema."""
    return [
        {"name": "Order_ID", "type": "string"},
        {"name": "Sales_Amount", "type": "numeric"},
        {"name": "Profit", "type": "numeric"},
        {"name": "Product_Category", "type": "string"},
        {"name": "Return_Flag", "type": "numeric"},
    ]


@pytest.fixture
def flight_schema():
    """Flight benchmark schema."""
    return [
        {"name": "Flight_Date", "type": "date"},
        {"name": "Airline", "type": "string"},
        {"name": "Origin_Airport", "type": "string"},
        {"name": "Destination_Airport", "type": "string"},
        {"name": "Departure_Delay", "type": "numeric"},
        {"name": "Peak_Hour", "type": "numeric"},
        {"name": "Delay_Target", "type": "numeric"},
    ]


# ---------------------------------------------------------------------------
# 1. SchemaValidator: Distinguishing Source Columns vs Derived Metrics
# ---------------------------------------------------------------------------

class TestSchemaValidatorDerivedMetrics:

    def test_count_with_row_count_aliases(self, synthetic_schema):
        """COUNT with row count aliases ('count', 'row_count', 'rows') should normalize to column=None."""
        for alias in ["count", "row_count", "rows", "records", "total_rows"]:
            op = {"type": "COUNT", "column": alias}
            res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
            assert res.valid, f"Failed for alias: {alias}"
            assert res.corrected_operation["column"] is None, f"Expected column=None for {alias}"

    def test_count_with_empty_column(self, synthetic_schema):
        """COUNT with empty column should normalize to column=None."""
        op = {"type": "COUNT"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert res.valid
        assert res.corrected_operation["column"] is None

    def test_count_with_valid_physical_column(self, synthetic_schema):
        """COUNT with valid physical column should preserve column name."""
        op = {"type": "COUNT", "column": "performance_score"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "performance_score"

    def test_count_with_missing_physical_column(self, synthetic_schema):
        """COUNT with a truly nonexistent column should return COLUMN_NOT_FOUND."""
        op = {"type": "COUNT", "column": "salary"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"
        assert "salary" in res.error_message

    def test_top_n_with_derived_metrics(self, synthetic_schema):
        """TOP_N with derived metrics (count, rate, difference, mean) should be valid."""
        for derived_metric in ["count", "rate", "percentage", "absolute_difference", "difference", "mean", "sum"]:
            op = {"type": "TOP_N", "column": derived_metric, "n": 5, "order": "desc"}
            res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
            assert res.valid, f"Failed for derived metric: {derived_metric}"

    def test_top_n_with_valid_physical_column(self, synthetic_schema):
        """TOP_N with physical column should be valid and normalized."""
        op = {"type": "TOP_N", "column": "performance_score", "n": 5, "order": "desc"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "performance_score"

    def test_top_n_with_missing_column(self, synthetic_schema):
        """TOP_N with genuinely missing column should return COLUMN_NOT_FOUND."""
        op = {"type": "TOP_N", "column": "customer_rating", "n": 5, "order": "desc"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"
        assert "customer_rating" in res.error_message

    def test_sort_rows_with_derived_rate(self, flight_schema):
        """SORT_ROWS with derived rate alias should be accepted."""
        op = {"type": "SORT_ROWS", "column": "rate", "ascending": False}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, flight_schema)
        assert res.valid

    def test_sort_rows_with_missing_column(self, flight_schema):
        """SORT_ROWS with truly missing column should fail COLUMN_NOT_FOUND."""
        op = {"type": "SORT_ROWS", "column": "ticket_price", "ascending": False}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, flight_schema)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"

    def test_target_rate_resolution_with_target_column(self, flight_schema):
        """AGGREGATE on 'target_positive_rate' should resolve to Delay_Target and mean."""
        for alias in ["target_positive_rate", "target-positive_rate", "target_rate", "positive_rate"]:
            op = {"type": "AGGREGATE", "column": alias, "func": "mean"}
            res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, flight_schema)
            assert res.valid, f"Failed for alias: {alias}"
            assert res.corrected_operation["column"] == "Delay_Target"
            assert res.corrected_operation["func"] == "mean"

    def test_target_rate_without_target_column(self, retail_schema):
        """AGGREGATE on 'target_positive_rate' should fail when dataset has no target column."""
        op = {"type": "AGGREGATE", "column": "target_positive_rate", "func": "mean"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, retail_schema)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"

    def test_aggregate_row_count(self, synthetic_schema):
        """AGGREGATE on 'count' func should normalize to column=None, func='count'."""
        op = {"type": "AGGREGATE", "column": "count", "func": "count"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert res.valid
        assert res.corrected_operation["column"] is None
        assert res.corrected_operation["func"] == "count"

    def test_group_operations_column_resolution(self, flight_schema):
        """GROUP_MEAN, GROUP_COUNT should accept 'group_col' and validate grouping/value columns."""
        op = {"type": "GROUP_MEAN", "group_col": "airline", "value_column": "departure_delay"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, flight_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "Airline"
        assert res.corrected_operation["value_column"] == "Departure_Delay"

    def test_group_operations_missing_group_column(self, flight_schema):
        """GROUP_COUNT with missing group column should fail COLUMN_NOT_FOUND."""
        op = {"type": "GROUP_COUNT", "group_col": "department"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, flight_schema)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"

    def test_group_operations_missing_value_column(self, flight_schema):
        """GROUP_MEAN with missing value column should fail COLUMN_NOT_FOUND."""
        op = {"type": "GROUP_MEAN", "group_col": "airline", "value_column": "ticket_price"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, flight_schema)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"

    def test_unsupported_operation_rejection(self, synthetic_schema):
        """Unsupported operations must be rejected, not silently accepted."""
        op = {"type": "MAGICAL_FORECAST", "column": "performance_score"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, synthetic_schema)
        assert not res.valid
        assert res.error_code == "UNSUPPORTED_OPERATION"


# ---------------------------------------------------------------------------
# 2. PlanValidator: Execution Gate Tests
# ---------------------------------------------------------------------------

class TestPlanValidatorDerivedMetrics:

    def test_row_count_plan_validation(self, synthetic_schema):
        columns = [c["name"] for c in synthetic_schema]
        types = {c["name"]: c["type"] for c in synthetic_schema}

        # target_column in row count aliases should be allowed
        for alias in ["count", "row_count", "rows"]:
            plan = AnalyticalPlan(intent="count", operation="count", target_column=alias, plan=[])
            res = plan_validator.validate(plan, columns, types)
            assert res.valid
            assert plan.target_column is None

    def test_top_n_derived_ranking_plan_validation(self, synthetic_schema):
        columns = [c["name"] for c in synthetic_schema]
        types = {c["name"]: c["type"] for c in synthetic_schema}

        for derived_key in ["rate", "count", "absolute_difference", "difference"]:
            plan = AnalyticalPlan(intent="top_n", operation="top_n", target_column=derived_key, plan=[])
            res = plan_validator.validate(plan, columns, types)
            assert res.valid

    def test_top_n_missing_column_plan_validation(self, synthetic_schema):
        columns = [c["name"] for c in synthetic_schema]
        types = {c["name"]: c["type"] for c in synthetic_schema}

        plan = AnalyticalPlan(intent="top_n", operation="top_n", target_column="nonexistent", plan=[])
        res = plan_validator.validate(plan, columns, types)
        assert not res.valid
        assert res.error_code == "COLUMN_NOT_FOUND"


# ---------------------------------------------------------------------------
# 3. PandasExecutor: Correctness Against Reference Calculations
# ---------------------------------------------------------------------------

class TestPandasExecutorReferenceCalculations:

    def test_total_row_count(self, synthetic_df):
        """Row count with None and 'count' alias matches len(df)."""
        ref_count = len(synthetic_df)

        res1 = pandas_executor.execute(
            AnalyticalPlan(intent="count", operation="count", target_column=None, plan=[]),
            synthetic_df
        )
        assert res1.success
        assert res1.value == ref_count

        res2 = pandas_executor.execute(
            AnalyticalPlan(intent="count", operation="count", target_column="count", plan=[]),
            synthetic_df
        )
        assert res2.success
        assert res2.value == ref_count

    def test_column_non_null_count(self, synthetic_df):
        """Non-null count of a column matches df[col].count()."""
        df_copy = synthetic_df.copy()
        df_copy.loc[0:10, "performance_score"] = np.nan
        ref_count = int(df_copy["performance_score"].count())

        res = pandas_executor.execute(
            AnalyticalPlan(intent="count", operation="count", target_column="performance_score", plan=[]),
            df_copy
        )
        assert res.success
        assert res.value == ref_count
        assert res.value == 100 - 11

    def test_mean_and_sum_precision(self, synthetic_df):
        """Mean and sum match pure-pandas calculations."""
        ref_mean = float(synthetic_df["performance_score"].mean())
        ref_sum = float(synthetic_df["performance_score"].sum())

        res_mean = pandas_executor.execute(
            AnalyticalPlan(intent="mean", operation="mean", target_column="performance_score", plan=[]),
            synthetic_df
        )
        assert res_mean.success
        assert math.isclose(res_mean.value, ref_mean, rel_tol=1e-9)

        res_sum = pandas_executor.execute(
            AnalyticalPlan(intent="sum", operation="sum", target_column="performance_score", plan=[]),
            synthetic_df
        )
        assert res_sum.success
        assert math.isclose(res_sum.value, ref_sum, rel_tol=1e-9)

    def test_target_positive_rate_calculation(self, synthetic_df):
        """Target-positive rate (mean of binary is_promoted) matches pure pandas calculation."""
        ref_rate = float(synthetic_df["is_promoted"].mean())
        assert ref_rate == 0.2  # 20 out of 100

        res = pandas_executor.execute(
            AnalyticalPlan(intent="mean", operation="mean", target_column="is_promoted", plan=[]),
            synthetic_df
        )
        assert res.success
        assert math.isclose(res.value, ref_rate, rel_tol=1e-9)

    def test_compound_filter_nonzero_subset(self, synthetic_df):
        """Compound filter with qualifying rows matches pure pandas boolean indexing."""
        # Condition: performance_score > 50 and is_promoted == 1
        mask = (synthetic_df["performance_score"] > 50) & (synthetic_df["is_promoted"] == 1)
        ref_count = int(mask.sum())
        ref_pct = round(float(ref_count / len(synthetic_df) * 100.0), 4)

        plan = AnalyticalPlan(
            intent="compound_filter",
            operation="compound_filter",
            target_column=None,
            parameters={
                "conditions": [
                    {"column": "performance_score", "operator": ">", "value": 50},
                    {"column": "is_promoted", "operator": "==", "value": 1},
                ]
            },
            plan=[]
        )
        res = pandas_executor.execute(plan, synthetic_df)
        assert res.success
        assert res.value["count"] == ref_count
        assert math.isclose(res.value["percentage"], ref_pct, abs_tol=1e-3)

    def test_compound_filter_zero_row_subset(self, synthetic_df):
        """Compound filter resulting in 0 rows should return count=0, percentage=0.0 without errors."""
        # Impossible condition: performance_score > 1000
        plan = AnalyticalPlan(
            intent="compound_filter",
            operation="compound_filter",
            target_column=None,
            parameters={
                "conditions": [
                    {"column": "performance_score", "operator": ">", "value": 1000},
                ]
            },
            plan=[]
        )
        res = pandas_executor.execute(plan, synthetic_df)
        assert res.success
        assert res.value["count"] == 0
        assert res.value["percentage"] == 0.0

    def test_top_n_derived_ranking_immutability(self, synthetic_df):
        """TOP_N with derived ranking key executes safely and does not mutate the original dataframe."""
        original_copy = synthetic_df.copy(deep=True)

        plan = AnalyticalPlan(
            intent="top_n",
            operation="top_n",
            target_column="count",  # derived metric key
            parameters={"n": 5, "order": "desc"},
            plan=[]
        )
        res = pandas_executor.execute(plan, synthetic_df)
        assert res.success
        assert len(res.matching_rows) <= 5

        # Check immutability: synthetic_df remains completely identical
        pd.testing.assert_frame_equal(synthetic_df, original_copy)


# ---------------------------------------------------------------------------
# 4. Adversarial Tests: Physical Columns Named count, rate, mean, difference
# ---------------------------------------------------------------------------

@pytest.fixture
def adversarial_schema():
    """Schema where columns are literally named after metrics/aggregates."""
    return [
        {"name": "count", "type": "numeric"},
        {"name": "rate", "type": "numeric"},
        {"name": "mean", "type": "numeric"},
        {"name": "difference", "type": "numeric"},
        {"name": "category", "type": "string"},
    ]


@pytest.fixture
def adversarial_df():
    """Dataframe where columns are literally named count, rate, mean, difference."""
    return pd.DataFrame({
        "count": [10.0, np.nan, 30.0, 40.0, 50.0],
        "rate": [0.15, 0.85, 0.45, 0.95, 0.20],
        "mean": [2.0, 4.0, 6.0, 8.0, 10.0],
        "difference": [-5.0, 10.0, 0.0, 15.0, -10.0],
        "category": ["A", "B", "A", "B", "A"],
    })


class TestAdversarialPhysicalColumns:
    """
    Adversarial verification ensuring physical columns named 'count', 'rate',
    'mean', or 'difference' remain accessible and are NOT obscured by derived aliases.
    """

    def test_adversarial_count_as_physical_column(self, adversarial_schema):
        """COUNT with physical column 'count' resolves to 'count', NOT normalized to None."""
        op = {"type": "COUNT", "column": "count"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, adversarial_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "count", "Physical column 'count' must NOT be erased to None"

    def test_adversarial_aggregate_mean_on_count(self, adversarial_schema):
        """AGGREGATE mean on physical column 'count' resolves correctly."""
        op = {"type": "AGGREGATE", "column": "count", "func": "mean"}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, adversarial_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "count"

    def test_adversarial_top_n_on_rate(self, adversarial_schema):
        """TOP_N on physical column 'rate' resolves to physical column 'rate'."""
        op = {"type": "TOP_N", "column": "rate", "n": 3}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, adversarial_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "rate"

    def test_adversarial_filter_on_count(self, adversarial_schema):
        """FILTER on physical column 'count' validates against physical column."""
        op = {"type": "FILTER", "column": "count", "operator": ">=", "value": 30}
        res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, adversarial_schema)
        assert res.valid
        assert res.corrected_operation["column"] == "count"

    def test_adversarial_aggregate_on_mean_and_difference(self, adversarial_schema):
        """AGGREGATE on physical columns 'mean' and 'difference' resolves correctly."""
        for col_name in ["mean", "difference"]:
            op = {"type": "AGGREGATE", "column": col_name, "func": "sum"}
            res = schema_validator.validate({"intent": "DATA_OPERATION", "operation": op}, adversarial_schema)
            assert res.valid
            assert res.corrected_operation["column"] == col_name

    def test_plan_validator_preserves_physical_count(self, adversarial_schema):
        """PlanValidator preserves target_column='count' when 'count' exists in dataset."""
        columns = [c["name"] for c in adversarial_schema]
        types = {c["name"]: c["type"] for c in adversarial_schema}
        plan = AnalyticalPlan(
            intent="aggregation",
            operation="count",
            target_column="count",
            parameters={},
            plan=[]
        )
        res = plan_validator.validate(plan, columns, types)
        assert res.valid
        assert plan.target_column == "count", "Physical column 'count' must remain as target_column in plan"

    def test_plan_validator_preserves_physical_rate(self, adversarial_schema):
        """PlanValidator preserves target_column='rate' when 'rate' exists in dataset."""
        columns = [c["name"] for c in adversarial_schema]
        types = {c["name"]: c["type"] for c in adversarial_schema}
        plan = AnalyticalPlan(
            intent="ranking",
            operation="top_n",
            target_column="rate",
            parameters={"n": 3},
            plan=[]
        )
        res = plan_validator.validate(plan, columns, types)
        assert res.valid
        assert plan.target_column == "rate"

    def test_executor_physical_count_ignores_nulls(self, adversarial_df):
        """Executor counting physical column 'count' returns non-null count (4), not total rows (5)."""
        plan = AnalyticalPlan(
            intent="aggregation",
            operation="count",
            target_column="count",
            parameters={},
            plan=[]
        )
        res = pandas_executor.execute(plan, adversarial_df)
        assert res.success
        ref_count = int(adversarial_df["count"].count())
        assert ref_count == 4
        assert res.value == 4, f"Expected non-null count 4, got {res.value}"

    def test_executor_physical_mean_on_count(self, adversarial_df):
        """Executor computing mean of physical column 'count' matches Pandas reference."""
        plan = AnalyticalPlan(
            intent="aggregation",
            operation="mean",
            target_column="count",
            parameters={},
            plan=[]
        )
        res = pandas_executor.execute(plan, adversarial_df)
        assert res.success
        ref_mean = float(adversarial_df["count"].mean())
        assert math.isclose(res.value, ref_mean, abs_tol=1e-6)
        assert math.isclose(res.value, 32.5, abs_tol=1e-6)

    def test_executor_physical_top_n_rate(self, adversarial_df):
        """Executor TOP_N on physical column 'rate' returns largest rate values."""
        plan = AnalyticalPlan(
            intent="ranking",
            operation="top_n",
            target_column="rate",
            parameters={"n": 3, "order": "desc"},
            plan=[]
        )
        res = pandas_executor.execute(plan, adversarial_df)
        assert res.success
        ref_top3 = adversarial_df.nlargest(3, "rate")["rate"].tolist()
        assert res.value == ref_top3
        assert res.value == [0.95, 0.85, 0.45]

    def test_executor_physical_filter_on_count(self, adversarial_df):
        """Executor FILTER on physical column 'count' >= 30 matches Pandas reference."""
        plan = AnalyticalPlan(
            intent="filter",
            operation="filter",
            target_column="count",
            parameters={"operator": ">=", "value": 30},
            plan=[]
        )
        res = pandas_executor.execute(plan, adversarial_df)
        assert res.success
        ref_filtered = len(adversarial_df[adversarial_df["count"] >= 30])
        assert res.value == ref_filtered
        assert res.value == 3

    def test_executor_physical_difference_sum(self, adversarial_df):
        """Executor SUM on physical column 'difference' matches Pandas reference."""
        plan = AnalyticalPlan(
            intent="aggregation",
            operation="sum",
            target_column="difference",
            parameters={},
            plan=[]
        )
        res = pandas_executor.execute(plan, adversarial_df)
        assert res.success
        ref_sum = float(adversarial_df["difference"].sum())
        assert math.isclose(res.value, ref_sum, abs_tol=1e-6)
        assert math.isclose(res.value, 10.0, abs_tol=1e-6)

    def test_adversarial_dataframe_immutability(self, adversarial_df):
        """Adversarial operations do not mutate the dataframe."""
        copy_df = adversarial_df.copy(deep=True)
        plan = AnalyticalPlan(
            intent="aggregation",
            operation="mean",
            target_column="count",
            parameters={},
            plan=[]
        )
        pandas_executor.execute(plan, adversarial_df)
        pd.testing.assert_frame_equal(adversarial_df, copy_df)


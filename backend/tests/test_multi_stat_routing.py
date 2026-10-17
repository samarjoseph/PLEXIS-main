"""
Unit and integration tests for Cluster 3: Multi-statistic / describe column routing.

Verifies:
1. Negative lookahead in master_router does NOT falsely block single-column summary
   requests containing English prepositions ("by the dataset's definition", "across all rows",
   "defined by", "accompanied by standard deviation").
2. Genuine grouping queries ("by department", "for each airline", "per region", "across categories")
   and hypothetical queries ("if every row with X were excluded") are strictly excluded from
   single-column DESCRIBE_COLUMN fast-path.
3. Multi-statistic DESCRIBE_COLUMN operations reach execution and return exact numerical
   values matching independently calculated Pandas ground truth.
4. Dataset immutability is preserved across all executions.
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

from router.master_router import master_router
from planner.schema import AnalyticalPlan
from executor.pandas_executor import pandas_executor
from core.normalization import QueryNormalizer
from core.context import ExecutionContext


# ---------------------------------------------------------------------------
# Test Fixtures: Multiple Schemas
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_df():
    """Synthetic dataframe with multiple numeric and categorical columns."""
    np.random.seed(42)
    return pd.DataFrame({
        "employee_id": list(range(1, 101)),
        "department": ["Engineering"] * 40 + ["Sales"] * 30 + ["Marketing"] * 20 + ["HR"] * 10,
        "salary": [float(30000 + x * 500) for x in range(100)],
        "performance_score": [float(x % 5 + 1) for x in range(100)],
        "overtime_hours": [float(x % 15) for x in range(100)],
    })


@pytest.fixture
def flight_df():
    """Flight dataset subset for Q09 verification."""
    csv_path = os.path.join(BASE_DIR, "storage", "uploads", "india_flight_delay_model_input.csv")
    if os.path.exists(csv_path):
        return pd.read_csv(csv_path)
    # Synthetic fallback matching exact schema
    return pd.DataFrame({
        "Departure_Delay": [0.0, 10.0, 47.0, 80.0, 119.0] * 1000,
        "Airline": ["IndiGo", "Air India", "SpiceJet", "Vistara", "Fly91"] * 1000,
    })


@pytest.fixture
def retail_df():
    """Retail dataset subset for Q14 verification."""
    csv_path = os.path.join(BASE_DIR, "storage", "uploads", "sample-100-rows_02878d97e94b411bbbc0a60f70557e0d.csv")
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        if "Customer_Age" in df.columns:
            return df
    return pd.DataFrame({
        "Customer_Age": [4.0, 25.0, 39.0, 60.0, 112.0] * 100,
        "Sales_Amount": [100.0, 250.0, 450.0, 800.0, 1200.0] * 100,
        "Department": ["Electronics", "Clothing", "Home", "Books", "Toys"] * 100,
    })


# ---------------------------------------------------------------------------
# 1. Targeted Positive Cases: Must Route to DESCRIBE_COLUMN
# ---------------------------------------------------------------------------

class TestMultiStatPositiveRouting:

    def test_q09_flight_query_routing(self, flight_df):
        """Q09 with 'supported by the dataset's definition' must route to DESCRIBE_COLUMN for Departure_Delay."""
        q = (
            "What are the minimum, maximum, mean, and median values of Departure_Delay? "
            "Report the units only if supported by the dataset's definition."
        )
        known_cols = {c.lower(): c for c in flight_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=flight_df, cols_override=known_cols)
        assert res is not None, "Q09 must NOT be blocked by negative lookahead"
        assert res["intent"] == "DATA_OPERATION"
        ops = res.get("operations", [])
        assert len(ops) == 1
        assert ops[0]["type"] == "DESCRIBE_COLUMN"
        assert ops[0]["column"] == "Departure_Delay"
        assert "mean" in ops[0]["metrics"]
        assert "median" in ops[0]["metrics"]
        assert "min" in ops[0]["metrics"]
        assert "max" in ops[0]["metrics"]

    def test_q14_retail_query_routing(self, retail_df):
        """Q14 from retail benchmark must route to DESCRIBE_COLUMN for Customer_Age."""
        q = "What are the mean, median, minimum, and maximum customer ages?"
        known_cols = {c.lower(): c for c in retail_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=retail_df, cols_override=known_cols)
        assert res is not None
        assert res["intent"] == "DATA_OPERATION"
        ops = res.get("operations", [])
        assert len(ops) == 1
        assert ops[0]["type"] == "DESCRIBE_COLUMN"
        assert ops[0]["column"] == "Customer_Age"

    def test_across_all_rows_routing(self, synthetic_df):
        """Query containing 'across all rows' must route to DESCRIBE_COLUMN, not blocked by 'across'."""
        q = "Show the mean, median, min, and max for salary across all rows."
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        assert res is not None
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == "salary"

    def test_across_the_dataset_routing(self, synthetic_df):
        """Query containing 'across the dataset' must route to DESCRIBE_COLUMN."""
        q = "Report the minimum, maximum, mean, and median of performance_score across the dataset."
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        assert res is not None
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == "performance_score"

    def test_accompanied_by_standard_deviation_routing(self, synthetic_df):
        """Query containing 'accompanied by standard deviation' must route to DESCRIBE_COLUMN."""
        q = "Calculate the mean, median, min, and max of salary accompanied by standard deviation."
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        assert res is not None
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == "salary"

    def test_defined_by_dataset_routing(self, synthetic_df):
        """Query containing 'as defined by the dataset' must route to DESCRIBE_COLUMN."""
        q = "Give me the mean and median for overtime_hours as defined by the dataset."
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        assert res is not None
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == "overtime_hours"


# ---------------------------------------------------------------------------
# 2. Targeted Negative Cases: Must NOT Route to Single-Column DESCRIBE_COLUMN
# ---------------------------------------------------------------------------

class TestMultiStatNegativeRouting:

    def test_grouped_by_department_excluded(self, synthetic_df):
        """'by department' is a grouping query and must NOT route to single-column DESCRIBE_COLUMN."""
        q = "What are the mean and median salary by department?"
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        # Should not be DESCRIBE_COLUMN
        if res is not None:
            op_type = res.get("operations", [{}])[0].get("type")
            assert op_type != "DESCRIBE_COLUMN", f"Grouped query was misrouted to {op_type}"

    def test_for_each_category_excluded(self, synthetic_df):
        """'for each department' is a grouping query and must NOT route to DESCRIBE_COLUMN."""
        q = "What are the mean and median salaries for each department?"
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            assert res.get("operations", [{}])[0].get("type") != "DESCRIBE_COLUMN"

    def test_per_region_excluded(self, synthetic_df):
        """'per department' is a grouping query and must NOT route to DESCRIBE_COLUMN."""
        q = "What are the mean and median performance scores per department?"
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            assert res.get("operations", [{}])[0].get("type") != "DESCRIBE_COLUMN"

    def test_across_categories_excluded(self, synthetic_df):
        """'across departments' is a grouping query and must NOT route to single-column describe."""
        q = "Compare the mean and median salary across departments."
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            assert res.get("operations", [{}])[0].get("type") != "DESCRIBE_COLUMN"

    def test_hypothetical_excluded_query_excluded(self, synthetic_df):
        """Hypothetical simulation query must NOT route to single-column describe."""
        q = "If every row with overtime_hours > 10 were temporarily excluded, what would the mean and median salary be?"
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(None, q, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            assert res.get("operations", [{}])[0].get("type") != "DESCRIBE_COLUMN"


# ---------------------------------------------------------------------------
# 3. Execution & Pandas Reference Calculation Matches
# ---------------------------------------------------------------------------

class TestMultiStatExecutionAgainstPandasReference:

    def test_q09_execution_matches_flight_ground_truth(self, flight_df):
        """Executing DESCRIBE_COLUMN on Departure_Delay returns exact benchmark ground truth."""
        plan = AnalyticalPlan(
            intent="describe_column",
            operation="describe_column",
            target_column="Departure_Delay",
            parameters={"metrics": ["min", "max", "mean", "median"]},
            plan=[]
        )
        res = pandas_executor.execute(plan, flight_df)
        assert res.success
        val = res.value

        # Pure Pandas reference calculations
        s = flight_df["Departure_Delay"].dropna()
        ref_min = float(s.min())
        ref_max = float(s.max())
        ref_mean = float(s.mean())
        ref_median = float(s.median())

        assert math.isclose(val["min"], ref_min, abs_tol=1e-6)
        assert math.isclose(val["max"], ref_max, abs_tol=1e-6)
        assert math.isclose(val["mean"], ref_mean, abs_tol=1e-4)
        assert math.isclose(val["median"], ref_median, abs_tol=1e-6)

        # Compare against flight benchmark ground truth: min 0, max 119, mean 42.6643, median 47.0
        if len(flight_df) >= 150000:
            assert math.isclose(val["min"], 0.0, abs_tol=1e-6)
            assert math.isclose(val["max"], 119.0, abs_tol=1e-6)
            assert math.isclose(val["mean"], 42.6643, abs_tol=1e-4)
            assert math.isclose(val["median"], 47.0, abs_tol=1e-6)

    def test_synthetic_describe_execution_matches_pandas(self, synthetic_df):
        """Executing DESCRIBE_COLUMN on synthetic salary matches Pandas reference."""
        plan = AnalyticalPlan(
            intent="describe_column",
            operation="describe_column",
            target_column="salary",
            parameters={"metrics": ["min", "max", "mean", "median", "std"]},
            plan=[]
        )
        res = pandas_executor.execute(plan, synthetic_df)
        assert res.success
        val = res.value

        s = synthetic_df["salary"]
        assert math.isclose(val["min"], float(s.min()), abs_tol=1e-6)
        assert math.isclose(val["max"], float(s.max()), abs_tol=1e-6)
        assert math.isclose(val["mean"], float(s.mean()), abs_tol=1e-6)
        assert math.isclose(val["median"], float(s.median()), abs_tol=1e-6)
        assert math.isclose(val["std"], float(s.std()), abs_tol=1e-6)

    def test_describe_column_immutability(self, synthetic_df):
        """DESCRIBE_COLUMN execution does not mutate the dataframe."""
        orig_copy = synthetic_df.copy(deep=True)
        plan = AnalyticalPlan(
            intent="describe_column",
            operation="describe_column",
            target_column="salary",
            parameters={"metrics": ["min", "max", "mean", "median"]},
            plan=[]
        )
        pandas_executor.execute(plan, synthetic_df)
        pd.testing.assert_frame_equal(synthetic_df, orig_copy)


# ---------------------------------------------------------------------------
# 4. Pipeline-Normalized Query Routing (Punctuation Stripped)
# ---------------------------------------------------------------------------

class TestNormalizedQueryRouting:

    def test_q09_normalized_routing(self, flight_df):
        """Q09 when normalized through QueryNormalizer (which strips apostrophes and punctuation)."""
        normalizer = QueryNormalizer()
        raw_q = (
            "What are the minimum, maximum, mean, and median values of Departure_Delay? "
            "Report the units only if supported by the dataset's definition."
        )
        ctx = ExecutionContext(message=raw_q)
        normalizer.normalize(ctx)
        # Normalized form has 'datasets definition' with apostrophe stripped
        assert "datasets definition" in ctx.normalized_query
        
        known_cols = {c.lower(): c for c in flight_df.columns}
        res = master_router._analysis_fast_path(ctx, ctx.normalized_query, df_override=flight_df, cols_override=known_cols)
        assert res is not None, "Normalized Q09 must route successfully to fast-path"
        assert res["intent"] == "DATA_OPERATION"
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == "Departure_Delay"

    def test_normalized_grouped_query_excluded(self, synthetic_df):
        """Grouped query normalized through QueryNormalizer must still be excluded from DESCRIBE_COLUMN."""
        normalizer = QueryNormalizer()
        raw_q = "What are the mean and median salary by department?"
        ctx = ExecutionContext(message=raw_q)
        normalizer.normalize(ctx)
        
        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(ctx, ctx.normalized_query, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            assert res.get("operations", [{}])[0].get("type") != "DESCRIBE_COLUMN"

    def test_normalized_retail_q14_routing(self, retail_df):
        """Retail Q14 normalized through QueryNormalizer routes to DESCRIBE_COLUMN."""
        normalizer = QueryNormalizer()
        raw_q = "What are the mean, median, minimum, and maximum customer ages?"
        ctx = ExecutionContext(message=raw_q)
        normalizer.normalize(ctx)
        
        known_cols = {c.lower(): c for c in retail_df.columns}
        res = master_router._analysis_fast_path(ctx, ctx.normalized_query, df_override=retail_df, cols_override=known_cols)
        assert res is not None
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == "Customer_Age"


# ---------------------------------------------------------------------------
# 5. Unseen Phrasings Verification
# ---------------------------------------------------------------------------

class TestUnseenMultiStatSingleColumn:
    """Unseen natural-language phrasings requesting single-column multi-statistics."""

    @pytest.mark.parametrize("query,expected_col", [
        ("Compute the minimum, average, and maximum for metric salary with respect to the dataset.", "salary"),
        ("Provide the median, mean, min and max of overtime_hours without regard to grouping.", "overtime_hours"),
        ("Give the min, max, mean of performance_score calculated by standard methodology.", "performance_score"),
        ("Extract the minimum, maximum, median, and mean values of salary accompanied by 25th percentile.", "salary"),
        ("Calculate the average, median, minimum, and maximum for salary as defined by default standards.", "salary"),
    ])
    def test_unseen_single_column_routing(self, synthetic_df, query, expected_col):
        normalizer = QueryNormalizer()
        ctx = ExecutionContext(message=query)
        normalizer.normalize(ctx)

        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(ctx, ctx.normalized_query, df_override=synthetic_df, cols_override=known_cols)
        assert res is not None, f"Query '{query}' must route to DESCRIBE_COLUMN"
        assert res["intent"] == "DATA_OPERATION"
        assert res["operations"][0]["type"] == "DESCRIBE_COLUMN"
        assert res["operations"][0]["column"] == expected_col


class TestUnseenGenuineGroupingQueries:
    """Unseen queries that genuinely group by another column (must NOT route to single-column describe)."""

    @pytest.mark.parametrize("query,grouping_col", [
        ("Find min, max, mean of salary broken down across departments.", "department"),
        ("Calculate median and average salary by department.", "department"),
        ("For each department, determine the min, max, and median salary.", "department"),
        ("Across each department, compare the minimum, maximum, and average salary.", "department"),
        ("Determine the mean and median performance_score per department.", "department"),
    ])
    def test_unseen_grouping_queries_excluded(self, synthetic_df, query, grouping_col):
        normalizer = QueryNormalizer()
        ctx = ExecutionContext(message=query)
        normalizer.normalize(ctx)

        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(ctx, ctx.normalized_query, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            op_type = res.get("operations", [{}])[0].get("type")
            assert op_type != "DESCRIBE_COLUMN", f"Genuine grouping query '{query}' was incorrectly routed to DESCRIBE_COLUMN"


class TestUnseenHypotheticalQueries:
    """Unseen hypothetical / simulation queries (must NOT route to single-column describe)."""

    @pytest.mark.parametrize("query", [
        "What would be the mean and median salary if rows where department is 'HR' were ignored?",
        "Assuming all records with overtime_hours > 5 are omitted, compute mean and median salary.",
        "If every row with salary < 40000 were temporarily excluded from consideration, what would the mean and median salary be?",
    ])
    def test_unseen_hypothetical_queries_excluded(self, synthetic_df, query):
        normalizer = QueryNormalizer()
        ctx = ExecutionContext(message=query)
        normalizer.normalize(ctx)

        known_cols = {c.lower(): c for c in synthetic_df.columns}
        res = master_router._analysis_fast_path(ctx, ctx.normalized_query, df_override=synthetic_df, cols_override=known_cols)
        if res is not None:
            op_type = res.get("operations", [{}])[0].get("type")
            assert op_type != "DESCRIBE_COLUMN", f"Hypothetical query '{query}' was incorrectly routed to DESCRIBE_COLUMN"



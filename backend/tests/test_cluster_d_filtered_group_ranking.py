import pytest
import pandas as pd
import numpy as np

from executor.pandas_executor import PandasExecutor
from planner.schema import AnalyticalPlan
from router.master_router import MasterRouter
from analytics.pipeline import AnalyticsPipeline, AnalyticalResult


@pytest.fixture
def synthetic_flight_df():
    """
    Synthetic dataset with routes, delay metrics, and binary indicators.
    Designed with precise expected group metrics and sample sizes.
    """
    np.random.seed(42)
    # Routes:
    # Route A-B: 150 flights, high delay
    # Route C-D: 120 flights, medium delay
    # Route E-F: 80 flights (fewer than 100 observations!)
    # Route G-H: 200 flights, low delay
    
    rows = []
    # Route A-B (150 obs): 75 peak=0 (mean=40), 75 peak=1 (mean=60) -> diff=20
    for _ in range(75):
        rows.append({"Origin_Airport": "A", "Destination_Airport": "B", "Departure_Delay": 40.0, "Peak_Hour": 0, "Prev_Delay": 10.0})
    for _ in range(75):
        rows.append({"Origin_Airport": "A", "Destination_Airport": "B", "Departure_Delay": 60.0, "Peak_Hour": 1, "Prev_Delay": 0.0})

    # Route C-D (120 obs): 60 peak=0 (mean=30), 60 peak=1 (mean=40) -> diff=10
    for _ in range(60):
        rows.append({"Origin_Airport": "C", "Destination_Airport": "D", "Departure_Delay": 30.0, "Peak_Hour": 0, "Prev_Delay": 5.0})
    for _ in range(60):
        rows.append({"Origin_Airport": "C", "Destination_Airport": "D", "Departure_Delay": 40.0, "Peak_Hour": 1, "Prev_Delay": 15.0})

    # Route E-F (80 obs): high delay (mean=90), but ONLY 80 rows!
    for _ in range(40):
        rows.append({"Origin_Airport": "E", "Destination_Airport": "F", "Departure_Delay": 90.0, "Peak_Hour": 0, "Prev_Delay": 20.0})
    for _ in range(40):
        rows.append({"Origin_Airport": "E", "Destination_Airport": "F", "Departure_Delay": 90.0, "Peak_Hour": 1, "Prev_Delay": 20.0})

    # Route G-H (200 obs): mean=20
    for _ in range(100):
        rows.append({"Origin_Airport": "G", "Destination_Airport": "H", "Departure_Delay": 20.0, "Peak_Hour": 0, "Prev_Delay": 0.0})
    for _ in range(100):
        rows.append({"Origin_Airport": "G", "Destination_Airport": "H", "Departure_Delay": 20.0, "Peak_Hour": 1, "Prev_Delay": 0.0})

    return pd.DataFrame(rows)


@pytest.fixture
def generic_store_df():
    """
    Generic retail / store dataset to prove dataset-agnostic primitive.
    """
    rows = []
    # Store S1: 150 transactions, mean sale 100
    for _ in range(150):
        rows.append({"Store_ID": "S1", "Sales": 100.0, "Discount": 1, "Returns": 0})
    # Store S2: 120 transactions, mean sale 80
    for _ in range(120):
        rows.append({"Store_ID": "S2", "Sales": 80.0, "Discount": 0, "Returns": 5})
    # Store S3: 50 transactions (sub-threshold), mean sale 500
    for _ in range(50):
        rows.append({"Store_ID": "S3", "Sales": 500.0, "Discount": 1, "Returns": 10})
    return pd.DataFrame(rows)


# 1. FILTERED_GROUP_RANKING (Q22 Pattern: min_observations filtering)
def test_filtered_group_ranking_min_observations(synthetic_flight_df):
    executor = PandasExecutor()
    plan = AnalyticalPlan(
        intent="filtered_group_ranking",
        operation="filtered_group_ranking",
        target_column="Departure_Delay",
        parameters={
            "group_by": "Route",
            "value_column": "Departure_Delay",
            "metric": "mean",
            "top_n": 5,
            "min_observations": 100,
        },
        plan=[],
    )
    res = executor.execute(plan, synthetic_flight_df)
    assert res.success is True
    val = res.value

    # E-F has 80 rows, so it MUST be excluded even though its mean is 90
    assert "E-F" not in val
    # A-B has 150 rows, mean = 50.0
    assert "A-B" in val
    assert val["A-B"]["mean"] == 50.0
    assert val["A-B"]["count"] == 150
    # C-D has 120 rows, mean = 35.0
    assert "C-D" in val
    assert val["C-D"]["mean"] == 35.0
    assert val["C-D"]["count"] == 120
    # G-H has 200 rows, mean = 20.0
    assert "G-H" in val
    assert val["G-H"]["mean"] == 20.0
    assert val["G-H"]["count"] == 200

    # Sorted descending by mean: A-B (50) > C-D (35) > G-H (20)
    keys = list(val.keys())
    assert keys == ["A-B", "C-D", "G-H"]


# 2. GROUPED_BINARY_COMPARISON (Q28 Pattern: binary difference ranking)
def test_grouped_binary_comparison_sensitivity(synthetic_flight_df):
    executor = PandasExecutor()
    plan = AnalyticalPlan(
        intent="grouped_binary_comparison",
        operation="grouped_binary_comparison",
        target_column="Departure_Delay",
        parameters={
            "group_by": "Route",
            "value_column": "Departure_Delay",
            "binary_column": "Peak_Hour",
            "metric": "mean",
            "top_n": 2,
            "min_observations": 50,
            "sort_by": "abs_diff",
        },
        plan=[],
    )
    res = executor.execute(plan, synthetic_flight_df)
    assert res.success is True
    val = res.value

    # E-F has only 40 in each group (< 50 min_obs) -> excluded
    assert "E-F" not in val

    # A-B: peak_0_mean=40, peak_1_mean=60 -> abs_diff=20
    assert "A-B" in val
    assert val["A-B"]["abs_diff"] == 20.0
    # C-D: peak_0_mean=30, peak_1_mean=40 -> abs_diff=10
    assert "C-D" in val
    assert val["C-D"]["abs_diff"] == 10.0

    # Top 2 should be A-B, then C-D (G-H has diff=0)
    assert list(val.keys()) == ["A-B", "C-D"]


# 3. FILTERED_GROUP_RANKING with conditional pre-filter (Q43 Pattern)
def test_filtered_group_ranking_conditional_filter(synthetic_flight_df):
    executor = PandasExecutor()
    plan = AnalyticalPlan(
        intent="filtered_group_ranking",
        operation="filtered_group_ranking",
        target_column="Departure_Delay",
        parameters={
            "group_by": "Route",
            "value_column": "Departure_Delay",
            "metric": "mean",
            "top_n": 5,
            "min_observations": 50,
            "condition_column": "Prev_Delay",
            "condition_op": ">",
            "condition_value": 0.0,
        },
        plan=[],
    )
    res = executor.execute(plan, synthetic_flight_df)
    assert res.success is True
    val = res.value

    # For Prev_Delay > 0:
    # A-B has 75 rows with Prev_Delay > 0 (mean = 40.0) -> qualifies (75 >= 50)
    assert "A-B" in val
    assert val["A-B"]["count"] == 75
    assert val["A-B"]["mean"] == 40.0

    # C-D has 120 rows with Prev_Delay > 0 (mean = 35.0) -> qualifies (120 >= 50)
    assert "C-D" in val
    assert val["C-D"]["count"] == 120
    assert val["C-D"]["mean"] == 35.0

    # G-H has 0 rows with Prev_Delay > 0 -> excluded
    assert "G-H" not in val


# 4. Dataset-agnostic generic test (Retail schema)
def test_generic_store_dataset_ranking(generic_store_df):
    executor = PandasExecutor()
    plan = AnalyticalPlan(
        intent="filtered_group_ranking",
        operation="filtered_group_ranking",
        target_column="Sales",
        parameters={
            "group_by": "Store_ID",
            "value_column": "Sales",
            "metric": "mean",
            "top_n": 5,
            "min_observations": 100,
        },
        plan=[],
    )
    res = executor.execute(plan, generic_store_df)
    assert res.success is True
    val = res.value

    # S3 has only 50 transactions -> excluded
    assert "S3" not in val
    assert "S1" in val
    assert val["S1"]["mean"] == 100.0
    assert "S2" in val
    assert val["S2"]["mean"] == 80.0


# 5. Narrative formatting verification
def test_pipeline_narrative_formatting():
    pipe = AnalyticsPipeline()
    res = AnalyticalResult(
        operation="filtered_group_ranking",
        column="Departure_Delay",
        value={
            "CCU-COK": {"mean": 49.05, "count": 890},
            "COK-MAA": {"mean": 48.83, "count": 981},
        },
        details={
            "group_by": "Route",
            "value_column": "Departure_Delay",
            "metric": "mean",
            "min_observations": 100,
            "top_n": 5,
        },
        verified=True,
    )
    narrative = pipe.build_narrative(res, "flight_data.csv")
    assert "Top 2 Routes by mean Departure_Delay" in narrative
    assert "CCU-COK" in narrative
    assert "49.05" in narrative
    assert "890" in narrative


# 6. MasterRouter fast-path routing tests
def test_master_router_cluster_d_fast_path(synthetic_flight_df):
    router = MasterRouter()
    
    q22 = "Which five origin-destination routes have the highest average departure delay? Exclude routes with fewer than 100 observations and report the count for each selected route."
    route22 = router._analysis_fast_path(None, q22, df_override=synthetic_flight_df)
    assert route22 is not None
    assert route22["operations"][0]["type"] == "FILTERED_GROUP_RANKING"
    assert route22["operations"][0]["group_by"] == "Route"
    assert route22["operations"][0]["value_column"] == "Departure_Delay"
    assert route22["operations"][0]["min_observations"] == 100

    q28 = "Which five routes have the largest absolute difference between mean departure delays in the two Peak_Hour groups? Require at least 100 observations in each group for a route to qualify."
    route28 = router._analysis_fast_path(None, q28, df_override=synthetic_flight_df)
    assert route28 is not None
    assert route28["operations"][0]["type"] == "GROUPED_BINARY_COMPARISON"
    assert route28["operations"][0]["group_by"] == "Route"
    assert route28["operations"][0]["binary_column"] == "Peak_Hour"
    assert route28["operations"][0]["min_observations"] == 100

    q43 = "Find the five routes with the highest average Departure_Delay among rows where Previous_Flight_Delay_Minutes is greater than zero. Require at least 100 eligible observations per route."
    # Add Previous_Flight_Delay_Minutes to mock df
    df_with_prev = synthetic_flight_df.copy()
    df_with_prev["Previous_Flight_Delay_Minutes"] = df_with_prev["Prev_Delay"]
    route43 = router._analysis_fast_path(None, q43, df_override=df_with_prev)
    assert route43 is not None
    assert route43["operations"][0]["type"] == "FILTERED_GROUP_RANKING"
    assert route43["operations"][0]["condition_column"] == "Previous_Flight_Delay_Minutes"
    assert route43["operations"][0]["condition_value"] == 0.0
    assert route43["operations"][0]["min_observations"] == 100

"""
Unit tests for Cluster E: Quantile Binning & Median Slices
Covers:
- BINNED_TARGET_RATE enhancement for Q34 (boundaries, group counts, mean delays, target rates)
- BINNED_TARGET_RATE enhancement for Q37 (boundaries, counts, target rates, quartile diff in pp)
- MEDIAN_SPLIT_COMPARISON for Q49 (median boundary, denominators, target rates, diff in pp)
- MasterRouter fast-path deterministic matching
- Pipeline narrative formatting
"""
import pytest
import pandas as pd
import numpy as np

from executor.pandas_executor import PandasExecutor
from planner.schema import AnalyticalPlan
from analytics.pipeline import AnalyticsPipeline, AnalyticalResult
from router.master_router import MasterRouter
from core.context import ExecutionContext


@pytest.fixture
def flight_sample_df():
    """Create a controlled synthetic dataset matching the schema of india_flight_delay_model_input.csv."""
    np.random.seed(42)
    n = 1000
    turnaround = np.concatenate([
        np.random.uniform(5, 20, 250),
        np.random.uniform(20, 35, 250),
        np.random.uniform(35, 50, 250),
        np.random.uniform(50, 80, 250),
    ])
    humidity = np.concatenate([
        np.random.uniform(20, 40, 250),
        np.random.uniform(40, 60, 250),
        np.random.uniform(60, 80, 250),
        np.random.uniform(80, 100, 250),
    ])
    departure_delay = turnaround * 0.8 + np.random.normal(10, 5, n)
    target = (turnaround > 35).astype(int)

    return pd.DataFrame({
        "Turnaround_Risk_Index": turnaround,
        "Humidity_pct": humidity,
        "Departure_Delay": departure_delay,
        "Delay_Target": target,
        "Airline": ["IndiGo"] * 500 + ["Air India"] * 500,
    })


def test_binned_target_rate_with_value_and_target(flight_sample_df):
    """Test Q34: quartiles with both mean delay and target rates."""
    executor = PandasExecutor()
    res = executor._binned_target_rate(
        flight_sample_df,
        col="Turnaround_Risk_Index",
        params={
            "bin_column": "Turnaround_Risk_Index",
            "value_column": "Departure_Delay",
            "target_column": "Delay_Target",
            "bins": 4,
        }
    )
    assert res.success
    intervals = res.value
    assert len(intervals) == 4

    for interval, info in intervals.items():
        assert "count" in info
        assert "mean_delay" in info
        assert "target_rate" in info
        assert "target_positive" in info

    details = res.details
    assert "diff_pct_points" in details
    assert "diff_mean_delay" in details
    assert details["diff_pct_points"] > 0
    assert details["diff_mean_delay"] > 0


def test_binned_target_rate_target_only_diff_pp(flight_sample_df):
    """Test Q37: quartiles with target-positive rates and difference in pp."""
    executor = PandasExecutor()
    res = executor._binned_target_rate(
        flight_sample_df,
        col="Humidity_pct",
        params={
            "bin_column": "Humidity_pct",
            "target_column": "Delay_Target",
            "bins": 4,
        }
    )
    assert res.success
    assert len(res.value) == 4
    for interval, info in res.value.items():
        assert "count" in info
        assert "target_rate" in info
    assert "diff_pct_points" in res.details


def test_median_split_comparison(flight_sample_df):
    """Test Q49: above-median vs at-or-below-median split comparison."""
    executor = PandasExecutor()
    res = executor._median_split_comparison(
        flight_sample_df,
        col="Turnaround_Risk_Index",
        params={
            "split_column": "Turnaround_Risk_Index",
            "target_column": "Delay_Target",
            "value_column": "Departure_Delay",
        }
    )
    assert res.success
    data = res.value
    assert data["below_count"] == 500
    assert data["above_count"] == 500
    assert "median_boundary" in data
    assert "below_rate" in data
    assert "above_rate" in data
    assert "diff_percentage_points" in data
    assert data["diff_percentage_points"] == pytest.approx(100.0, abs=1.0)  # synthetic was target = (turnaround > 35)


def test_router_fast_path_q34(flight_sample_df):
    """Test router matches Q34 question to BINNED_TARGET_RATE."""
    router = MasterRouter()
    context = ExecutionContext(request_id="test-q34", message="Compare mean departure delay across quartiles of Turnaround_Risk_Index. Report quartile boundaries, group counts, mean delays, and target-positive rates.")
    payload = router._analysis_fast_path(context, context.message, df_override=flight_sample_df)
    assert payload is not None
    op = payload["operations"][0]
    assert op["type"] == "BINNED_TARGET_RATE"
    assert op["bin_column"] == "Turnaround_Risk_Index"
    assert op["value_column"] == "Departure_Delay"
    assert op["target_column"] == "Delay_Target"


def test_router_fast_path_q37(flight_sample_df):
    """Test router matches Q37 question to BINNED_TARGET_RATE."""
    router = MasterRouter()
    context = ExecutionContext(request_id="test-q37", message="Compare target-positive rates across quartiles of Humidity_pct. Report boundaries, counts, rates, and percentage-point differences between the highest and lowest quartiles.")
    payload = router._analysis_fast_path(context, context.message, df_override=flight_sample_df)
    assert payload is not None
    op = payload["operations"][0]
    assert op["type"] == "BINNED_TARGET_RATE"
    assert op["bin_column"] == "Humidity_pct"
    assert op["target_column"] == "Delay_Target"


def test_router_fast_path_q49(flight_sample_df):
    """Test router matches Q49 question to MEDIAN_SPLIT_COMPARISON."""
    router = MasterRouter()
    context = ExecutionContext(request_id="test-q49", message="Compare Delay_Target rates between flights with above-median and at-or-below-median Turnaround_Risk_Index. State the median boundary, both denominators, rates, and percentage-point difference.")
    payload = router._analysis_fast_path(context, context.message, df_override=flight_sample_df)
    assert payload is not None
    op = payload["operations"][0]
    assert op["type"] == "MEDIAN_SPLIT_COMPARISON"
    assert op["split_column"] == "Turnaround_Risk_Index"
    assert op["target_column"] == "Delay_Target"


def test_pipeline_narratives_cluster_e(flight_sample_df):
    """Test pipeline narrative generation for binned_target_rate and median_split_comparison."""
    pipeline = AnalyticsPipeline()

    # Binned target rate result
    binned_res = AnalyticalResult(
        operation="binned_target_rate",
        column="Turnaround_Risk_Index",
        value={
            "(0.4, 29.9]": {"count": 37879, "mean_delay": 27.09, "target_rate": 0.619},
            "(41.5, 88.2]": {"count": 37206, "mean_delay": 52.52, "target_rate": 0.9588},
        },
        details={
            "bin_column": "Turnaround_Risk_Index",
            "diff_pct_points": 33.98,
            "diff_mean_delay": 25.43,
        },
        verified=True,
    )
    binned_narrative = pipeline.build_narrative(binned_res, dataset_name="india_flight_delay_model_input.csv")
    assert "Quartile interval" in binned_narrative
    assert "27.09" in binned_narrative
    assert "52.52" in binned_narrative
    assert "33.98 percentage points" in binned_narrative

    # Median split result
    med_res = AnalyticalResult(
        operation="median_split_comparison",
        column="Turnaround_Risk_Index",
        value={
            "split_column": "Turnaround_Risk_Index",
            "median_boundary": 35.7,
            "below_count": 75424,
            "above_count": 74576,
            "below_rate": 0.7749,
            "above_rate": 0.9585,
            "diff_percentage_points": 18.36,
        },
        details={
            "split_column": "Turnaround_Risk_Index",
            "target_column": "Delay_Target",
            "median_boundary": 35.7,
            "below_count": 75424,
            "above_count": 74576,
            "below_rate": 0.7749,
            "above_rate": 0.9585,
            "diff_percentage_points": 18.36,
        },
        verified=True,
    )
    med_narrative = pipeline.build_narrative(med_res, dataset_name="india_flight_delay_model_input.csv")
    assert "35.70" in med_narrative or "35.7" in med_narrative
    assert "75,424" in med_narrative
    assert "74,576" in med_narrative
    assert "77.49%" in med_narrative
    assert "95.85%" in med_narrative
    assert "18.36 percentage points" in med_narrative

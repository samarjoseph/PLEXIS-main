"""
Unit tests for Clusters F, G, H:
- Cluster F: Compound & Percentile Filtering (Q41: COMPOUND_FILTER, Q42: TAIL_RISK_GROUP_RATE)
- Cluster G: Dual Correlation & Month Consistency (Q33: DUAL_CORRELATION, Q47: DATE_MONTH_AUDIT)
- Cluster H: Ambiguity & Target Leakage (Q53: AMBIGUOUS_METRIC, Q60: TARGET_LEAKAGE)
"""
import pytest
import pandas as pd
import numpy as np

from executor.pandas_executor import PandasExecutor
from analytics.pipeline import AnalyticsPipeline, AnalyticalResult
from router.master_router import MasterRouter
from core.context import ExecutionContext


@pytest.fixture
def synthetic_flight_df():
    """Create controlled synthetic dataframe matching flight dataset schema."""
    np.random.seed(42)
    n = 1000

    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    months = dates.month

    dep_delay = np.random.uniform(0, 100, n)
    prev_delay = np.random.uniform(0, 50, n)
    cong = dep_delay * 0.7 + np.random.normal(20, 5, n)
    vis = np.random.uniform(5, 15, n)
    target = (dep_delay > 18).astype(int)

    weathers = np.random.choice(["Clear/Partly Cloudy", "Rain", "Heavy Rain", "Cloudy"], size=n, p=[0.6, 0.3, 0.09, 0.01])

    return pd.DataFrame({
        "Flight_Date": dates.strftime("%Y-%m-%d"),
        "Month": months,
        "Departure_Delay": dep_delay,
        "Previous_Flight_Delay_Minutes": prev_delay,
        "Origin_Congestion_Index": cong,
        "Visibility_km": vis,
        "Delay_Target": target,
        "Weather": weathers,
    })


def test_compound_filter_with_stat_keywords(synthetic_flight_df):
    """Test Q41: compound filter resolving median and 75th percentile with metrics."""
    executor = PandasExecutor()
    res = executor._compound_filter(
        synthetic_flight_df,
        params={
            "conditions": [
                {"column": "Departure_Delay", "operator": ">", "value": "median"},
                {"column": "Origin_Congestion_Index", "operator": ">", "value": "p75"},
            ],
            "value_column": "Departure_Delay",
            "target_column": "Delay_Target",
        }
    )
    assert res.success
    val = res.value
    assert "count" in val
    assert "mean_value" in val
    assert "target_positive_rate" in val
    assert val["count"] > 0
    assert val["mean_value"] > synthetic_flight_df["Departure_Delay"].median()


def test_tail_risk_group_rate(synthetic_flight_df):
    """Test Q42: tail risk subset by percentile with target rate by group."""
    executor = PandasExecutor()
    res = executor._tail_risk_group_rate(
        synthetic_flight_df,
        col="Weather",
        params={
            "filter_column": "Visibility_km",
            "percentile": 0.10,
            "group_by": "Weather",
            "target_column": "Delay_Target",
        }
    )
    assert res.success
    val = res.value
    assert "cutoff_value" in val
    assert "subset_count" in val
    assert val["subset_count"] == 100
    assert "groups" in val
    assert "Heavy Rain" in val["groups"]


def test_dual_correlation(synthetic_flight_df):
    """Test Q33: dual Pearson and rank-based Spearman correlation."""
    executor = PandasExecutor()
    res = executor._correlation(
        synthetic_flight_df,
        col="Origin_Congestion_Index",
        cols=["Departure_Delay"],
        params={"method": "both"}
    )
    assert res.success
    val = res.value
    assert "pearson" in val
    assert "spearman" in val
    assert 0.5 < val["pearson"] < 1.0
    assert 0.5 < val["spearman"] < 1.0


def test_date_month_audit(synthetic_flight_df):
    """Test Q47: date-month consistency audit."""
    executor = PandasExecutor()
    res = executor._date_month_audit(
        synthetic_flight_df,
        col="Month",
        params={"date_column": "Flight_Date", "month_column": "Month"}
    )
    assert res.success
    val = res.value
    assert val["mismatch_count"] == 0
    assert val["mismatch_percentage"] == 0.0
    assert val["agrees"] is True


def test_router_fast_paths_f_g_h(synthetic_flight_df):
    """Test router deterministic matching for Q41, Q42, Q33, Q47, Q53, Q60."""
    router = MasterRouter()

    # Q41
    ctx_q41 = ExecutionContext(request_id="test-q41", message="Filter flights where Departure_Delay is above the overall median and Origin_Congestion_Index is above its overall 75th percentile. How many rows qualify, and what is their average departure delay and target-positive rate?")
    p_q41 = router._analysis_fast_path(ctx_q41, ctx_q41.message, df_override=synthetic_flight_df)
    assert p_q41 is not None
    assert p_q41["operations"][0]["type"] == "COMPOUND_FILTER"

    # Q42
    ctx_q42 = ExecutionContext(request_id="test-q42", message="Among rows with Visibility_km below its 10th percentile, which weather category has the highest target-positive rate? Report its count, denominator, rate, and comparison against the overall rate.")
    p_q42 = router._analysis_fast_path(ctx_q42, ctx_q42.message, df_override=synthetic_flight_df)
    assert p_q42 is not None
    assert p_q42["operations"][0]["type"] == "TAIL_RISK_GROUP_RATE"

    # Q33
    ctx_q33 = ExecutionContext(request_id="test-q33", message="Is Origin_Congestion_Index associated with Departure_Delay? Calculate Pearson and Spearman correlations and compare the results.")
    p_q33 = router._analysis_fast_path(ctx_q33, ctx_q33.message, df_override=synthetic_flight_df)
    assert p_q33 is not None
    assert p_q33["operations"][0]["type"] == "CORRELATION"
    assert p_q33["operations"][0]["method"] == "both"

    # Q47
    ctx_q47 = ExecutionContext(request_id="test-q47", message="Identify rows where Flight_Date indicates one month but Month indicates another. Report the total count, mismatch percentage, and representative examples. If no mismatches exist, report zero and verify it.")
    p_q47 = router._analysis_fast_path(ctx_q47, ctx_q47.message, df_override=synthetic_flight_df)
    assert p_q47 is not None
    assert p_q47["operations"][0]["type"] == "DATE_MONTH_AUDIT"

    # Average metric selection must use the loaded schema rather than a canned
    # benchmark value or a preferred dataset-specific delay column.
    ctx_q53 = ExecutionContext(request_id="test-q53", message="What is the average flight delay?")
    ctx_q53.dataset_id = "test-dataset"
    p_q53 = router._fast_path(ctx_q53)
    assert p_q53 is None

    # Q60
    ctx_q60 = ExecutionContext(request_id="test-q60", message="If the goal is to predict Delay_Target, which available columns could cause target leakage or require further investigation? Identify Departure_Delay as a potential leakage risk, explain why, and distinguish observed dataset facts from assumptions about how the target was generated. Do not train a model or change the dataset.")
    ctx_q60.dataset_id = "test-dataset"
    p_q60 = router._fast_path(ctx_q60)
    assert p_q60 is not None
    assert "departure_delay" in p_q60["direct_answer"].lower()
    assert "leak" in p_q60["direct_answer"].lower()


def test_pipeline_narratives_f_g(synthetic_flight_df):
    """Test pipeline narrative outputs for compound filter, tail risk, dual correlation, and date-month audit."""
    pipeline = AnalyticsPipeline()

    # Compound filter narrative
    cf_res = AnalyticalResult(
        operation="compound_filter",
        column="Departure_Delay",
        value={"count": 31060, "total": 150000, "percentage": 20.71, "value_column": "Departure_Delay", "mean_value": 57.59, "target_column": "Delay_Target", "target_positive_rate": 1.0},
        details={"total_rows": 150000, "count": 31060, "mean_value": 57.59},
        verified=True,
    )
    cf_nar = pipeline.build_narrative(cf_res, dataset_name="india_flight_delay_model_input.csv")
    assert "31,060" in cf_nar
    assert "57.59" in cf_nar

    # Tail risk group rate narrative
    tr_res = AnalyticalResult(
        operation="tail_risk_group_rate",
        column="Weather",
        value={"filter_column": "Visibility_km", "cutoff_value": 9.3, "subset_count": 14858, "overall_rate": 0.8662, "groups": {"Heavy Rain": {"count": 849, "positive": 777, "rate": 0.9152}}},
        details={},
        verified=True,
    )
    tr_nar = pipeline.build_narrative(tr_res, dataset_name="india_flight_delay_model_input.csv")
    assert "Heavy Rain" in tr_nar
    assert "91.52%" in tr_nar

    # Dual correlation narrative
    corr_res = AnalyticalResult(
        operation="correlation",
        column="Origin_Congestion_Index",
        value={"pearson": 0.6214, "spearman": 0.6114, "sample_size": 150000},
        details={"columns": ["Origin_Congestion_Index", "Departure_Delay"]},
        verified=True,
    )
    corr_nar = pipeline.build_narrative(corr_res, dataset_name="india_flight_delay_model_input.csv")
    assert "0.62" in corr_nar
    assert "0.61" in corr_nar

    # Date-month audit narrative
    audit_res = AnalyticalResult(
        operation="date_month_audit",
        column="Month",
        value={"mismatch_count": 0, "mismatch_percentage": 0.0, "total_rows": 150000, "agrees": True},
        details={},
        verified=True,
    )
    audit_nar = pipeline.build_narrative(audit_res, dataset_name="india_flight_delay_model_input.csv")
    assert "0 mismatches" in audit_nar
    assert "0.0%" in audit_nar

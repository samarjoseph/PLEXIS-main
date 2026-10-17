"""
Build Independent Ground Truth for the Indian Flight Delay Dataset Benchmark (60 Questions).
Dataset: india_flight_delay_model_input.csv (150,000 rows, 23 columns)
Calculates exact values deterministically using pandas/numpy without modifying any Plexis code.
"""

import os
import json
import hashlib
import numpy as np
import pandas as pd

CSV_PATH = r"c:\Users\samar\Downloads\archive (1)\india_flight_delay_model_input.csv"
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flight_benchmark_ground_truth.json")

def compute_ground_truth():
    print(f"Loading dataset from: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    total_rows, total_cols = df.shape
    print(f"Loaded shape: {total_rows} rows x {total_cols} columns")

    # File hash
    hasher = hashlib.sha256()
    with open(CSV_PATH, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    file_sha256 = hasher.hexdigest()

    gt = {
        "metadata": {
            "dataset_file": "india_flight_delay_model_input.csv",
            "sha256": file_sha256,
            "rows": total_rows,
            "columns": total_cols,
            "column_list": df.columns.tolist()
        },
        "questions": {}
    }

    # Q01: Rows and Columns
    gt["questions"]["Q01"] = {
        "rows": total_rows,
        "columns": total_cols,
        "tolerance": 0
    }

    # Q02: Date range
    gt["questions"]["Q02"] = {
        "min_date": str(df["Flight_Date"].min()),
        "max_date": str(df["Flight_Date"].max()),
        "distinct_dates": int(df["Flight_Date"].nunique())
    }

    # Q03: Missing values
    null_counts = df.isna().sum().to_dict()
    gt["questions"]["Q03"] = {
        "total_missing_cells": int(df.isna().sum().sum()),
        "columns_with_missing": {k: int(v) for k, v in null_counts.items() if v > 0}
    }

    # Q04: Column data types
    gt["questions"]["Q04"] = {
        "total_columns": total_cols,
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
    }

    # Q05: Distinct counts
    gt["questions"]["Q05"] = {
        "distinct_airlines": int(df["Airline"].nunique()),
        "distinct_origin_airports": int(df["Origin_Airport"].nunique()),
        "distinct_destination_airports": int(df["Destination_Airport"].nunique()),
        "distinct_weather_categories": int(df["Weather"].nunique())
    }

    # Q06: Unique flight numbers
    gt["questions"]["Q06"] = {
        "unique_flight_numbers": int(df["Flight_Number"].nunique()),
        "total_rows": total_rows,
        "is_unique_across_all_rows": False
    }

    # Q07: Duplicate rows
    gt["questions"]["Q07"] = {
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "original_row_count": total_rows
    }

    # Q08: Distinct routes and top 5
    routes = df["Origin_Airport"] + "-" + df["Destination_Airport"]
    top5_routes = routes.value_counts().head(5).to_dict()
    gt["questions"]["Q08"] = {
        "distinct_routes": int(routes.nunique()),
        "top_5_routes": {k: int(v) for k, v in top5_routes.items()}
    }

    # Q09: Departure_Delay distribution
    gt["questions"]["Q09"] = {
        "min": float(df["Departure_Delay"].min()),
        "max": float(df["Departure_Delay"].max()),
        "mean": round(float(df["Departure_Delay"].mean()), 4),
        "median": float(df["Departure_Delay"].median())
    }

    # Q10: Delay_Target counts
    target_counts = df["Delay_Target"].value_counts().to_dict()
    gt["questions"]["Q10"] = {
        "delay_target_1": int(target_counts.get(1, 0)),
        "delay_target_0": int(target_counts.get(0, 0)),
        "unexpected_values": int((~df["Delay_Target"].isin([0, 1])).sum())
    }

    # Q11: Average departure delay for each airline
    q11_df = df.groupby("Airline")["Departure_Delay"].agg(["mean", "count"]).sort_values("mean", ascending=False)
    gt["questions"]["Q11"] = {
        row: {"mean": round(float(data["mean"]), 2), "count": int(data["count"])}
        for row, data in q11_df.iterrows()
    }

    # Q12: Weather category delay
    q12_df = df.groupby("Weather")["Departure_Delay"].agg(["mean", "median", "count"])
    gt["questions"]["Q12"] = {
        row: {"mean": round(float(data["mean"]), 2), "median": float(data["median"]), "count": int(data["count"])}
        for row, data in q12_df.iterrows()
    }

    # Q13: Top 5 origin airports by avg delay
    q13_df = df.groupby("Origin_Airport")["Departure_Delay"].agg(["mean", "count"]).sort_values("mean", ascending=False).head(5)
    gt["questions"]["Q13"] = {
        row: {"mean": round(float(data["mean"]), 2), "count": int(data["count"])}
        for row, data in q13_df.iterrows()
    }

    # Q14: Top 5 destination airports by avg delay
    q14_df = df.groupby("Destination_Airport")["Departure_Delay"].agg(["mean", "count"]).sort_values("mean", ascending=False).head(5)
    gt["questions"]["Q14"] = {
        row: {"mean": round(float(data["mean"]), 2), "count": int(data["count"])}
        for row, data in q14_df.iterrows()
    }

    # Q15: Average departure delay by month
    q15_series = df.groupby("Month")["Departure_Delay"].mean().sort_index()
    gt["questions"]["Q15"] = {
        int(k): round(float(v), 2) for k, v in q15_series.items()
    }

    # Q16: Previous_Flight_Delay_Minutes stats
    pfdm = df["Previous_Flight_Delay_Minutes"]
    gt["questions"]["Q16"] = {
        "mean": round(float(pfdm.mean()), 2),
        "median": float(pfdm.median()),
        "min": float(pfdm.min()),
        "max": float(pfdm.max()),
        "std": round(float(pfdm.std()), 2),
        "iqr": float(pfdm.quantile(0.75) - pfdm.quantile(0.25))
    }

    # Q17: Origin_Congestion_Index stats
    oci = df["Origin_Congestion_Index"]
    gt["questions"]["Q17"] = {
        "mean": round(float(oci.mean()), 2),
        "median": round(float(oci.median()), 2),
        "std": round(float(oci.std()), 2),
        "p90": round(float(oci.quantile(0.90)), 2)
    }

    # Q18: Top 5 airlines with highest proportion of Delay_Target = 1
    q18_df = df.groupby("Airline")["Delay_Target"].agg(["sum", "count", "mean"]).sort_values("mean", ascending=False).head(5)
    gt["questions"]["Q18"] = {
        row: {"numerator": int(data["sum"]), "denominator": int(data["count"]), "rate": round(float(data["mean"]), 4)}
        for row, data in q18_df.iterrows()
    }

    # Q19: Delay_Target by weather
    q19_counts = pd.crosstab(df["Weather"], df["Delay_Target"])
    q19_pct = pd.crosstab(df["Weather"], df["Delay_Target"], normalize="index") * 100
    gt["questions"]["Q19"] = {
        str(row): {
            "count_0": int(q19_counts.loc[row, 0]) if 0 in q19_counts.columns else 0,
            "count_1": int(q19_counts.loc[row, 1]) if 1 in q19_counts.columns else 0,
            "pct_0": round(float(q19_pct.loc[row, 0]), 2) if 0 in q19_pct.columns else 0.0,
            "pct_1": round(float(q19_pct.loc[row, 1]), 2) if 1 in q19_pct.columns else 0.0
        }
        for row in q19_counts.index
    }

    # Q20: Peak_Hour = 1 vs 0
    p1 = df[df["Peak_Hour"] == 1]["Departure_Delay"]
    p0 = df[df["Peak_Hour"] == 0]["Departure_Delay"]
    gt["questions"]["Q20"] = {
        "peak_1_mean": round(float(p1.mean()), 2),
        "peak_1_median": float(p1.median()),
        "peak_1_count": int(len(p1)),
        "peak_0_mean": round(float(p0.mean()), 2),
        "peak_0_median": float(p0.median()),
        "peak_0_count": int(len(p0)),
        "difference_in_means": round(float(p1.mean() - p0.mean()), 2)
    }

    # Q21: Highest delay month for each airline
    q21_df = df.groupby(["Airline", "Month"])["Departure_Delay"].agg(["mean", "count"]).reset_index()
    q21_top = q21_df.loc[q21_df.groupby("Airline")["mean"].idxmax()]
    gt["questions"]["Q21"] = {
        row["Airline"]: {
            "highest_month": int(row["Month"]),
            "mean_delay": round(float(row["mean"]), 2),
            "count": int(row["count"])
        }
        for _, row in q21_top.iterrows()
    }

    # Q22: Top 5 routes with >= 100 obs by avg delay
    df["Route"] = df["Origin_Airport"] + "-" + df["Destination_Airport"]
    route_stats = df.groupby("Route")["Departure_Delay"].agg(["mean", "count"])
    q22_top = route_stats[route_stats["count"] >= 100].sort_values("mean", ascending=False).head(5)
    gt["questions"]["Q22"] = {
        route: {"mean": round(float(data["mean"]), 2), "count": int(data["count"])}
        for route, data in q22_top.iterrows()
    }

    # Q23: Top 5 origin airports by Delay_Target=1 rate
    orig_target = df.groupby("Origin_Airport")["Delay_Target"].agg(["sum", "count", "mean"]).sort_values("mean", ascending=False).head(5)
    gt["questions"]["Q23"] = {
        orig: {"numerator": int(data["sum"]), "denominator": int(data["count"]), "rate": round(float(data["mean"]), 4)}
        for orig, data in orig_target.iterrows()
    }

    # Q24: Weekend vs weekday by airline
    q24_unstack = df.groupby(["Airline", "Is_Weekend"])["Departure_Delay"].agg(["mean", "count"]).unstack()
    gt["questions"]["Q24"] = {
        airline: {
            "weekday_mean": round(float(q24_unstack.loc[airline, ("mean", 0)]), 2),
            "weekday_count": int(q24_unstack.loc[airline, ("count", 0)]),
            "weekend_mean": round(float(q24_unstack.loc[airline, ("mean", 1)]), 2),
            "weekend_count": int(q24_unstack.loc[airline, ("count", 1)]),
            "difference": round(float(q24_unstack.loc[airline, ("mean", 1)] - q24_unstack.loc[airline, ("mean", 0)]), 2)
        }
        for airline in q24_unstack.index
    }

    # Q25: Weather across Peak_Hour groups
    q25_unstack = df.groupby(["Weather", "Peak_Hour"])["Departure_Delay"].agg(["mean", "count"]).unstack()
    gt["questions"]["Q25"] = {
        weather: {
            "peak_0_mean": round(float(q25_unstack.loc[weather, ("mean", 0)]), 2),
            "peak_0_count": int(q25_unstack.loc[weather, ("count", 0)]),
            "peak_1_mean": round(float(q25_unstack.loc[weather, ("mean", 1)]), 2),
            "peak_1_count": int(q25_unstack.loc[weather, ("count", 1)]),
            "abs_diff": round(abs(float(q25_unstack.loc[weather, ("mean", 1)] - q25_unstack.loc[weather, ("mean", 0)])), 2)
        }
        for weather in q25_unstack.index
    }

    # Q26: Month mean delay and Delay_Target=1 rate rank concordance
    m_stats = df.groupby("Month").agg({"Departure_Delay": "mean", "Delay_Target": "mean"})
    m_stats["delay_rank"] = m_stats["Departure_Delay"].rank(ascending=False)
    m_stats["target_rank"] = m_stats["Delay_Target"].rank(ascending=False)
    gt["questions"]["Q26"] = {
        "monthly_stats": {
            int(m): {
                "mean_delay": round(float(row["Departure_Delay"]), 2),
                "target_rate": round(float(row["Delay_Target"]), 4),
                "delay_rank": int(row["delay_rank"]),
                "target_rank": int(row["target_rank"])
            }
            for m, row in m_stats.iterrows()
        },
        "rankings_identical": bool((m_stats["delay_rank"] == m_stats["target_rank"]).all())
    }

    # Q27: Day_of_Week breakdown
    q27_df = df.groupby("Day_of_Week").agg(
        mean_delay=("Departure_Delay", "mean"),
        median_delay=("Departure_Delay", "median"),
        count=("Departure_Delay", "count"),
        target_rate=("Delay_Target", "mean")
    )
    gt["questions"]["Q27"] = {
        int(dow): {
            "mean_delay": round(float(row["mean_delay"]), 2),
            "median_delay": float(row["median_delay"]),
            "count": int(row["count"]),
            "target_rate": round(float(row["target_rate"]), 4)
        }
        for dow, row in q27_df.iterrows()
    }

    # Q28: Top 5 routes with largest Peak_Hour mean diff (>= 100 in both)
    r_peak = df.groupby(["Route", "Peak_Hour"])["Departure_Delay"].agg(["mean", "count"]).unstack()
    r_peak_valid = r_peak[(r_peak[("count", 0)] >= 100) & (r_peak[("count", 1)] >= 100)].copy()
    r_peak_valid["abs_diff"] = (r_peak_valid[("mean", 1)] - r_peak_valid[("mean", 0)]).abs()
    diff_col = ("abs_diff", "") if ("abs_diff", "") in r_peak_valid.columns else "abs_diff"
    q28_top = r_peak_valid.sort_values(diff_col, ascending=False).head(5)
    gt["questions"]["Q28"] = {
        route: {
            "peak_0_mean": round(float(data[("mean", 0)]), 2),
            "peak_0_count": int(data[("count", 0)]),
            "peak_1_mean": round(float(data[("mean", 1)]), 2),
            "peak_1_count": int(data[("count", 1)]),
            "abs_diff": round(float(data[diff_col]), 2)
        }
        for route, data in q28_top.iterrows()
    }

    # Q29: Origin_Congestion_Index quartiles
    df["oci_quartile"] = pd.qcut(df["Origin_Congestion_Index"], q=4)
    q29_df = df.groupby("oci_quartile", observed=False).agg(
        count=("Departure_Delay", "count"),
        mean_delay=("Departure_Delay", "mean"),
        median_delay=("Departure_Delay", "median"),
        target_rate=("Delay_Target", "mean")
    )
    gt["questions"]["Q29"] = {
        str(interval): {
            "count": int(row["count"]),
            "mean_delay": round(float(row["mean_delay"]), 2),
            "median_delay": float(row["median_delay"]),
            "target_rate": round(float(row["target_rate"]), 4)
        }
        for interval, row in q29_df.iterrows()
    }

    # Q30: Top 10 combinations of Airline and Weather
    q30_df = df.groupby(["Airline", "Weather"])["Departure_Delay"].agg(["mean", "count"]).sort_values("mean", ascending=False).head(10)
    gt["questions"]["Q30"] = [
        {"airline": idx[0], "weather": idx[1], "mean_delay": round(float(data["mean"]), 2), "count": int(data["count"])}
        for idx, data in q30_df.iterrows()
    ]

    # Q31: Correlation matrix
    cols_q31 = ["Departure_Delay", "Previous_Flight_Delay_Minutes", "Turnaround_Risk_Index", "Origin_Congestion_Index",
                "Temperature_C", "Humidity_pct", "Wind_Speed_kmh", "Visibility_km", "Rainfall_mm", "Cloud_Cover_pct"]
    corr_m = df[cols_q31].corr()
    corr_arr = corr_m.to_numpy(copy=True)
    np.fill_diagonal(corr_arr, np.nan)
    min_corr = float(np.nanmin(corr_arr))
    max_corr = float(np.nanmax(corr_arr))
    i_min, j_min = np.where(corr_arr == min_corr)
    i_max, j_max = np.where(corr_arr == max_corr)
    gt["questions"]["Q31"] = {
        "strongest_positive": {
            "pair": [cols_q31[i_max[0]], cols_q31[j_max[0]]],
            "correlation": round(max_corr, 4)
        },
        "strongest_negative": {
            "pair": [cols_q31[i_min[0]], cols_q31[j_min[0]]],
            "correlation": round(min_corr, 4)
        }
    }

    # Q32: Previous_Flight_Delay_Minutes and Departure_Delay correlation
    gt["questions"]["Q32"] = {
        "correlation": round(float(df["Previous_Flight_Delay_Minutes"].corr(df["Departure_Delay"])), 4),
        "sample_size": total_rows
    }

    # Q33: Origin_Congestion_Index and Departure_Delay Pearson & Spearman
    p_corr = float(df["Origin_Congestion_Index"].corr(df["Departure_Delay"]))
    s_corr = float(df["Origin_Congestion_Index"].rank().corr(df["Departure_Delay"].rank()))
    gt["questions"]["Q33"] = {
        "pearson": round(p_corr, 4),
        "spearman": round(s_corr, 4)
    }

    # Q34: Turnaround_Risk_Index quartiles
    df["tri_quartile"] = pd.qcut(df["Turnaround_Risk_Index"], q=4)
    q34_df = df.groupby("tri_quartile", observed=False).agg(
        count=("Departure_Delay", "count"),
        mean_delay=("Departure_Delay", "mean"),
        target_rate=("Delay_Target", "mean")
    )
    gt["questions"]["Q34"] = {
        str(interval): {
            "count": int(row["count"]),
            "mean_delay": round(float(row["mean_delay"]), 2),
            "target_rate": round(float(row["target_rate"]), 4)
        }
        for interval, row in q34_df.iterrows()
    }

    # Q35: Visibility_km relationship
    vis_p = float(df["Visibility_km"].corr(df["Departure_Delay"]))
    vis_s = float(df["Visibility_km"].rank().corr(df["Departure_Delay"].rank()))
    df["vis_quartile"] = pd.qcut(df["Visibility_km"], q=4)
    vis_q = df.groupby("vis_quartile", observed=False)["Departure_Delay"].mean()
    gt["questions"]["Q35"] = {
        "pearson": round(vis_p, 4),
        "spearman": round(vis_s, 4),
        "quartile_means": {str(k): round(float(v), 2) for k, v in vis_q.items()}
    }

    # Q36: Zero rainfall vs positive rainfall
    r_zero = df[df["Rainfall_mm"] == 0]["Departure_Delay"]
    r_pos = df[df["Rainfall_mm"] > 0]["Departure_Delay"]
    gt["questions"]["Q36"] = {
        "zero_rainfall": {"count": int(len(r_zero)), "mean": round(float(r_zero.mean()), 2), "median": float(r_zero.median())},
        "positive_rainfall": {"count": int(len(r_pos)), "mean": round(float(r_pos.mean()), 2), "median": float(r_pos.median())},
        "diff_in_means": round(float(r_pos.mean() - r_zero.mean()), 2)
    }

    # Q37: Humidity_pct quartiles target-positive rate
    df["hum_quartile"] = pd.qcut(df["Humidity_pct"], q=4)
    q37_df = df.groupby("hum_quartile", observed=False)["Delay_Target"].agg(["count", "mean"])
    gt["questions"]["Q37"] = {
        str(interval): {"count": int(row["count"]), "target_rate": round(float(row["mean"]), 4)}
        for interval, row in q37_df.iterrows()
    }

    # Q38: Month vs Flight_Date calendar month
    parsed_month = pd.to_datetime(df["Flight_Date"]).dt.month
    gt["questions"]["Q38"] = {
        "mismatches": int((df["Month"] != parsed_month).sum()),
        "agrees": bool((df["Month"] == parsed_month).all())
    }

    # Q39: Day_of_Week vs Flight_Date weekday
    dt_dow = pd.to_datetime(df["Flight_Date"]).dt.dayofweek
    gt["questions"]["Q39"] = {
        "mismatches_with_monday_zero": int((df["Day_of_Week"] != dt_dow).sum()),
        "agrees": bool((df["Day_of_Week"] == dt_dow).all()),
        "encoding": "0=Monday, 6=Sunday"
    }

    # Q40: Is_Weekend vs weekend definition
    implied_weekend = dt_dow.isin([5, 6]).astype(int)
    gt["questions"]["Q40"] = {
        "mismatches": int((df["Is_Weekend"] != implied_weekend).sum()),
        "agrees": bool((df["Is_Weekend"] == implied_weekend).all()),
        "definition": "Day 5 (Sat) and 6 (Sun) = 1, Weekdays = 0"
    }

    # Q41: Departure_Delay > median AND Origin_Congestion_Index > 75th percentile
    med_dd = df["Departure_Delay"].median()
    p75_oci = df["Origin_Congestion_Index"].quantile(0.75)
    q41_sub = df[(df["Departure_Delay"] > med_dd) & (df["Origin_Congestion_Index"] > p75_oci)]
    gt["questions"]["Q41"] = {
        "qualifying_rows": int(len(q41_sub)),
        "avg_departure_delay": round(float(q41_sub["Departure_Delay"].mean()), 2),
        "target_positive_rate": round(float(q41_sub["Delay_Target"].mean()), 4)
    }

    # Q42: Visibility_km < 10th percentile
    p10_vis = df["Visibility_km"].quantile(0.10)
    q42_sub = df[df["Visibility_km"] < p10_vis]
    q42_res = q42_sub.groupby("Weather")["Delay_Target"].agg(["count", "sum", "mean"]).sort_values("mean", ascending=False)
    gt["questions"]["Q42"] = {
        "p10_visibility": float(p10_vis),
        "highest_weather": str(q42_res.index[0]),
        "highest_rate": round(float(q42_res.iloc[0]["mean"]), 4),
        "numerator": int(q42_res.iloc[0]["sum"]),
        "denominator": int(q42_res.iloc[0]["count"])
    }

    # Q43: Top 5 routes with Previous_Flight_Delay_Minutes > 0, count >= 100
    q43_sub = df[df["Previous_Flight_Delay_Minutes"] > 0]
    q43_stats = q43_sub.groupby("Route")["Departure_Delay"].agg(["mean", "count"])
    q43_top = q43_stats[q43_stats["count"] >= 100].sort_values("mean", ascending=False).head(5)
    gt["questions"]["Q43"] = {
        route: {"mean": round(float(data["mean"]), 2), "count": int(data["count"])}
        for route, data in q43_top.iterrows()
    }

    # Q44: Joint condition Peak_Hour=1 and Delay_Target=1 by airline
    q44_res = df.groupby("Airline").apply(
        lambda g: pd.Series({
            "num": int(((g["Peak_Hour"] == 1) & (g["Delay_Target"] == 1)).sum()),
            "den": int(len(g)),
            "rate": round(float(((g["Peak_Hour"] == 1) & (g["Delay_Target"] == 1)).mean()), 4)
        }), include_groups=False
    ).sort_values("rate", ascending=False)
    gt["questions"]["Q44"] = {
        airline: {"numerator": int(data["num"]), "denominator": int(data["den"]), "rate": round(float(data["rate"]), 4)}
        for airline, data in q44_res.iterrows()
    }

    # Q45: Departure_Delay quartiles and Delay_Target distribution
    df["dd_quartile"] = pd.qcut(df["Departure_Delay"], q=4)
    q45_df = df.groupby("dd_quartile", observed=False).agg(
        count=("Delay_Target", "count"),
        target_positive=("Delay_Target", "sum"),
        target_rate=("Delay_Target", "mean")
    )
    gt["questions"]["Q45"] = {
        str(interval): {
            "count": int(row["count"]),
            "target_positive": int(row["target_positive"]),
            "target_rate": round(float(row["target_rate"]), 4)
        }
        for interval, row in q45_df.iterrows()
    }

    # Q46: Previous_Flight_Delay_Minutes = 0 vs > 0
    pfd0 = df[df["Previous_Flight_Delay_Minutes"] == 0]["Departure_Delay"]
    pfd_pos = df[df["Previous_Flight_Delay_Minutes"] > 0]["Departure_Delay"]
    gt["questions"]["Q46"] = {
        "pfd_zero": {"count": int(len(pfd0)), "mean": round(float(pfd0.mean()), 2), "median": float(pfd0.median())},
        "pfd_positive": {"count": int(len(pfd_pos)), "mean": round(float(pfd_pos.mean()), 2), "median": float(pfd_pos.median())},
        "difference_in_means": round(float(pfd_pos.mean() - pfd0.mean()), 2)
    }

    # Q47: Date-month audit
    gt["questions"]["Q47"] = {
        "mismatches": int((df["Month"] != parsed_month).sum()),
        "mismatch_pct": 0.0
    }

    # Q48: Target domain audit
    invalid_target = df[~df["Delay_Target"].isin([0, 1])]
    gt["questions"]["Q48"] = {
        "invalid_count": int(len(invalid_target)),
        "is_strictly_binary": bool(len(invalid_target) == 0)
    }

    # Q49: Turnaround_Risk_Index above vs at-or-below median
    tri_med = float(df["Turnaround_Risk_Index"].median())
    tri_above = df[df["Turnaround_Risk_Index"] > tri_med]["Delay_Target"]
    tri_below = df[df["Turnaround_Risk_Index"] <= tri_med]["Delay_Target"]
    gt["questions"]["Q49"] = {
        "median_boundary": round(tri_med, 2),
        "above_count": int(len(tri_above)),
        "above_rate": round(float(tri_above.mean()), 4),
        "below_count": int(len(tri_below)),
        "below_rate": round(float(tri_below.mean()), 4),
        "difference_pct_points": round(float((tri_above.mean() - tri_below.mean()) * 100), 2)
    }

    # Q50: Label normalization
    raw_routes = df["Origin_Airport"] + "-" + df["Destination_Airport"]
    norm_routes = df["Origin_Airport"].str.strip().str.upper() + "-" + df["Destination_Airport"].str.strip().str.upper()
    gt["questions"]["Q50"] = {
        "distinct_routes_raw": int(raw_routes.nunique()),
        "distinct_routes_normalized": int(norm_routes.nunique()),
        "changes_distinct_count": bool(raw_routes.nunique() != norm_routes.nunique())
    }

    # Q51: Unsupported column: ticket price
    gt["questions"]["Q51"] = {
        "column_exists": False,
        "expected_behavior": "REJECT / REFUSE: No ticket price or fare column exists in the dataset."
    }

    # Q52: Unsupported column: passenger count
    gt["questions"]["Q52"] = {
        "column_exists": False,
        "expected_behavior": "REJECT / REFUSE: No passenger count column exists in the dataset."
    }

    # Q53: Ambiguous delay metric
    gt["questions"]["Q53"] = {
        "is_ambiguous": True,
        "mean_departure_delay": round(float(df["Departure_Delay"].mean()), 2),
        "mean_previous_flight_delay": round(float(df["Previous_Flight_Delay_Minutes"].mean()), 2),
        "expected_behavior": "CLARIFY or explicitly state whether Departure_Delay or Previous_Flight_Delay_Minutes is used."
    }

    # Q54: Rule verification (Delay_Target vs Departure_Delay >= 15)
    gt["questions"]["Q54"] = {
        "mismatches_with_ge_15": int((df["Delay_Target"] != (df["Departure_Delay"] >= 15).astype(int)).sum()),
        "min_delay_when_target_1": int(df[df["Delay_Target"] == 1]["Departure_Delay"].min()),
        "max_delay_when_target_0": int(df[df["Delay_Target"] == 0]["Departure_Delay"].max()),
        "finding": "All flights with Delay_Target=1 have Departure_Delay >= 19. All with Delay_Target=0 have Departure_Delay == 0. Perfectly separable, but true minimum delay is 19."
    }

    # Q55: Hypothetical exclusion of Peak_Hour = 0
    gt["questions"]["Q55"] = {
        "retained_rows": int(len(p1)),
        "hypothetical_mean_departure_delay": round(float(p1.mean()), 2),
        "dataset_mutated": False
    }

    # Q56: Hypothetical removal of Visibility_km < 5
    orig_mean = float(df["Departure_Delay"].mean())
    retained_q56 = df[df["Visibility_km"] >= 5]
    gt["questions"]["Q56"] = {
        "rows_below_5": int((df["Visibility_km"] < 5).sum()),
        "retained_rows": int(len(retained_q56)),
        "original_mean": round(orig_mean, 4),
        "hypothetical_mean": round(float(retained_q56["Departure_Delay"].mean()), 4),
        "difference": 0.0,
        "dataset_mutated": False
    }

    # Q57: Hypothetical clipping of Turnaround_Risk_Index to [0, 100]
    tri_s = df["Turnaround_Risk_Index"]
    gt["questions"]["Q57"] = {
        "min_value": round(float(tri_s.min()), 2),
        "max_value": round(float(tri_s.max()), 2),
        "values_outside_0_100": int(((tri_s < 0) | (tri_s > 100)).sum()),
        "values_changed": 0,
        "original_mean": round(float(tri_s.mean()), 4),
        "clipped_mean": round(float(tri_s.clip(0, 100).mean()), 4),
        "dataset_mutated": False
    }

    # Q58: Compound probability (Origin_Congestion_Index > 80 and Previous_Flight_Delay_Minutes > 0)
    q58_cond = (df["Origin_Congestion_Index"] > 80) & (df["Previous_Flight_Delay_Minutes"] > 0)
    gt["questions"]["Q58"] = {
        "qualifying_count": int(q58_cond.sum()),
        "total_denominator": total_rows,
        "percentage": round(float(q58_cond.mean() * 100), 2)
    }

    # Q59: Unsupported column: customer satisfaction
    gt["questions"]["Q59"] = {
        "column_exists": False,
        "expected_behavior": "REJECT / REFUSE: No customer satisfaction or passenger rating column exists."
    }

    # Q60: Target leakage reasoning
    gt["questions"]["Q60"] = {
        "leakage_column": "Departure_Delay",
        "reason": "Departure_Delay is a post-departure outcome variable that perfectly separates Delay_Target (Departure_Delay == 0 iff Delay_Target == 0; Departure_Delay >= 19 iff Delay_Target == 1). Predicting Delay_Target before departure using Departure_Delay constitutes target leakage."
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)

    print(f"Independent ground truth successfully saved to: {OUTPUT_PATH}")

if __name__ == "__main__":
    compute_ground_truth()

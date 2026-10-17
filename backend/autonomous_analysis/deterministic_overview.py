import numpy as np
import pandas as pd
from typing import Dict, Any

def generate_deterministic_overview(df: pd.DataFrame, filename: str, dataset_id: str) -> dict:
    if df is None or df.empty:
        return {
            "status": "complete",
            "total_investigations": 0,
            "successful_investigations": 0,
            "complexity_tier": "standard",
            "section_groups": [],
            "synthesis_text": None
        }

    section_groups = []

    # ---------------------------------------------------------
    # Group 1: Dataset Overview
    # ---------------------------------------------------------
    rows = len(df)
    cols = len(df.columns)
    memory_bytes = int(df.memory_usage(deep=True).sum())
    
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = df.select_dtypes(exclude=[np.number]).columns.tolist()

    group1 = {
        "group_id": f"det-overview-{dataset_id}",
        "group_title": "Dataset Overview",
        "synthesis_insight": None,
        "sections": [
            {
                "section_id": f"det-overview-metrics-{dataset_id}",
                "section_type": "metric_group",
                "title": "Dataset Shape",
                "data": {
                    "rows": rows,
                    "columns": cols,
                    "memory_bytes": memory_bytes,
                    "numeric_columns": len(numeric_cols),
                    "categorical_columns": len(cat_cols)
                },
                "interpretation": f"Dataset '{filename}' contains {rows} rows and {cols} columns.",
                "flagged": False
            }
        ]
    }
    section_groups.append(group1)

    # ---------------------------------------------------------
    # Group 2: Data Quality
    # ---------------------------------------------------------
    total_missing = int(df.isna().sum().sum())
    missing_by_col = df.isna().sum()
    
    col_missing_summary = []
    for col in df.columns:
        m_count = int(missing_by_col[col])
        if m_count > 0:
            col_missing_summary.append({
                "column": col,
                "missing_count": m_count,
                "valid_count": rows - m_count,
                "missing_pct": round((m_count / rows) * 100, 2) if rows > 0 else 0.0
            })
    
    missing_rows = df[df.isna().any(axis=1)].index.tolist()
    
    dup_count = int(df.duplicated().sum())
    complete_rows = rows - dup_count
    
    group2 = {
        "group_id": f"det-quality-{dataset_id}",
        "group_title": "Data Quality",
        "synthesis_insight": None,
        "sections": [
            {
                "section_id": f"det-missingness-{dataset_id}",
                "section_type": "missingness",
                "title": "Missing Value Analysis",
                "data": {
                    "total_missing_cells": total_missing,
                    "column_missing_summary": col_missing_summary,
                    "missing_row_indices": missing_rows[:100]  # limit to prevent massive payload
                },
                "interpretation": f"Found {total_missing} missing cells across {len(col_missing_summary)} columns." if total_missing > 0 else "No missing values detected in the dataset.",
                "flagged": total_missing > 0
            },
            {
                "section_id": f"det-duplicates-{dataset_id}",
                "section_type": "metric_group",
                "title": "Duplicate Rows",
                "data": {
                    "duplicate_rows": dup_count,
                    "complete_rows": complete_rows,
                    "complete_rows_pct": round((complete_rows / rows) * 100, 2) if rows > 0 else 0.0
                },
                "interpretation": f"Found {dup_count} duplicate rows." if dup_count > 0 else "No duplicate rows detected.",
                "flagged": dup_count > 0
            }
        ]
    }
    section_groups.append(group2)

    # ---------------------------------------------------------
    # Group 3: Column Statistics
    # ---------------------------------------------------------
    stats_groups = []
    for col in df.columns:
        s = df[col]
        m_count = int(s.isna().sum())
        u_count = int(s.nunique(dropna=True))
        
        if col in numeric_cols and pd.api.types.is_numeric_dtype(s):
            val_mean = float(s.mean()) if not pd.isna(s.mean()) else None
            val_median = float(s.median()) if not pd.isna(s.median()) else None
            val_std = float(s.std()) if not pd.isna(s.std()) else None
            val_min = float(s.min()) if not pd.isna(s.min()) else None
            val_max = float(s.max()) if not pd.isna(s.max()) else None
            
            stats_groups.append({
                "column": col,
                "type": "numeric",
                "missing": m_count,
                "unique": u_count,
                "mean": round(val_mean, 2) if val_mean is not None else None,
                "median": round(val_median, 2) if val_median is not None else None,
                "std": round(val_std, 2) if val_std is not None else None,
                "min": round(val_min, 2) if val_min is not None else None,
                "max": round(val_max, 2) if val_max is not None else None
            })
        else:
            val_counts = s.value_counts()
            top_val = str(val_counts.index[0]) if not val_counts.empty else None
            top_count = int(val_counts.iloc[0]) if not val_counts.empty else None
            top_pct = round((top_count / (rows - m_count)) * 100, 2) if top_count and (rows - m_count) > 0 else None
            
            stats_groups.append({
                "column": col,
                "type": "text",
                "missing": m_count,
                "unique": u_count,
                "top_value": top_val,
                "top_count": top_count,
                "top_pct": top_pct
            })

    group3 = {
        "group_id": f"det-colstats-{dataset_id}",
        "group_title": "Column Statistics",
        "synthesis_insight": None,
        "sections": [
            {
                "section_id": f"det-table-{dataset_id}",
                "section_type": "table",
                "title": "Summary Statistics",
                "data": {
                    "groups": stats_groups
                },
                "interpretation": "Statistical overview of all columns.",
                "flagged": False
            }
        ]
    }
    section_groups.append(group3)

    # ---------------------------------------------------------
    # Group 4: Important Findings
    # ---------------------------------------------------------
    findings_data = []
    
    if total_missing > 0:
        findings_data.append({"finding": f"{total_missing} missing cells across {len(col_missing_summary)} columns", "severity": "warning"})
    
    if dup_count > 0:
        findings_data.append({"finding": f"{dup_count} duplicate rows detected", "severity": "warning"})
        
    for col in df.columns:
        s = df[col]
        valid_rows = rows - int(s.isna().sum())
        if valid_rows == 0:
            continue
            
        u_count = int(s.nunique(dropna=True))
        
        if col in numeric_cols:
            val_min = s.min()
            val_max = s.max()
            if not pd.isna(val_min) and not pd.isna(val_max):
                if isinstance(val_min, float):
                    findings_data.append({"finding": f"'{col}' ranges from {val_min:.2f} to {val_max:.2f}", "severity": "info"})
                else:
                    findings_data.append({"finding": f"'{col}' ranges from {val_min} to {val_max}", "severity": "info"})
            
            if pd.api.types.is_numeric_dtype(s) and u_count > 1:
                skew_val = s.skew()
                if pd.notna(skew_val) and abs(skew_val) > 1.0:
                    skew_dir = "right-skewed" if skew_val > 0 else "left-skewed"
                    findings_data.append({"finding": f"'{col}' has a {skew_dir} distribution", "severity": "info"})
        else:
            if valid_rows > 0:
                unique_ratio = u_count / valid_rows
                if unique_ratio > 0.8 and u_count > 10:
                    findings_data.append({"finding": f"{int(unique_ratio*100)}% of '{col}' values are unique", "severity": "info"})
                elif u_count <= 10:
                    findings_data.append({"finding": f"'{col}' contains {u_count} unique values", "severity": "info"})

    # Always ensure the frontend doesn't crash on an empty list
    if not findings_data:
        findings_data.append({"finding": "Data is well-formed with no significant anomalies detected.", "severity": "info"})

    group4 = {
        "group_id": f"det-findings-{dataset_id}",
        "group_title": "Important Findings",
        "synthesis_insight": None,
        "sections": [
            {
                "section_id": f"det-dq-findings-{dataset_id}",
                "section_type": "data_quality",
                "title": "Automated Observations",
                "data": {
                    "issues": findings_data
                },
                "interpretation": "Key observations derived directly from data computations.",
                "flagged": any(f["severity"] == "warning" for f in findings_data)
            }
        ]
    }
    section_groups.append(group4)

    # ---------------------------------------------------------
    # Group 5: Distributions (for numeric columns only)
    # ---------------------------------------------------------
    dist_sections = []
    for col in numeric_cols:
        s = df[col].dropna()
        if len(s) == 0:
            continue
            
        counts, bins = np.histogram(s, bins=15)
        
        valid_count = len(s)
        missing_count = int(df[col].isna().sum())
        mean_val = float(s.mean())
        median_val = float(s.median())
        std_val = float(s.std())
        min_val = float(s.min())
        max_val = float(s.max())
        skew_val = float(s.skew()) if len(s) > 2 else 0.0
        kurt_val = float(s.kurtosis()) if len(s) > 3 else 0.0
        q1_val = float(s.quantile(0.25))
        q3_val = float(s.quantile(0.75))
        
        max_idx = np.argmax(counts)
        modal_bin_label = f"{bins[max_idx]:.2f} – {bins[max_idx+1]:.2f}"
        modal_bin_count = int(counts[max_idx])
        
        dist_sections.append({
            "section_id": f"det-dist-{col}-{dataset_id}",
            "section_type": "distribution",
            "title": f"Distribution: {col}",
            "data": {
                "counts": counts.tolist(),
                "bins": bins.tolist(),
                "valid_count": valid_count,
                "missing_count": missing_count,
                "mean": round(mean_val, 2) if not pd.isna(mean_val) else None,
                "median": round(median_val, 2) if not pd.isna(median_val) else None,
                "std": round(std_val, 2) if not pd.isna(std_val) else None,
                "min": round(min_val, 2) if not pd.isna(min_val) else None,
                "max": round(max_val, 2) if not pd.isna(max_val) else None,
                "skewness": round(skew_val, 2) if not pd.isna(skew_val) else None,
                "kurtosis": round(kurt_val, 2) if not pd.isna(kurt_val) else None,
                "q1": round(q1_val, 2) if not pd.isna(q1_val) else None,
                "q3": round(q3_val, 2) if not pd.isna(q3_val) else None,
                "modal_bin_label": modal_bin_label,
                "modal_bin_count": modal_bin_count
            },
            "interpretation": f"Distribution of {col} with mean {mean_val:.2f} and median {median_val:.2f}.",
            "flagged": False
        })
    
    if dist_sections:
        group5 = {
            "group_id": f"det-distributions-{dataset_id}",
            "group_title": "Distributions",
            "synthesis_insight": None,
            "sections": dist_sections
        }
        section_groups.append(group5)

    # ---------------------------------------------------------
    # Group 6: Categorical Breakdown (low-cardinality)
    # ---------------------------------------------------------
    cat_sections = []
    for col in cat_cols:
        s = df[col]
        valid_s = s.dropna()
        if len(valid_s) == 0:
            continue
            
        u_count = s.nunique(dropna=True)
        if u_count <= 30:
            val_counts = valid_s.value_counts().head(10)
            
            frequencies = []
            for val, count in val_counts.items():
                frequencies.append({
                    "value": str(val),
                    "count": int(count),
                    "pct": round((int(count) / len(valid_s)) * 100, 2)
                })
                
            cat_sections.append({
                "section_id": f"det-cat-{col}-{dataset_id}",
                "section_type": "chart",
                "title": f"Frequencies: {col}",
                "data": {
                    "frequencies": frequencies
                },
                "interpretation": f"Categorical breakdown of {col} (top {len(frequencies)} values).",
                "flagged": False
            })
            
    if cat_sections:
        group6 = {
            "group_id": f"det-categorical-{dataset_id}",
            "group_title": "Categorical Breakdown",
            "synthesis_insight": None,
            "sections": cat_sections
        }
        section_groups.append(group6)

    total_investigations = sum(len(g["sections"]) for g in section_groups)
    
    return {
        "status": "complete",
        "total_investigations": total_investigations,
        "successful_investigations": total_investigations,
        "complexity_tier": "standard",
        "section_groups": section_groups,
        "synthesis_text": None
    }

"""
Compute authoritative ground truth for Cross-Domain Generalization Benchmarks:
1. Retail (Sales_transactions_2022_2025.csv)
2. Healthcare (healthcare_patient_admissions.csv)
3. Banking (banking_credit_risk_portfolio.csv)
4. Manufacturing (manufacturing_sensor_telemetry.csv)
"""

import os
import json
import numpy as np
import pandas as pd

BASE_DIR = r"c:\Users\samar\Downloads\plexisv2-main\plexisv2-main\backend\storage\uploads"

# --- 1. Retail ---
df_retail = pd.read_csv(os.path.join(BASE_DIR, "Sales_transactions_2022_2025.csv"))
ret_flag_binary = (df_retail["Return_Flag"] == "Yes").astype(int)
gt_retail = {
    "rows": len(df_retail),
    "cols": len(df_retail.columns),
    "duplicates": int(df_retail.duplicated().sum()),
    "total_missing": int(df_retail.isna().sum().sum()),
    "sales_amount_mean": round(float(df_retail["Sales_Amount"].mean()), 2),
    "sales_amount_median": round(float(df_retail["Sales_Amount"].median()), 2),
    "sales_amount_max": round(float(df_retail["Sales_Amount"].max()), 2),
    "top_category": df_retail["Product_Category"].value_counts().index[0],
    "top_category_count": int(df_retail["Product_Category"].value_counts().iloc[0]),
    "return_rate_overall": round(float(ret_flag_binary.mean()), 4),
    "corr_discount_quantity": round(float(df_retail["Discount_Percentage"].corr(df_retail["Quantity"])), 4),
}

# Profit distribution by Return_Flag ('No' vs 'Yes')
p0 = df_retail[df_retail["Return_Flag"] == "No"]["Profit"].dropna()
p1 = df_retail[df_retail["Return_Flag"] == "Yes"]["Profit"].dropna()
gt_retail["profit_return_no_mean"] = round(float(p0.mean()), 2)
gt_retail["profit_return_no_median"] = round(float(p0.median()), 2)
gt_retail["profit_return_no_iqr"] = round(float(p0.quantile(0.75) - p0.quantile(0.25)), 2)
gt_retail["profit_return_yes_mean"] = round(float(p1.mean()), 2)
gt_retail["profit_return_yes_median"] = round(float(p1.median()), 2)
gt_retail["profit_return_yes_iqr"] = round(float(p1.quantile(0.75) - p1.quantile(0.25)), 2)
gt_retail["profit_median_abs_diff"] = round(abs(float(p0.median()) - float(p1.median())), 2)

# --- 2. Healthcare ---
df_health = pd.read_csv(os.path.join(BASE_DIR, "healthcare_patient_admissions.csv"))
gt_health = {
    "rows": len(df_health),
    "cols": len(df_health.columns),
    "duplicates": int(df_health.duplicated().sum()),
    "total_missing": int(df_health.isna().sum().sum()),
    "missing_billing": int(df_health["total_billing_usd"].isna().sum()),
    "missing_satisfaction": int(df_health["patient_satisfaction"].isna().sum()),
    "los_mean": round(float(df_health["length_of_stay"].mean()), 2),
    "los_median": round(float(df_health["length_of_stay"].median()), 2),
    "readmitted_rate_overall": round(float(df_health["readmitted_30d"].mean()), 4),
    "corr_age_comorbidity": round(float(df_health["age"].corr(df_health["comorbidity_index"])), 4),
}

# LOS by readmitted_30d
los0 = df_health[df_health["readmitted_30d"] == 0]["length_of_stay"].dropna()
los1 = df_health[df_health["readmitted_30d"] == 1]["length_of_stay"].dropna()
gt_health["los_readmit_0_mean"] = round(float(los0.mean()), 2)
gt_health["los_readmit_0_median"] = round(float(los0.median()), 2)
gt_health["los_readmit_0_iqr"] = round(float(los0.quantile(0.75) - los0.quantile(0.25)), 2)
gt_health["los_readmit_1_mean"] = round(float(los1.mean()), 2)
gt_health["los_readmit_1_median"] = round(float(los1.median()), 2)
gt_health["los_readmit_1_iqr"] = round(float(los1.quantile(0.75) - los1.quantile(0.25)), 2)
gt_health["los_median_abs_diff"] = round(abs(float(los0.median()) - float(los1.median())), 2)

# Readmission rate by ICU
icu_rate = df_health.groupby("icu_admitted")["readmitted_30d"].mean().to_dict()
gt_health["readmit_icu_0"] = round(float(icu_rate.get(0, 0)), 4)
gt_health["readmit_icu_1"] = round(float(icu_rate.get(1, 0)), 4)

# Top department
top_dept = df_health["department"].value_counts().index[0]
top_dept_count = int(df_health["department"].value_counts().iloc[0])
gt_health["top_department"] = top_dept
gt_health["top_department_count"] = top_dept_count


# --- 3. Banking ---
df_bank = pd.read_csv(os.path.join(BASE_DIR, "banking_credit_risk_portfolio.csv"))
gt_bank = {
    "rows": len(df_bank),
    "cols": len(df_bank.columns),
    "duplicates": int(df_bank.duplicated().sum()),
    "total_missing": int(df_bank.isna().sum().sum()),
    "missing_employment": int(df_bank["employment_years"].isna().sum()),
    "missing_income": int(df_bank["annual_income"].isna().sum()),
    "credit_score_mean": round(float(df_bank["credit_score"].mean()), 2),
    "credit_score_median": round(float(df_bank["credit_score"].median()), 2),
    "default_rate_overall": round(float(df_bank["default_flag"].mean()), 4),
    "corr_dti_interest": round(float(df_bank["debt_to_income"].corr(df_bank["interest_rate"])), 4),
}

# Credit score by default_flag
cs0 = df_bank[df_bank["default_flag"] == 0]["credit_score"].dropna()
cs1 = df_bank[df_bank["default_flag"] == 1]["credit_score"].dropna()
gt_bank["credit_default_0_mean"] = round(float(cs0.mean()), 2)
gt_bank["credit_default_0_median"] = round(float(cs0.median()), 2)
gt_bank["credit_default_0_iqr"] = round(float(cs0.quantile(0.75) - cs0.quantile(0.25)), 2)
gt_bank["credit_default_1_mean"] = round(float(cs1.mean()), 2)
gt_bank["credit_default_1_median"] = round(float(cs1.median()), 2)
gt_bank["credit_default_1_iqr"] = round(float(cs1.quantile(0.75) - cs1.quantile(0.25)), 2)
gt_bank["credit_median_abs_diff"] = round(abs(float(cs0.median()) - float(cs1.median())), 2)

# Default rate by risk tier
tier_rates = df_bank.groupby("risk_tier")["default_flag"].mean().to_dict()
gt_bank["default_rate_by_tier"] = {k: round(float(v), 4) for k, v in tier_rates.items()}


# --- 4. Manufacturing ---
df_mfg = pd.read_csv(os.path.join(BASE_DIR, "manufacturing_sensor_telemetry.csv"))
gt_mfg = {
    "rows": len(df_mfg),
    "cols": len(df_mfg.columns),
    "duplicates": int(df_mfg.duplicated().sum()),
    "total_missing": int(df_mfg.isna().sum().sum()),
    "missing_vibration": int(df_mfg["vibration_mm_s"].isna().sum()),
    "missing_pressure": int(df_mfg["pressure_bar"].isna().sum()),
    "temp_mean": round(float(df_mfg["temperature_celsius"].mean()), 2),
    "temp_median": round(float(df_mfg["temperature_celsius"].median()), 2),
    "temp_min": round(float(df_mfg["temperature_celsius"].min()), 2),
    "temp_max": round(float(df_mfg["temperature_celsius"].max()), 2),
    "defect_rate_overall": round(float(df_mfg["defect_flag"].mean()), 4),
    "corr_temp_vibration": round(float(df_mfg["temperature_celsius"].corr(df_mfg["vibration_mm_s"])), 4),
}

# Temperature by defect_flag
t0 = df_mfg[df_mfg["defect_flag"] == 0]["temperature_celsius"].dropna()
t1 = df_mfg[df_mfg["defect_flag"] == 1]["temperature_celsius"].dropna()
gt_mfg["temp_defect_0_mean"] = round(float(t0.mean()), 2)
gt_mfg["temp_defect_0_median"] = round(float(t0.median()), 2)
gt_mfg["temp_defect_0_iqr"] = round(float(t0.quantile(0.75) - t0.quantile(0.25)), 2)
gt_mfg["temp_defect_1_mean"] = round(float(t1.mean()), 2)
gt_mfg["temp_defect_1_median"] = round(float(t1.median()), 2)
gt_mfg["temp_defect_1_iqr"] = round(float(t1.quantile(0.75) - t1.quantile(0.25)), 2)
gt_mfg["temp_median_abs_diff"] = round(abs(float(t0.median()) - float(t1.median())), 2)

# Defect rate by line
line_rates = df_mfg.groupby("line_id")["defect_flag"].mean().to_dict()
gt_mfg["defect_rate_by_line"] = {k: round(float(v), 4) for k, v in line_rates.items()}

all_gt = {
    "retail": gt_retail,
    "healthcare": gt_health,
    "banking": gt_bank,
    "manufacturing": gt_mfg,
}

out_path = r"c:\Users\samar\Downloads\plexisv2-main\plexisv2-main\backend\tests\benchmarks\cross_domain_ground_truth.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(all_gt, f, indent=2)

print("SUCCESS: Computed and saved cross_domain_ground_truth.json")
for domain, d in all_gt.items():
    print(f"Domain [{domain.upper()}]: {d['rows']} rows x {d['cols']} cols | {d['duplicates']} dups | {d['total_missing']} nulls")

"""
Script to calculate and verify exact ground truth for Telco Customer Churn 60 questions.
"""
import pandas as pd
import numpy as np
import json

CSV_PATH = r"C:\Users\samar\Downloads\archive (2)\WA_Fn-UseC_-Telco-Customer-Churn.csv"
df = pd.read_csv(CSV_PATH)

gt = {}

# Q01
gt["Q01"] = {
    "rows": len(df),
    "cols": len(df.columns),
    "unique_customer_ids": df["customerID"].nunique(),
    "is_unique": bool(df["customerID"].nunique() == len(df))
}

# Q02
type_map = {}
for col in df.columns:
    type_map[col] = {
        "observed_type": str(df[col].dtype),
        "unique_count": int(df[col].nunique()),
        "true_nulls": int(df[col].isna().sum()),
        "blank_strings": int((df[col].astype(str).str.strip() == '').sum()) if df[col].dtype == object else 0
    }
gt["Q02"] = type_map

# Q03
cat_cols = df.select_dtypes(include=['object']).columns.tolist()
cat_profile = {}
for col in cat_cols:
    if col != "customerID":
        cat_profile[col] = df[col].value_counts().to_dict()
gt["Q03"] = cat_profile

# Q04
tc_raw = df["TotalCharges"]
tc_num = pd.to_numeric(tc_raw, errors="coerce")
gt["Q04"] = {
    "original_type": str(tc_raw.dtype),
    "blank_count": int((tc_raw.str.strip() == '').sum()),
    "failed_conversion_count": int(tc_num.isna().sum()),
    "valid_count": int(tc_num.notna().sum()),
    "mean": round(float(tc_num.mean()), 2),
    "median": round(float(tc_num.median()), 2),
    "min": round(float(tc_num.min()), 2),
    "max": round(float(tc_num.max()), 2),
    "std": round(float(tc_num.std()), 2)
}

# Q05
gt["Q05"] = {
    "duplicate_ids": int(len(df) - df["customerID"].nunique()),
    "duplicate_rows": int(df.duplicated().sum()),
    "is_valid_pk": True
}

# Q06
ten = df["tenure"]
mc = df["MonthlyCharges"]
gt["Q06"] = {
    "tenure": {
        "count": int(ten.count()), "mean": round(float(ten.mean()), 2), "median": round(float(ten.median()), 2),
        "std": round(float(ten.std()), 2), "min": round(float(ten.min()), 2), "max": round(float(ten.max()), 2),
        "q1": round(float(ten.quantile(0.25)), 2), "q3": round(float(ten.quantile(0.75)), 2),
        "iqr": round(float(ten.quantile(0.75) - ten.quantile(0.25)), 2)
    },
    "MonthlyCharges": {
        "count": int(mc.count()), "mean": round(float(mc.mean()), 2), "median": round(float(mc.median()), 2),
        "std": round(float(mc.std()), 2), "min": round(float(mc.min()), 2), "max": round(float(mc.max()), 2),
        "q1": round(float(mc.quantile(0.25)), 2), "q3": round(float(mc.quantile(0.75)), 2),
        "iqr": round(float(mc.quantile(0.75) - mc.quantile(0.25)), 2)
    },
    "TotalCharges": {
        "count": int(tc_num.notna().sum()), "mean": round(float(tc_num.mean()), 2), "median": round(float(tc_num.median()), 2),
        "std": round(float(tc_num.std()), 2), "min": round(float(tc_num.min()), 2), "max": round(float(tc_num.max()), 2),
        "q1": round(float(tc_num.quantile(0.25)), 2), "q3": round(float(tc_num.quantile(0.75)), 2),
        "iqr": round(float(tc_num.quantile(0.75) - tc_num.quantile(0.25)), 2)
    }
}

# Q07
ch_counts = df["Churn"].value_counts().to_dict()
gt["Q07"] = {
    "counts": ch_counts,
    "percentages": {k: round(v / len(df) * 100, 2) for k, v in ch_counts.items()},
    "denominator": len(df)
}

# Q08
gt["Q08"] = {
    "SeniorCitizen_unique": sorted(df["SeniorCitizen"].unique().tolist()),
    "tenure_min_max": [int(ten.min()), int(ten.max())],
    "MonthlyCharges_min_max": [float(mc.min()), float(mc.max())],
    "TotalCharges_valid_min_max": [float(tc_num.min()), float(tc_num.max())],
    "TotalCharges_blanks": 11,
    "tenure_zero_count": int((df["tenure"] == 0).sum())
}

# Q09
gt["Q09"] = {
    "exact_duplicates": 0,
    "duplicate_customer_ids": 0,
    "invalid_numeric_values": 11,
    "impact": "11 rows have blank TotalCharges corresponding to tenure=0 (new customers). They can be analyzed for tenure and monthly charges, but require coercion/handling for TotalCharges."
}

# Q10
gt["Q10"] = {
    "rows": len(df),
    "cols": len(df.columns),
    "customer_ids_unique": 7043,
    "tc_valid": 7032,
    "tc_blank": 11
}

# Q11
c_grp = df.groupby("Contract")["Churn"].value_counts().unstack(fill_value=0)
c_grp["Total"] = c_grp.sum(axis=1)
c_grp["ChurnRate"] = (c_grp["Yes"] / c_grp["Total"] * 100).round(2)
gt["Q11"] = c_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q12
i_grp = df.groupby("InternetService")["Churn"].value_counts().unstack(fill_value=0)
i_grp["Total"] = i_grp.sum(axis=1)
i_grp["ChurnRate"] = (i_grp["Yes"] / i_grp["Total"] * 100).round(2)
gt["Q12"] = {
    "groups": i_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "highest": "Fiber optic",
    "lowest": "No"
}

# Q13
p_grp = df.groupby("PaymentMethod")["Churn"].value_counts().unstack(fill_value=0)
p_grp["Total"] = p_grp.sum(axis=1)
p_grp["ChurnRate"] = (p_grp["Yes"] / p_grp["Total"] * 100).round(2)
gt["Q13"] = p_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q14
pb_grp = df.groupby("PaperlessBilling")["Churn"].value_counts().unstack(fill_value=0)
pb_grp["Total"] = pb_grp.sum(axis=1)
pb_grp["ChurnRate"] = (pb_grp["Yes"] / pb_grp["Total"] * 100).round(2)
gt["Q14"] = {
    "groups": pb_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "difference_pp": round(pb_grp.loc["Yes", "ChurnRate"] - pb_grp.loc["No", "ChurnRate"], 2)
}

# Q15
part_grp = df.groupby("Partner")["Churn"].value_counts().unstack(fill_value=0)
part_grp["Total"] = part_grp.sum(axis=1)
part_grp["ChurnRate"] = (part_grp["Yes"] / part_grp["Total"] * 100).round(2)
dep_grp = df.groupby("Dependents")["Churn"].value_counts().unstack(fill_value=0)
dep_grp["Total"] = dep_grp.sum(axis=1)
dep_grp["ChurnRate"] = (dep_grp["Yes"] / dep_grp["Total"] * 100).round(2)
gt["Q15"] = {
    "Partner": part_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "Dependents": dep_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")
}

# Q16
gen_grp = df.groupby("gender")["Churn"].value_counts().unstack(fill_value=0)
gen_grp["Total"] = gen_grp.sum(axis=1)
gen_grp["ChurnRate"] = (gen_grp["Yes"] / gen_grp["Total"] * 100).round(2)
sen_grp = df.groupby("SeniorCitizen")["Churn"].value_counts().unstack(fill_value=0)
sen_grp["Total"] = sen_grp.sum(axis=1)
sen_grp["ChurnRate"] = (sen_grp["Yes"] / sen_grp["Total"] * 100).round(2)
gt["Q16"] = {
    "gender": gen_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "SeniorCitizen": sen_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")
}

# Q17
ps_grp = df.groupby("PhoneService")["Churn"].value_counts().unstack(fill_value=0)
ps_grp["Total"] = ps_grp.sum(axis=1)
ps_grp["ChurnRate"] = (ps_grp["Yes"] / ps_grp["Total"] * 100).round(2)
ml_grp = df.groupby("MultipleLines")["Churn"].value_counts().unstack(fill_value=0)
ml_grp["Total"] = ml_grp.sum(axis=1)
ml_grp["ChurnRate"] = (ml_grp["Yes"] / ml_grp["Total"] * 100).round(2)
gt["Q17"] = {
    "PhoneService": ps_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "MultipleLines": ml_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")
}

# Q18
features_q18 = ["OnlineSecurity", "OnlineBackup", "DeviceProtection", "TechSupport"]
gt_q18 = {}
for feat in features_q18:
    f_grp = df.groupby(feat)["Churn"].value_counts().unstack(fill_value=0)
    f_grp["Total"] = f_grp.sum(axis=1)
    f_grp["ChurnRate"] = (f_grp["Yes"] / f_grp["Total"] * 100).round(2)
    gt_q18[feat] = f_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")
gt["Q18"] = gt_q18

# Q19
tv_grp = df.groupby("StreamingTV")["Churn"].value_counts().unstack(fill_value=0)
tv_grp["Total"] = tv_grp.sum(axis=1)
tv_grp["ChurnRate"] = (tv_grp["Yes"] / tv_grp["Total"] * 100).round(2)
mov_grp = df.groupby("StreamingMovies")["Churn"].value_counts().unstack(fill_value=0)
mov_grp["Total"] = mov_grp.sum(axis=1)
mov_grp["ChurnRate"] = (mov_grp["Yes"] / mov_grp["Total"] * 100).round(2)
gt["Q19"] = {
    "StreamingTV": tv_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "StreamingMovies": mov_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")
}

# Q20
all_cats = []
for col in ["Contract", "InternetService", "PaymentMethod"]:
    c_df = df.groupby(col)["Churn"].value_counts().unstack(fill_value=0)
    c_df["Total"] = c_df.sum(axis=1)
    c_df["ChurnRate"] = (c_df["Yes"] / c_df["Total"] * 100).round(2)
    for idx, row in c_df.iterrows():
        all_cats.append({"Feature": col, "Category": idx, "Count": int(row["Total"]), "ChurnCount": int(row["Yes"]), "ChurnRate": float(row["ChurnRate"])})
all_cats = sorted(all_cats, key=lambda x: x["ChurnRate"], reverse=True)
gt["Q20"] = all_cats

# Q21: 2D table Contract x InternetService
ci_grp = df.groupby(["Contract", "InternetService"])["Churn"].value_counts().unstack(fill_value=0)
ci_grp["Total"] = ci_grp.sum(axis=1)
ci_grp["ChurnRate"] = (ci_grp["Yes"] / ci_grp["Total"] * 100).round(2)
gt["Q21"] = ci_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q22: Contract x PaymentMethod >= 50
cp_grp = df.groupby(["Contract", "PaymentMethod"])["Churn"].value_counts().unstack(fill_value=0)
cp_grp["Total"] = cp_grp.sum(axis=1)
cp_grp["ChurnRate"] = (cp_grp["Yes"] / cp_grp["Total"] * 100).round(2)
cp_eligible = cp_grp[cp_grp["Total"] >= 50].sort_values("ChurnRate", ascending=False)
gt["Q22"] = {
    "eligible": cp_eligible[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index"),
    "excluded": cp_grp[cp_grp["Total"] < 50][["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")
}

# Q23: InternetService x TechSupport >= 100, top 5 highest churn
it_grp = df.groupby(["InternetService", "TechSupport"])["Churn"].value_counts().unstack(fill_value=0)
it_grp["Total"] = it_grp.sum(axis=1)
it_grp["ChurnRate"] = (it_grp["Yes"] / it_grp["Total"] * 100).round(2)
it_eligible = it_grp[it_grp["Total"] >= 100].sort_values("ChurnRate", ascending=False)
gt["Q23"] = it_eligible.head(5)[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q24: Contract x PaperlessBilling difference
cpb = df.groupby(["Contract", "PaperlessBilling"])["Churn"].value_counts().unstack(fill_value=0)
cpb["Total"] = cpb.sum(axis=1)
cpb["ChurnRate"] = (cpb["Yes"] / cpb["Total"] * 100).round(2)
diffs_q24 = {}
for contract in df["Contract"].unique():
    r_yes = cpb.loc[(contract, "Yes"), "ChurnRate"]
    r_no = cpb.loc[(contract, "No"), "ChurnRate"]
    diffs_q24[contract] = {"Yes": r_yes, "No": r_no, "diff_pp": round(abs(r_yes - r_no), 2)}
gt["Q24"] = diffs_q24

# Q25: SeniorCitizen x Contract
sc_grp = df.groupby(["SeniorCitizen", "Contract"])["Churn"].value_counts().unstack(fill_value=0)
sc_grp["Total"] = sc_grp.sum(axis=1)
sc_grp["ChurnRate"] = (sc_grp["Yes"] / sc_grp["Total"] * 100).round(2)
gt["Q25"] = sc_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q26: Dependents within Contract
cd_grp = df.groupby(["Contract", "Dependents"])["Churn"].value_counts().unstack(fill_value=0)
cd_grp["Total"] = cd_grp.sum(axis=1)
cd_grp["ChurnRate"] = (cd_grp["Yes"] / cd_grp["Total"] * 100).round(2)
gt["Q26"] = cd_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q27: InternetService x OnlineSecurity x TechSupport >= 50
iot_grp = df.groupby(["InternetService", "OnlineSecurity", "TechSupport"])["Churn"].value_counts().unstack(fill_value=0)
iot_grp["Total"] = iot_grp.sum(axis=1)
iot_grp["ChurnRate"] = (iot_grp["Yes"] / iot_grp["Total"] * 100).round(2)
iot_eligible = iot_grp[iot_grp["Total"] >= 50].sort_values("ChurnRate", ascending=False)
gt["Q27"] = iot_eligible[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q28: Difference between Month-to-month and Two year within PaymentMethod
pm_diffs = {}
for pm in df["PaymentMethod"].unique():
    sub = df[df["PaymentMethod"] == pm]
    m2m = sub[sub["Contract"] == "Month-to-month"]
    two_yr = sub[sub["Contract"] == "Two year"]
    r_m2m = round((m2m["Churn"] == "Yes").mean() * 100, 2)
    r_two_yr = round((two_yr["Churn"] == "Yes").mean() * 100, 2)
    pm_diffs[pm] = {
        "Month-to-month_rate": r_m2m,
        "Two_year_rate": r_two_yr,
        "diff_pp": round(r_m2m - r_two_yr, 2)
    }
gt["Q28"] = pm_diffs

# Q29: Service category with largest churn rate diff vs other categories in same feature
service_cols = ["OnlineSecurity", "OnlineBackup", "DeviceProtection", "TechSupport", "StreamingTV", "StreamingMovies", "PhoneService", "MultipleLines", "InternetService"]
diffs_q29 = []
for col in service_cols:
    overall_mean = (df["Churn"] == "Yes").mean()
    for cat in df[col].unique():
        in_cat = df[df[col] == cat]
        out_cat = df[df[col] != cat]
        r_in = (in_cat["Churn"] == "Yes").mean() * 100
        r_out = (out_cat["Churn"] == "Yes").mean() * 100
        diffs_q29.append({
            "feature": col,
            "category": cat,
            "in_count": len(in_cat),
            "out_count": len(out_cat),
            "in_rate": round(r_in, 2),
            "out_rate": round(r_out, 2),
            "abs_diff": round(abs(r_in - r_out), 2)
        })
diffs_q29 = sorted(diffs_q29, key=lambda x: x["abs_diff"], reverse=True)
gt["Q29"] = diffs_q29[0]

# Q30: 3 largest customer segments (Contract, InternetService, PaymentMethod)
cip = df.groupby(["Contract", "InternetService", "PaymentMethod"]).size().reset_index(name="count")
cip["share_pct"] = (cip["count"] / len(df) * 100).round(2)
churn_rates_cip = []
for _, row in cip.iterrows():
    sub = df[(df["Contract"] == row["Contract"]) & (df["InternetService"] == row["InternetService"]) & (df["PaymentMethod"] == row["PaymentMethod"])]
    churn_rates_cip.append(round((sub["Churn"] == "Yes").mean() * 100, 2))
cip["churn_rate"] = churn_rates_cip
top3_cip = cip.sort_values("count", ascending=False).head(3)
gt["Q30"] = top3_cip.to_dict(orient="records")

# Q31: Pearson correlations (tenure, MonthlyCharges, TotalCharges, binary Churn)
df_clean = df[tc_num.notna()].copy()
df_clean["TotalCharges_num"] = pd.to_numeric(df_clean["TotalCharges"])
df_clean["Churn_binary"] = (df_clean["Churn"] == "Yes").astype(int)
corr_matrix = df_clean[["tenure", "MonthlyCharges", "TotalCharges_num", "Churn_binary"]].corr(method="pearson").round(4)
gt["Q31"] = {
    "matrix": corr_matrix.to_dict(),
    "n": len(df_clean),
    "encoding": "Churn: Yes=1, No=0"
}

# Q32: Pearson and Spearman between tenure and TotalCharges
r_pearson = df_clean["tenure"].corr(df_clean["TotalCharges_num"], method="pearson")
r_spearman = df_clean["tenure"].rank().corr(df_clean["TotalCharges_num"].rank(), method="pearson")
gt["Q32"] = {
    "pearson": round(float(r_pearson), 4),
    "spearman": round(float(r_spearman), 4),
    "n": len(df_clean)
}

# Q33: Correlation between MonthlyCharges and TotalCharges
r_mc_tc = df_clean["MonthlyCharges"].corr(df_clean["TotalCharges_num"], method="pearson")
gt["Q33"] = {
    "pearson": round(float(r_mc_tc), 4),
    "n": len(df_clean)
}

# Q34: tenure quartiles
df["tenure_q"] = pd.qcut(df["tenure"], q=4, duplicates="drop")
q34_grp = df.groupby("tenure_q", observed=False)["Churn"].value_counts().unstack(fill_value=0)
q34_grp["Total"] = q34_grp.sum(axis=1)
q34_grp["ChurnRate"] = (q34_grp["Yes"] / q34_grp["Total"] * 100).round(2)
gt["Q34"] = {str(k): v for k, v in q34_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index").items()}

# Q35: MonthlyCharges quartiles
df["mc_q"] = pd.qcut(df["MonthlyCharges"], q=4)
q35_grp = df.groupby("mc_q", observed=False).agg(
    count=("MonthlyCharges", "count"),
    mean_mc=("MonthlyCharges", "mean"),
    median_mc=("MonthlyCharges", "median"),
    churn_count=("Churn", lambda s: (s == "Yes").sum()),
    churn_rate=("Churn", lambda s: round((s == "Yes").mean() * 100, 2))
).round(2)
gt["Q35"] = {str(k): v for k, v in q35_grp.to_dict(orient="index").items()}

# Q36: Tenure bands: 0-12, 13-24, 25-48, 49-72
bins = [-1, 12, 24, 48, 72]
labels = ["0-12", "13-24", "25-48", "49-72"]
df["tenure_band"] = pd.cut(df["tenure"], bins=bins, labels=labels)
q36_grp = df.groupby("tenure_band", observed=False)["Churn"].value_counts().unstack(fill_value=0)
q36_grp["Total"] = q36_grp.sum(axis=1)
q36_grp["ChurnRate"] = (q36_grp["Yes"] / q36_grp["Total"] * 100).round(2)
gt["Q36"] = q36_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q37: MonthlyCharges for churned vs non-churned
mc_ch = df[df["Churn"] == "Yes"]["MonthlyCharges"]
mc_noch = df[df["Churn"] == "No"]["MonthlyCharges"]
gt["Q37"] = {
    "churned": {"count": len(mc_ch), "mean": round(float(mc_ch.mean()), 2), "median": round(float(mc_ch.median()), 2), "std": round(float(mc_ch.std()), 2)},
    "non_churned": {"count": len(mc_noch), "mean": round(float(mc_noch.mean()), 2), "median": round(float(mc_noch.median()), 2), "std": round(float(mc_noch.std()), 2)},
    "mean_diff": round(float(mc_ch.mean() - mc_noch.mean()), 2),
    "median_diff": round(float(mc_ch.median() - mc_noch.median()), 2)
}

# Q38: Tenure for churned vs non-churned
ten_ch = df[df["Churn"] == "Yes"]["tenure"]
ten_noch = df[df["Churn"] == "No"]["tenure"]
gt["Q38"] = {
    "churned": {"count": len(ten_ch), "mean": round(float(ten_ch.mean()), 2), "median": round(float(ten_ch.median()), 2), "q1": round(float(ten_ch.quantile(0.25)), 2), "q3": round(float(ten_ch.quantile(0.75)), 2)},
    "non_churned": {"count": len(ten_noch), "mean": round(float(ten_noch.mean()), 2), "median": round(float(ten_noch.median()), 2), "q1": round(float(ten_noch.quantile(0.25)), 2), "q3": round(float(ten_noch.quantile(0.75)), 2)},
    "median_diff": round(abs(float(ten_ch.median() - ten_noch.median())), 2)
}

# Q39: Deciles of MonthlyCharges
df["mc_decile"] = pd.qcut(df["MonthlyCharges"], q=10)
q39_grp = df.groupby("mc_decile", observed=False).agg(
    count=("MonthlyCharges", "count"),
    churn_count=("Churn", lambda s: (s == "Yes").sum()),
    churn_rate=("Churn", lambda s: round((s == "Yes").mean() * 100, 2))
)
gt["Q39"] = {str(k): v for k, v in q39_grp.to_dict(orient="index").items()}

# Q40: Tenure vs Churn association measure (Point-biserial correlation / Cramer's V)
df["churn_int"] = (df["Churn"] == "Yes").astype(int)
pbc = df["churn_int"].corr(df["tenure"], method="pearson")
gt["Q40"] = {
    "point_biserial_correlation": round(float(pbc), 4),
    "n": len(df)
}

# Q41: tenure <= 12 and MonthlyCharges > median(70.35)
mc_med = float(df["MonthlyCharges"].median())
q41_sub = df[(df["tenure"] <= 12) & (df["MonthlyCharges"] > mc_med)]
gt["Q41"] = {
    "median_threshold": mc_med,
    "total_count": len(q41_sub),
    "churn_count": int((q41_sub["Churn"] == "Yes").sum()),
    "non_churn_count": int((q41_sub["Churn"] == "No").sum()),
    "churn_rate": round((q41_sub["Churn"] == "Yes").mean() * 100, 2),
    "mean_monthly_charges": round(float(q41_sub["MonthlyCharges"].mean()), 2)
}

# Q42: Contract = Month-to-month and PaperlessBilling = Yes: Electronic check vs other
q42_pop = df[(df["Contract"] == "Month-to-month") & (df["PaperlessBilling"] == "Yes")]
e_check = q42_pop[q42_pop["PaymentMethod"] == "Electronic check"]
other_pm = q42_pop[q42_pop["PaymentMethod"] != "Electronic check"]
gt["Q42"] = {
    "electronic_check": {
        "denominator": len(e_check),
        "churn_count": int((e_check["Churn"] == "Yes").sum()),
        "churn_rate": round((e_check["Churn"] == "Yes").mean() * 100, 2)
    },
    "other_methods": {
        "denominator": len(other_pm),
        "churn_count": int((other_pm["Churn"] == "Yes").sum()),
        "churn_rate": round((other_pm["Churn"] == "Yes").mean() * 100, 2)
    }
}

# Q43: InternetService = Fiber optic: OnlineSecurity categories >= 100
fo = df[df["InternetService"] == "Fiber optic"]
fo_os = fo.groupby("OnlineSecurity")["Churn"].value_counts().unstack(fill_value=0)
fo_os["Total"] = fo_os.sum(axis=1)
fo_os["ChurnRate"] = (fo_os["Yes"] / fo_os["Total"] * 100).round(2)
gt["Q43"] = fo_os[fo_os["Total"] >= 100].sort_values("ChurnRate", ascending=False)[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q44: tenure >= 24 and MonthlyCharges > median(70.35), by contract
q44_sub = df[(df["tenure"] >= 24) & (df["MonthlyCharges"] > mc_med)]
q44_grp = q44_sub.groupby("Contract")["Churn"].value_counts().unstack(fill_value=0)
q44_grp["Total"] = q44_grp.sum(axis=1)
q44_grp["ChurnRate"] = (q44_grp["Yes"] / q44_grp["Total"] * 100).round(2)
gt["Q44"] = q44_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index")

# Q45: estimated_charge_per_tenure_month = TotalCharges / tenure (tenure > 0)
df_tpos = df[df["tenure"] > 0].copy()
df_tpos["tc_num"] = pd.to_numeric(df_tpos["TotalCharges"], errors="coerce")
df_tpos["ratio"] = df_tpos["tc_num"] / df_tpos["tenure"]
gt["Q45"] = {
    "overall": {"mean": round(float(df_tpos["ratio"].mean()), 2), "median": round(float(df_tpos["ratio"].median()), 2)},
    "churn_yes": {"mean": round(float(df_tpos[df_tpos["Churn"]=="Yes"]["ratio"].mean()), 2), "median": round(float(df_tpos[df_tpos["Churn"]=="Yes"]["ratio"].median()), 2)},
    "churn_no": {"mean": round(float(df_tpos[df_tpos["Churn"]=="No"]["ratio"].mean()), 2), "median": round(float(df_tpos[df_tpos["Churn"]=="No"]["ratio"].median()), 2)},
    "eligible_rows": len(df_tpos)
}

# Q46: TotalCharges vs MonthlyCharges * tenure
df_clean["expected_tc"] = df_clean["MonthlyCharges"] * df_clean["tenure"]
df_clean["abs_diff"] = (df_clean["TotalCharges_num"] - df_clean["expected_tc"]).abs()
df_clean["rel_diff_pct"] = np.where(df_clean["expected_tc"] > 0, df_clean["abs_diff"] / df_clean["expected_tc"] * 100, 0)
gt["Q46"] = {
    "mean_abs_diff": round(float(df_clean["abs_diff"].mean()), 2),
    "median_abs_diff": round(float(df_clean["abs_diff"].median()), 2),
    "max_abs_diff": round(float(df_clean["abs_diff"].max()), 2),
    "mean_rel_diff_pct": round(float(df_clean["rel_diff_pct"].mean()), 2),
    "exact_match_count": int((df_clean["abs_diff"] < 0.01).sum()),
    "total_eligible": len(df_clean)
}

# Q47: Contract x tenure quartile combinations (valid TotalCharges)
df_clean["tenure_q"] = pd.qcut(df_clean["tenure"], q=4, duplicates="drop")
q47_grp = df_clean.groupby(["Contract", "tenure_q"], observed=False)["Churn"].value_counts().unstack(fill_value=0)
q47_grp["Total"] = q47_grp.sum(axis=1)
q47_grp["ChurnRate"] = (q47_grp["Yes"] / q47_grp["Total"] * 100).round(2)
gt["Q47"] = {f"{k[0]}__{str(k[1])}": v for k, v in q47_grp[["Total", "Yes", "No", "ChurnRate"]].to_dict(orient="index").items()}

# Q48: Contract = Month-to-month & PaperlessBilling = Yes & PaymentMethod = Electronic check & Churn = Yes
comb = (df["Contract"] == "Month-to-month") & (df["PaperlessBilling"] == "Yes") & (df["PaymentMethod"] == "Electronic check")
comb_churn = comb & (df["Churn"] == "Yes")
gt["Q48"] = {
    "numerator": int(comb_churn.sum()),
    "denominator": len(df),
    "percentage": round(comb_churn.sum() / len(df) * 100, 2)
}

# Q49: Above vs below median MonthlyCharges
above_med = df[df["MonthlyCharges"] > mc_med]
below_med = df[df["MonthlyCharges"] < mc_med]
eq_med = df[df["MonthlyCharges"] == mc_med]
gt["Q49"] = {
    "median": mc_med,
    "above_count": len(above_med),
    "above_churn_rate": round((above_med["Churn"] == "Yes").mean() * 100, 2),
    "below_count": len(below_med),
    "below_churn_rate": round((below_med["Churn"] == "Yes").mean() * 100, 2),
    "equal_count": len(eq_med)
}

# Q50: Short tenure (<=12) and high monthly charges (> median) vs remaining
st_hc = (df["tenure"] <= 12) & (df["MonthlyCharges"] > mc_med)
st_lc = (df["tenure"] <= 12) & (df["MonthlyCharges"] <= mc_med)
lt_hc = (df["tenure"] > 12) & (df["MonthlyCharges"] > mc_med)
lt_lc = (df["tenure"] > 12) & (df["MonthlyCharges"] <= mc_med)
gt["Q50"] = {
    "short_tenure_high_charge": {"count": int(st_hc.sum()), "churn_rate": round((df[st_hc]["Churn"] == "Yes").mean() * 100, 2)},
    "remaining_customers": {"count": int((~st_hc).sum()), "churn_rate": round((df[~st_hc]["Churn"] == "Yes").mean() * 100, 2)},
    "all_four_counts": {
        "st_hc": int(st_hc.sum()), "st_lc": int(st_lc.sum()), "lt_hc": int(lt_hc.sum()), "lt_lc": int(lt_lc.sum())
    }
}

# Q51: Average MonthlyCharges churned vs hypothetical excluding churned
gt["Q51"] = {
    "churned_mean": round(float(mc_ch.mean()), 2),
    "remaining_mean": round(float(mc_noch.mean()), 2),
    "dataset_unmodified": True
}

# Q52: Hypothetically exclude tenure = 0
t0_count = int((df["tenure"] == 0).sum())
df_t_nonzero = df[df["tenure"] > 0]
gt["Q52"] = {
    "excluded_count": t0_count,
    "remaining_count": len(df_t_nonzero),
    "original_churn_rate": round((df["Churn"] == "Yes").mean() * 100, 2),
    "new_churn_rate": round((df_t_nonzero["Churn"] == "Yes").mean() * 100, 2),
    "difference_pp": round((df_t_nonzero["Churn"] == "Yes").mean() * 100 - (df["Churn"] == "Yes").mean() * 100, 4)
}

# Q53: Cap MonthlyCharges at 95th percentile
p95 = float(df["MonthlyCharges"].quantile(0.95))
affected_rows = int((df["MonthlyCharges"] > p95).sum())
capped_mc = df["MonthlyCharges"].clip(upper=p95)
gt["Q53"] = {
    "p95_threshold": round(p95, 2),
    "affected_rows": affected_rows,
    "original_mean": round(float(df["MonthlyCharges"].mean()), 2),
    "capped_mean": round(float(capped_mc.mean()), 2),
    "mean_diff": round(float(df["MonthlyCharges"].mean() - capped_mc.mean()), 2)
}

# Q54: TotalCharges safe conversion audit
gt["Q54"] = {
    "valid_conversions": int(tc_num.notna().sum()),
    "blank_or_whitespace": int((tc_raw.str.strip() == '').sum()),
    "nonblank_invalid": int(tc_num.isna().sum() - (tc_raw.str.strip() == '').sum())
}

# Q55: Nonexistent column CustomerSatisfactionScore
gt["Q55"] = {
    "column": "CustomerSatisfactionScore",
    "exists": False,
    "expected_action": "Reject / state unsupported column"
}

# Q56: Missing ticket price
gt["Q56"] = {
    "column": "ticket price",
    "exists": False,
    "expected_action": "Identify missing field, require additional ticketing data"
}

# Q57: customerID validity as numeric predictor
gt["Q57"] = {
    "column": "customerID",
    "type": "object / string",
    "is_unique_identifier": True,
    "is_valid_numeric_predictor": False
}

# Q58: Counterfactual contract change causation
gt["Q58"] = {
    "observational_difference": "Month-to-month churn is 42.71% vs Two year 2.83%",
    "causal_validity": False,
    "explanation": "Correlation is not causation. Self-selection, tenure differences, and customer commitment confound observational rates."
}

# Q59: Target leakage risk
gt["Q59"] = {
    "target": "Churn",
    "potential_leakage_risks": "TotalCharges and tenure may reflect customer lifetime directly; timing of record must precede churn event."
}

# Q60: Final integrity verification
gt["Q60"] = {
    "rows": 7043,
    "cols": 21,
    "customer_ids_unique": 7043,
    "totalcharges_blanks": 11,
    "dataset_unmodified": True
}

def make_json_serializable(obj):
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            key_str = "__".join(str(x) for x in k) if isinstance(k, tuple) else str(k)
            new_dict[key_str] = make_json_serializable(v)
        return new_dict
    elif isinstance(obj, (list, tuple)):
        return [make_json_serializable(x) for x in obj]
    elif isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64)):
        return float(obj)
    return obj

gt_serializable = make_json_serializable(gt)

output_path = r"c:\Users\samar\Downloads\plexisv2-main\plexisv2-main\backend\tests\benchmarks\telco_benchmark_ground_truth.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(gt_serializable, f, indent=2)

print(f"Ground truth written successfully with {len(gt_serializable)} questions.")

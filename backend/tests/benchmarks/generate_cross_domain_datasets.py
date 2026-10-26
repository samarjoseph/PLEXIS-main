"""
Cross-Domain Dataset Generator for Plexis Benchmarks.

Generates complex, realistic datasets across multiple industries:
1. Healthcare Operations: 10,000 rows x 18 cols (Readmissions, Billing, Length of Stay)
2. Banking Credit Risk: 15,000 rows x 16 cols (Loan defaults, DTI, Credit Scores)
3. Manufacturing Sensor Telemetry: 12,000 rows x 15 cols (Predictive maintenance, vibration, thermal)

All datasets contain realistic complexities:
- Missing values (1-4%)
- Duplicate records (0.1-0.2%)
- Skewed distributions and outliers
- High-cardinality categories
- Mixed numeric, temporal, and categorical types
"""

import os
import numpy as np
import pandas as pd

np.random.seed(42)
OUTPUT_DIR = r"c:\Users\samar\Downloads\plexisv2-main\plexisv2-main\backend\storage\uploads"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def generate_healthcare():
    n = 10000
    patient_ids = [f"PAT_{i:06d}" for i in range(1, n + 1)]
    ages = np.random.normal(54, 18, n).clip(18, 95).astype(int)
    genders = np.random.choice(["Female", "Male", "Non-Binary"], n, p=[0.51, 0.47, 0.02])
    admission_types = np.random.choice(["Emergency", "Elective", "Urgent", "Newborn"], n, p=[0.45, 0.35, 0.15, 0.05])
    departments = np.random.choice(
        ["Cardiology", "Oncology", "Orthopedics", "Neurology", "Pediatrics", "General Surgery", "ICU"],
        n, p=[0.20, 0.15, 0.18, 0.12, 0.08, 0.17, 0.10]
    )
    # Lognormal length of stay
    los = np.random.lognormal(1.2, 0.7, n).clip(1, 45).round(1)
    
    # Skewed billing amount with extreme outliers
    billing = (los * np.random.lognormal(7.8, 0.6, n) + np.random.normal(5000, 2000, n)).clip(800, 250000).round(2)
    
    insurers = np.random.choice(["BlueCross", "Medicare", "Medicaid", "UnitedHealth", "Aetna", "Self-Pay"], n, p=[0.28, 0.25, 0.15, 0.18, 0.10, 0.04])
    icu_flags = np.random.choice([0, 1], n, p=[0.82, 0.18])
    comorbidity_idx = np.random.poisson(1.8, n).clip(0, 8)
    
    # Readmission probability correlated with age, ICU, and comorbidity
    logit = -2.2 + 0.015 * (ages - 50) + 0.7 * icu_flags + 0.25 * comorbidity_idx
    prob_readmit = 1.0 / (1.0 + np.exp(-logit))
    readmit_30d = (np.random.rand(n) < prob_readmit).astype(int)
    
    satisfaction = np.random.choice([1, 2, 3, 4, 5], n, p=[0.05, 0.10, 0.25, 0.38, 0.22])

    df = pd.DataFrame({
        "patient_id": patient_ids,
        "age": ages,
        "gender": genders,
        "admission_type": admission_types,
        "department": departments,
        "length_of_stay": los,
        "total_billing_usd": billing,
        "insurance_provider": insurers,
        "icu_admitted": icu_flags,
        "comorbidity_index": comorbidity_idx,
        "readmitted_30d": readmit_30d,
        "patient_satisfaction": satisfaction,
        "doctor_id": [f"DOC_{np.random.randint(101, 220)}" for _ in range(n)],
        "discharge_disposition": np.random.choice(["Home", "Rehabilitation", "SNF", "Hospice", "Expired"], n, p=[0.75, 0.12, 0.08, 0.03, 0.02]),
    })

    # Introduce 1.5% missing values in billing and satisfaction
    mask_bill = np.random.rand(n) < 0.015
    df.loc[mask_bill, "total_billing_usd"] = np.nan
    mask_sat = np.random.rand(n) < 0.02
    df.loc[mask_sat, "patient_satisfaction"] = np.nan

    # Introduce 8 duplicate rows
    dups = df.sample(8, random_state=42)
    df = pd.concat([df, dups], ignore_index=True)

    path = os.path.join(OUTPUT_DIR, "healthcare_patient_admissions.csv")
    df.to_csv(path, index=False)
    print(f"Generated Healthcare: {df.shape} -> {path}")
    return df


def generate_banking():
    n = 15000
    account_ids = [f"ACC_{i:07d}" for i in range(1, n + 1)]
    incomes = np.random.lognormal(10.8, 0.55, n).clip(18000, 450000).round(2)
    credit_scores = np.random.normal(685, 65, n).clip(450, 850).astype(int)
    dti = np.random.beta(2.5, 5.0, n).clip(0.02, 0.65).round(4)
    loan_amounts = (incomes * np.random.uniform(0.1, 0.65, n)).clip(2000, 100000).round(2)
    loan_terms = np.random.choice([12, 24, 36, 48, 60], n, p=[0.05, 0.10, 0.45, 0.15, 0.25])
    interest_rates = (22.5 - 0.02 * credit_scores + 8.0 * dti + np.random.normal(0, 1.2, n)).clip(3.5, 29.9).round(2)
    employment_yrs = np.random.exponential(5.5, n).clip(0, 35).round(1)
    home_ownership = np.random.choice(["RENT", "MORTGAGE", "OWN", "OTHER"], n, p=[0.42, 0.45, 0.12, 0.01])
    loan_purpose = np.random.choice(
        ["debt_consolidation", "credit_card", "home_improvement", "small_business", "medical", "auto"],
        n, p=[0.50, 0.22, 0.12, 0.06, 0.06, 0.04]
    )
    delinq_2yr = np.random.poisson(0.35, n).clip(0, 8)
    
    # Default flag correlated with credit score, DTI, and delinquencies
    logit = -1.5 - 0.008 * (credit_scores - 650) + 3.2 * dti + 0.4 * delinq_2yr
    prob_def = 1.0 / (1.0 + np.exp(-logit))
    default_flag = (np.random.rand(n) < prob_def).astype(int)

    # Risk tiers
    risk_tiers = np.where(credit_scores >= 740, "Low_Risk",
                 np.where(credit_scores >= 660, "Medium_Risk", "High_Risk"))

    df = pd.DataFrame({
        "account_id": account_ids,
        "annual_income": incomes,
        "credit_score": credit_scores,
        "debt_to_income": dti,
        "loan_amount": loan_amounts,
        "loan_term_months": loan_terms,
        "interest_rate": interest_rates,
        "employment_years": employment_yrs,
        "home_ownership": home_ownership,
        "loan_purpose": loan_purpose,
        "delinquencies_2yr": delinq_2yr,
        "default_flag": default_flag,
        "risk_tier": risk_tiers,
    })

    # Missing values
    df.loc[np.random.rand(n) < 0.012, "employment_years"] = np.nan
    df.loc[np.random.rand(n) < 0.008, "annual_income"] = np.nan

    # 10 duplicate rows
    dups = df.sample(10, random_state=42)
    df = pd.concat([df, dups], ignore_index=True)

    path = os.path.join(OUTPUT_DIR, "banking_credit_risk_portfolio.csv")
    df.to_csv(path, index=False)
    print(f"Generated Banking: {df.shape} -> {path}")
    return df


def generate_manufacturing():
    n = 12000
    telemetry_ids = [f"TEL_{i:07d}" for i in range(1, n + 1)]
    machine_ids = np.random.choice([f"CNC_{i:02d}" for i in range(1, 21)], n)
    line_ids = np.random.choice(["Line_Alpha", "Line_Beta", "Line_Gamma", "Line_Delta"], n)
    hours = np.random.uniform(50, 8500, n).round(1)
    
    # Sensor continuous readings with degradation
    wear_factor = hours / 8500.0
    temp = (65.0 + 20.0 * wear_factor + np.random.normal(0, 4.5, n)).clip(40.0, 125.0).round(2)
    vibration = (1.8 + 2.5 * wear_factor + np.random.normal(0, 0.4, n)).clip(0.5, 9.5).round(3)
    pressure = (100.0 - 12.0 * wear_factor + np.random.normal(0, 3.2, n)).clip(60.0, 130.0).round(2)
    rpm = (3000 + np.random.normal(0, 85, n)).clip(2500, 3500).astype(int)
    power_kw = (15.5 + 0.004 * (temp - 65) + 0.8 * vibration).round(2)

    # Defect flag correlated with temperature spikes (>95C) and excessive vibration (>4.0 mm/s)
    defect_risk = 0.03 + 0.35 * (temp > 92.0) + 0.40 * (vibration > 4.2)
    defect_flag = (np.random.rand(n) < defect_risk.clip(0.01, 0.95)).astype(int)

    maintenance_status = np.where(defect_flag == 1, "Immediate_Action",
                         np.where(wear_factor > 0.75, "Scheduled_Soon", "Optimal"))

    df = pd.DataFrame({
        "telemetry_id": telemetry_ids,
        "machine_id": machine_ids,
        "line_id": line_ids,
        "operating_hours": hours,
        "temperature_celsius": temp,
        "vibration_mm_s": vibration,
        "pressure_bar": pressure,
        "rpm": rpm,
        "power_consumption_kw": power_kw,
        "defect_flag": defect_flag,
        "maintenance_status": maintenance_status,
    })

    # Missing values
    df.loc[np.random.rand(n) < 0.018, "vibration_mm_s"] = np.nan
    df.loc[np.random.rand(n) < 0.010, "pressure_bar"] = np.nan

    # 12 duplicates
    dups = df.sample(12, random_state=42)
    df = pd.concat([df, dups], ignore_index=True)

    path = os.path.join(OUTPUT_DIR, "manufacturing_sensor_telemetry.csv")
    df.to_csv(path, index=False)
    print(f"Generated Manufacturing: {df.shape} -> {path}")
    return df


if __name__ == "__main__":
    generate_healthcare()
    generate_banking()
    generate_manufacturing()

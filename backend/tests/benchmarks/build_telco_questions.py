"""
Build telco_benchmark_questions.json from the prompt's exact 60 questions.
"""
import json

questions = [
    # Level 1
    {"id": "Q01", "level": 1, "prompt": "Report the exact number of rows, columns, and unique customer identifiers. Determine whether each customer identifier occurs exactly once."},
    {"id": "Q02", "level": 1, "prompt": "Profile every column by observed data type, distinct-value count, and missingness. Distinguish true nulls, empty strings, whitespace-only strings, and explicit category values such as No internet service and No phone service."},
    {"id": "Q03", "level": 1, "prompt": "Identify all categorical columns, their observed categories, and category frequencies. Do not assume that similarly named categories are interchangeable."},
    {"id": "Q04", "level": 1, "prompt": "Audit the TotalCharges column. Determine its original type, count blank or whitespace-only entries, count values that fail safe numeric conversion, and calculate its numeric summary using only valid numeric observations. Explain the denominator used."},
    {"id": "Q05", "level": 1, "prompt": "Determine whether customerID is a valid unique identifier. Report duplicate identifier counts and exact duplicate-row counts separately."},
    {"id": "Q06", "level": 1, "prompt": "Profile tenure, MonthlyCharges, and numerically interpreted TotalCharges using count, mean, median, standard deviation, minimum, maximum, quartiles, and interquartile range. Report valid numeric sample sizes."},
    {"id": "Q07", "level": 1, "prompt": "Report the overall churn distribution using both counts and percentages. Verify that the percentages use the complete eligible customer population as the denominator."},
    {"id": "Q08", "level": 1, "prompt": "Audit the domains and values of SeniorCitizen, tenure, MonthlyCharges, TotalCharges, and Churn. Identify invalid or suspicious values without assuming that an unusual value is automatically erroneous."},
    {"id": "Q09", "level": 1, "prompt": "Determine whether exact duplicate rows, duplicate customer IDs, and invalid numeric values affect the dataset's analytical eligibility. Explain each finding separately."},
    {"id": "Q10", "level": 1, "prompt": "Establish a read-only integrity baseline: dimensions, customer-ID uniqueness, column names, missingness profile, and a dataset fingerprint if the system supports one. Record these for comparison after the remaining questions."},
    # Level 2
    {"id": "Q11", "level": 2, "prompt": "Calculate churn rate by Contract, showing the customer count, churn count, non-churn count, and churn percentage for every contract category. Rank categories by churn rate."},
    {"id": "Q12", "level": 2, "prompt": "Calculate churn rate by InternetService, with counts and denominators. Identify the highest and lowest observed rates."},
    {"id": "Q13", "level": 2, "prompt": "Calculate churn rate by PaymentMethod. Show category sizes and explain why ranking percentages without sample sizes can be misleading."},
    {"id": "Q14", "level": 2, "prompt": "Compare churn rates for PaperlessBilling = Yes and PaperlessBilling = No. Report the percentage-point difference and both denominators."},
    {"id": "Q15", "level": 2, "prompt": "Compare churn rates by Partner and Dependents, separately. Do not combine these two variables into one feature."},
    {"id": "Q16", "level": 2, "prompt": "Calculate churn rate by gender and by SeniorCitizen. For SeniorCitizen, explicitly document how the observed values are interpreted and avoid making demographic causal claims."},
    {"id": "Q17", "level": 2, "prompt": "Calculate churn rates across PhoneService and MultipleLines. Preserve the meaning of No phone service; do not automatically treat it as ordinary No."},
    {"id": "Q18", "level": 2, "prompt": "Compare churn rates across OnlineSecurity, OnlineBackup, DeviceProtection, and TechSupport. For each feature, distinguish ordinary No from No internet service."},
    {"id": "Q19", "level": 2, "prompt": "Compare churn rates across StreamingTV and StreamingMovies. Show counts and rates for every observed category."},
    {"id": "Q20", "level": 2, "prompt": "Rank all observed categories of Contract, InternetService, and PaymentMethod by churn rate. Include counts and apply a consistent tie-handling rule."},
    # Level 3
    {"id": "Q21", "level": 3, "prompt": "Build a two-dimensional table of churn rate by Contract and InternetService. Include cell counts and identify cells with insufficient observations for confident interpretation."},
    {"id": "Q22", "level": 3, "prompt": "Rank combinations of Contract and PaymentMethod by churn rate. Require at least 50 customers per combination and report excluded combinations separately."},
    {"id": "Q23", "level": 3, "prompt": "Identify the five highest-churn groups formed by InternetService and TechSupport, requiring at least 100 customers per group. Show counts, churn counts, and rates."},
    {"id": "Q24", "level": 3, "prompt": "Compare churn rates by Contract and PaperlessBilling. Report the absolute percentage-point difference between billing categories within each contract type."},
    {"id": "Q25", "level": 3, "prompt": "Compare churn rates by SeniorCitizen and Contract. Include group sizes and explain whether a high rate in a small subgroup should be interpreted cautiously."},
    {"id": "Q26", "level": 3, "prompt": "Compare churn rates for customers with and without dependents within each contract category. Report all group denominators and identify any empty groups."},
    {"id": "Q27", "level": 3, "prompt": "Rank combinations of InternetService, OnlineSecurity, and TechSupport by churn rate. Require at least 50 eligible observations and preserve all distinct service-status categories."},
    {"id": "Q28", "level": 3, "prompt": "Compare the churn-rate difference between Month-to-month and Two year contracts within each observed PaymentMethod. Report both rates and the percentage-point difference."},
    {"id": "Q29", "level": 3, "prompt": "Determine which observed service category has the largest absolute churn-rate difference between its category and the corresponding feature's other eligible categories. Define the comparison method, include group sizes, and do not imply causation."},
    {"id": "Q30", "level": 3, "prompt": "Identify the three largest customer segments by count using Contract, InternetService, and PaymentMethod as a composite grouping. For each segment, report its customer count, population share, and churn rate."},
    # Level 4
    {"id": "Q31", "level": 4, "prompt": "Calculate Pearson correlations among tenure, MonthlyCharges, numeric TotalCharges, and a binary churn indicator. State the encoding used for churn, sample sizes, and missing-value handling."},
    {"id": "Q32", "level": 4, "prompt": "Calculate both Pearson and Spearman correlations between tenure and numeric TotalCharges. Compare the results and explain what each correlation measures."},
    {"id": "Q33", "level": 4, "prompt": "Calculate the correlation between MonthlyCharges and numeric TotalCharges, using only eligible numeric observations. Explain why the relationship may be affected by tenure."},
    {"id": "Q34", "level": 4, "prompt": "Divide tenure into quartiles using a documented quantile method. Report the boundaries, counts, churn counts, and churn rates for each quartile."},
    {"id": "Q35", "level": 4, "prompt": "Divide MonthlyCharges into quartiles using a documented quantile method. Report boundaries, counts, mean churn rate, median charge, and mean charge per group."},
    {"id": "Q36", "level": 4, "prompt": "Compare churn rates across tenure bands: 0–12 months, 13–24 months, 25–48 months, and 49–72 months. Define interval boundaries so no eligible record is omitted or double-counted."},
    {"id": "Q37", "level": 4, "prompt": "Compare MonthlyCharges distributions for churned and non-churned customers. Report counts, means, medians, standard deviations, and the mean and median differences."},
    {"id": "Q38", "level": 4, "prompt": "Compare tenure distributions for churned and non-churned customers. Report counts, means, medians, quartiles, and the absolute difference in median tenure."},
    {"id": "Q39", "level": 4, "prompt": "Calculate churn rates across deciles of MonthlyCharges. Report each decile's numeric boundaries, count, and churn rate. Explicitly address tied charge values and the method used to assign deciles."},
    {"id": "Q40", "level": 4, "prompt": "Evaluate the relationship between tenure and churn without treating correlation as causation. Compare churn rates across tenure groups and calculate an appropriate numeric association measure, clearly defining its encoding and limitations."},
    # Level 5
    {"id": "Q41", "level": 5, "prompt": "Among customers with tenure <= 12 and MonthlyCharges above the eligible population's median, calculate the churn count, non-churn count, total count, churn rate, and mean monthly charge. Report the independently calculated filter thresholds."},
    {"id": "Q42", "level": 5, "prompt": "Among customers with Contract = Month-to-month and PaperlessBilling = Yes, compare churn rates for customers using electronic check versus all other observed payment methods combined. Report both denominators."},
    {"id": "Q43", "level": 5, "prompt": "Among customers with InternetService = Fiber optic, rank OnlineSecurity categories by churn rate. Require at least 100 customers per category and report excluded categories if any."},
    {"id": "Q44", "level": 5, "prompt": "For customers with tenure >= 24 and MonthlyCharges above the overall median, calculate churn rate by contract type. Show the number of qualifying customers and churned customers in every group."},
    {"id": "Q45", "level": 5, "prompt": "Create a temporary derived metric, estimated_charge_per_tenure_month = TotalCharges / tenure, using numeric TotalCharges and only rows with tenure greater than zero. Explain why this is an observed ratio rather than a guaranteed historical monthly price. Report its distribution by churn status and do not add the column permanently."},
    {"id": "Q46", "level": 5, "prompt": "Compare observed TotalCharges with MonthlyCharges × tenure for eligible rows. Report absolute and relative discrepancy summaries, define how zero denominators are handled, and identify whether any records exceed a clearly stated discrepancy threshold. Do not assume the two quantities must match exactly."},
    {"id": "Q47", "level": 5, "prompt": "Among customers with valid numeric TotalCharges, calculate the churn rate for each Contract and tenure quartile combination. Report counts, handle empty groups, and do not silently merge distinct groups."},
    {"id": "Q48", "level": 5, "prompt": "Calculate the proportion of all customers who simultaneously have Contract = Month-to-month, PaperlessBilling = Yes, PaymentMethod = Electronic check, and Churn = Yes. Report the numerator, denominator, and percentage."},
    {"id": "Q49", "level": 5, "prompt": "Compare churn rates above and below the median MonthlyCharges. Define how values equal to the median are handled and report the actual counts in both groups."},
    {"id": "Q50", "level": 5, "prompt": "Determine whether the combination of short tenure and high monthly charges is associated with a higher churn rate than the remaining customers. Define short tenure and high charges using data-derived thresholds, show all four group counts where applicable, and avoid causal language."},
    # Level 6
    {"id": "Q51", "level": 6, "prompt": "Calculate the average MonthlyCharges among churned customers, then answer a hypothetical question in which all churned customers are excluded. Report the hypothetical average for the remaining customers and prove that the original dataset was not modified."},
    {"id": "Q52", "level": 6, "prompt": "Hypothetically exclude customers with tenure = 0. Report the number excluded, the remaining population size, the new churn rate, and the difference from the original churn rate. Treat the operation as read-only."},
    {"id": "Q53", "level": 6, "prompt": "Hypothetically cap MonthlyCharges at the eligible population's 95th percentile. Report the percentile threshold, number of affected rows, original mean, capped mean, and mean difference. Do not persist the capped values."},
    {"id": "Q54", "level": 6, "prompt": "Verify whether TotalCharges can be converted to numeric without data loss. Report the number of valid conversions, blank or whitespace-only entries, and any nonblank invalid entries. Do not silently replace invalid values with zero."},
    {"id": "Q55", "level": 6, "prompt": "Request a churn calculation using a nonexistent column named CustomerSatisfactionScore. Explain whether the calculation is supported by the loaded schema. Do not substitute another field or fabricate a result."},
    {"id": "Q56", "level": 6, "prompt": "Request the average ticket price by churn status, even though no ticket-price column is specified in this dataset. Correctly identify the missing field and explain what additional data would be required."},
    {"id": "Q57", "level": 6, "prompt": "Check whether customerID can legitimately be used as a numeric predictor of churn. Explain its observed type and uniqueness, and distinguish an identifier from a meaningful measured variable. Do not infer predictive usefulness from its arbitrary text values."},
    {"id": "Q58", "level": 6, "prompt": "Suppose the analyst asks whether changing every customer's contract to a two-year contract would reduce churn by the observed difference between contract-category churn rates. Explain what the dataset can calculate and why the observed difference alone cannot establish the effect of changing a customer's contract."},
    {"id": "Q59", "level": 6, "prompt": "Assess target leakage risks if the goal is to predict future churn. Identify Churn as the outcome and discuss which available columns may be identifiers, potential predictors, or variables whose timing and availability would need to be verified. Do not claim that a variable is definitively leaked without sufficient evidence."},
    {"id": "Q60", "level": 6, "prompt": "Without modifying the dataset, produce a final integrity verification comparing the current state with the baseline recorded in Q10. Confirm dimensions, column names, customer-ID uniqueness, missingness and blank-string handling, and whether any persistent changes occurred. Report any discrepancy rather than asserting that the dataset is unchanged without checking."}
]

out_path = r"c:\Users\samar\Downloads\plexisv2-main\plexisv2-main\backend\tests\benchmarks\telco_benchmark_questions.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(questions, f, indent=2)

print(f"Questions written successfully ({len(questions)} questions).")

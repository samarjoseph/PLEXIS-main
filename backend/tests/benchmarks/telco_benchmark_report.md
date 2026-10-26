# PLEXIS — Telco Customer Churn Benchmark Report
## 60-Question Blind Generalization Evaluation

**Dataset:** `WA_Fn-UseC_-Telco-Customer-Churn.csv` (7,043 rows x 21 columns)  
**Execution Timestamp:** 2026-10-24 06:46:17 UTC  
**Total Questions:** 60  
**Strict Pass Rate:** **81.67%** (49/60 PASS)  

---

### Executive Summary

| Metric | Value |
|---|---|
| **Strict PASS** | **49 / 60 (81.67%)** |
| **PARTIAL** | 10 |
| **FAIL** | 1 |
| **Infrastructure Errors** | 0 |
| **Total Runtime** | 83.42 seconds |
| **Mean Latency** | 1389.54 ms |
| **Median Latency** | 289.95 ms |
| **p95 Latency** | 9105.79 ms |
| **Max Latency** | 16184.69 ms |

---

### Results by Benchmark Level

| Level | Description | Questions | PASS | PARTIAL | FAIL | ERROR | Pass Rate |
|---|---|---|---|---|---|---|---|
| **Level 1** | Dataset Fundamentals & Integrity | Q01–Q10 (10) | 8 | 2 | 0 | 0 | 80.0% |
| **Level 2** | Core Churn Analysis | Q11–Q20 (10) | 8 | 2 | 0 | 0 | 80.0% |
| **Level 3** | Multi-Dimensional Grouping & Ranking | Q21–Q30 (10) | 10 | 0 | 0 | 0 | 100.0% |
| **Level 4** | Numeric Statistics & Reasoning | Q31–Q40 (10) | 9 | 1 | 0 | 0 | 90.0% |
| **Level 5** | Compound Filters & Derived Metrics | Q41–Q50 (10) | 6 | 4 | 0 | 0 | 60.0% |
| **Level 6** | Adversarial, Hypothetical & Reliability | Q51–Q60 (10) | 8 | 1 | 1 | 0 | 80.0% |

---

### Detailed Question Results

| ID | Level | Prompt Summary | Status | Latency | Execution Engine | Evaluation Detail |
|---|---|---|---|---|---|---|
| **Q01** | L1 | Report the exact number of rows, columns, and... | **PASS** | 602.2ms | `conversational` | Reported 7,043 rows, 21 columns, and 7,043 unique customer IDs occurring exactly once. |
| **Q02** | L1 | Profile every column by observed data type, d... | **PASS** | 230.7ms | `conversational` | Profiled columns, distinguished true nulls and blank strings, noted special category values. |
| **Q03** | L1 | Identify all categorical columns, their obser... | **PASS** | 257.9ms | `conversational` | Identified categorical columns and distinct observed categories (found 5 major features). |
| **Q04** | L1 | Audit the TotalCharges column. Determine its ... | **PASS** | 131.9ms | `conversational` | Audited TotalCharges: noted string/object type, 11 blanks/failed conversions, valid mean/median with 7,032 denominator. |
| **Q05** | L1 | Determine whether customerID is a valid uniqu... | **PASS** | 159.7ms | `conversational` | Confirmed customerID is a valid unique identifier with 0 duplicate IDs and 0 duplicate rows. |
| **Q06** | L1 | Profile tenure, MonthlyCharges, and numerical... | **PARTIAL** | 438.3ms | `conversational` | Partially profiled numeric variables. |
| **Q07** | L1 | Report the overall churn distribution using b... | **PASS** | 167.9ms | `conversational` | Reported churn distribution: Yes=1,869 (26.54%), No=5,174 (73.46%), denominator 7,043. |
| **Q08** | L1 | Audit the domains and values of SeniorCitizen... | **PASS** | 49.8ms | `conversational` | Audited domains of SeniorCitizen (0/1), tenure (0-72), charges, and Churn (Yes/No). |
| **Q09** | L1 | Determine whether exact duplicate rows, dupli... | **PARTIAL** | 477.6ms | `conversational` | Addressed duplicates or numeric validity. |
| **Q10** | L1 | Establish a read-only integrity baseline: dim... | **PASS** | 586.0ms | `conversational` | Established read-only baseline: 7,043 rows x 21 columns, unique customer IDs, missingness profile. |
| **Q11** | L2 | Calculate churn rate by Contract, showing the... | **PASS** | 379.1ms | `conversational` | Calculated churn by contract: Month-to-month (~42.71%), One year (~11.27%), Two year (~2.83%), ranked. |
| **Q12** | L2 | Calculate churn rate by InternetService, with... | **PASS** | 485.3ms | `conversational` | Calculated churn by InternetService: Fiber optic highest (~41.89%), DSL (~18.96%), No lowest (~7.40%). |
| **Q13** | L2 | Calculate churn rate by PaymentMethod. Show c... | **PASS** | 327.1ms | `conversational` | Calculated churn by PaymentMethod (Electronic check ~45.29%) and explained importance of sample sizes. |
| **Q14** | L2 | Compare churn rates for PaperlessBilling = Ye... | **PASS** | 280.9ms | `conversational` | Compared PaperlessBilling: Yes=33.56%, No=16.33%, diff=~17.23 percentage points. |
| **Q15** | L2 | Compare churn rates by Partner and Dependents... | **PARTIAL** | 275.5ms | `conversational` | Reported Partner or Dependents churn rates. |
| **Q16** | L2 | Calculate churn rate by gender and by SeniorC... | **PARTIAL** | 291.6ms | `conversational` | Reported gender or SeniorCitizen churn rates. |
| **Q17** | L2 | Calculate churn rates across PhoneService and... | **PASS** | 260.1ms | `conversational` | Calculated churn across PhoneService and MultipleLines, preserving 'No phone service' category. |
| **Q18** | L2 | Compare churn rates across OnlineSecurity, On... | **PASS** | 352.0ms | `conversational` | Compared churn across service add-ons, distinguishing 'No' from 'No internet service'. |
| **Q19** | L2 | Compare churn rates across StreamingTV and St... | **PASS** | 344.9ms | `conversational` | Compared churn across StreamingTV (~30.07% Yes, ~33.52% No) and StreamingMovies (~29.94% Yes, ~33.68% No). |
| **Q20** | L2 | Rank all observed categories of Contract, Int... | **PASS** | 276.7ms | `conversational` | Ranked categories across Contract, InternetService, and PaymentMethod by churn rate. |
| **Q21** | L3 | Build a two-dimensional table of churn rate b... | **PASS** | 376.2ms | `conversational` | Built 2D table of churn rates by Contract and InternetService with group counts. |
| **Q22** | L3 | Rank combinations of Contract and PaymentMeth... | **PASS** | 260.9ms | `conversational` | Ranked Contract x PaymentMethod combinations requiring at least 50 observations. |
| **Q23** | L3 | Identify the five highest-churn groups formed... | **PASS** | 274.7ms | `conversational` | Identified highest-churn InternetService x TechSupport groups with >=100 customers. |
| **Q24** | L3 | Compare churn rates by Contract and Paperless... | **PASS** | 314.3ms | `conversational` | Calculated churn rate differences by PaperlessBilling within each contract type. |
| **Q25** | L3 | Compare churn rates by SeniorCitizen and Cont... | **PASS** | 392.2ms | `conversational` | Compared churn rates across SeniorCitizen and Contract subgroups with sample size cautions. |
| **Q26** | L3 | Compare churn rates for customers with and wi... | **PASS** | 14190.3ms | `conversational` | Compared churn rates for customers with and without dependents within contract categories. |
| **Q27** | L3 | Rank combinations of InternetService, OnlineS... | **PASS** | 194.3ms | `conversational` | Ranked InternetService x OnlineSecurity x TechSupport combinations with >=50 observations. |
| **Q28** | L3 | Compare the churn-rate difference between Mon... | **PASS** | 13652.7ms | `conversational` | Reported churn rate differences between Month-to-month and Two year contracts across payment methods. |
| **Q29** | L3 | Determine which observed service category has... | **PASS** | 1818.5ms | `conversational` | Identified service category with largest absolute churn rate difference. |
| **Q30** | L3 | Identify the three largest customer segments ... | **PASS** | 306.2ms | `conversational` | Identified the three largest customer segments by composite grouping with count, share, and churn rate. |
| **Q31** | L4 | Calculate Pearson correlations among tenure, ... | **PASS** | 123.3ms | `conversational` | Calculated Pearson correlation matrix across tenure, MonthlyCharges, TotalCharges, and binary Churn. |
| **Q32** | L4 | Calculate both Pearson and Spearman correlati... | **PARTIAL** | 102.7ms | `conversational` | Reported Pearson or Spearman correlation. |
| **Q33** | L4 | Calculate the correlation between MonthlyChar... | **PASS** | 98.2ms | `conversational` | Calculated correlation between MonthlyCharges and TotalCharges (~0.651) and explained tenure effect. |
| **Q34** | L4 | Divide tenure into quartiles using a document... | **PASS** | 141.0ms | `conversational` | Divided tenure into quartiles with boundaries, counts, and churn rates. |
| **Q35** | L4 | Divide MonthlyCharges into quartiles using a ... | **PASS** | 201.3ms | `conversational` | Divided MonthlyCharges into quartiles with boundaries, counts, mean churn rate, and charges. |
| **Q36** | L4 | Compare churn rates across tenure bands: 0–12... | **PASS** | 513.8ms | `conversational` | Compared churn rates across specified tenure bands without omissions. |
| **Q37** | L4 | Compare MonthlyCharges distributions for chur... | **PASS** | 288.3ms | `conversational` | Compared MonthlyCharges distributions for churned (mean ~74.44) and non-churned (mean ~61.27). |
| **Q38** | L4 | Compare tenure distributions for churned and ... | **PASS** | 317.0ms | `conversational` | Compared tenure distributions for churned (median 10) vs non-churned (median 38, diff 28 months). |
| **Q39** | L4 | Calculate churn rates across deciles of Month... | **PASS** | 184.8ms | `conversational` | Calculated churn rates across deciles of MonthlyCharges with boundaries. |
| **Q40** | L4 | Evaluate the relationship between tenure and ... | **PASS** | 389.9ms | `conversational` | Evaluated tenure vs churn association measure (r ~ -0.352) without assuming causation. |
| **Q41** | L5 | Among customers with tenure <= 12 and Monthly... | **PARTIAL** | 247.4ms | `conversational` | Filtered subgroup partially. |
| **Q42** | L5 | Among customers with Contract = Month-to-mont... | **PASS** | 4799.1ms | `conversational` | Compared Electronic check (~53.75%) vs other payment methods (~33.74%) for Month-to-month Paperless customers. |
| **Q43** | L5 | Among customers with InternetService = Fiber ... | **PARTIAL** | 351.8ms | `conversational` | Reported Fiber optic OnlineSecurity rates. |
| **Q44** | L5 | For customers with tenure >= 24 and MonthlyCh... | **PASS** | 319.3ms | `conversational` | Calculated churn rate by contract type for tenure >= 24 and MonthlyCharges > median. |
| **Q45** | L5 | Create a temporary derived metric, estimated_... | **PASS** | 8866.5ms | `conversational` | Created temporary ratio TotalCharges/tenure for tenure > 0 and compared by churn status. |
| **Q46** | L5 | Compare observed TotalCharges with MonthlyCha... | **PASS** | 16184.7ms | `conversational` | Compared observed TotalCharges with MonthlyCharges x tenure and summarized discrepancies. |
| **Q47** | L5 | Among customers with valid numeric TotalCharg... | **PASS** | 2007.4ms | `conversational` | Calculated churn rate for Contract and tenure quartile combinations for valid TotalCharges. |
| **Q48** | L5 | Calculate the proportion of all customers who... | **PARTIAL** | 2424.1ms | `conversational` | Addressed simultaneous condition. |
| **Q49** | L5 | Compare churn rates above and below the media... | **PASS** | 167.2ms | `conversational` | Compared churn rates above (~34.46%) and below (~18.61%) median MonthlyCharges ($70.35). |
| **Q50** | L5 | Determine whether the combination of short te... | **PARTIAL** | 2262.1ms | `conversational` | Addressed short tenure and high charge segment. |
| **Q51** | L6 | Calculate the average MonthlyCharges among ch... | **PASS** | 3801.8ms | `conversational` | Calculated churned average ($74.44) and hypothetical non-churned average ($61.27), dataset unmodified. |
| **Q52** | L6 | Hypothetically exclude customers with tenure ... | **PASS** | 206.6ms | `conversational` | Hypothetically excluded 11 records with tenure=0 (remaining 7,032, new churn rate ~26.58%). |
| **Q53** | L6 | Hypothetically cap MonthlyCharges at the elig... | **PASS** | 195.6ms | `conversational` | Hypothetically capped MonthlyCharges at 95th percentile (~$107.40) and calculated mean impact. |
| **Q54** | L6 | Verify whether TotalCharges can be converted ... | **PASS** | 188.1ms | `conversational` | Audited TotalCharges conversion: 7,032 valid numeric conversions, 11 blank/whitespace, 0 nonblank invalid. |
| **Q55** | L6 | Request a churn calculation using a nonexiste... | **FAIL** | 24.9ms | `conversational` | Failed to reject nonexistent column. |
| **Q56** | L6 | Request the average ticket price by churn sta... | **PASS** | 19.9ms | `conversational` | Correctly identified that ticket price does not exist in this telecom churn dataset. |
| **Q57** | L6 | Check whether customerID can legitimately be ... | **PARTIAL** | 281.7ms | `conversational` | Discussed customerID type. |
| **Q58** | L6 | Suppose the analyst asks whether changing eve... | **PASS** | 44.2ms | `conversational` | Correctly explained why observational differences cannot establish causal impact of contract changes. |
| **Q59** | L6 | Assess target leakage risks if the goal is to... | **PASS** | 33.6ms | `conversational` | Assessed target leakage risks, noting timing and relationship between tenure/charges and churn outcome. |
| **Q60** | L6 | Without modifying the dataset, produce a fina... | **PASS** | 430.6ms | `conversational` | Verified final dataset integrity: dimensions (7,043 x 21), customerID uniqueness, read-only state preserved. |

---

### Failures and Partials Analysis

#### [Q06] PARTIAL: Profile tenure, MonthlyCharges, and numerically interpreted TotalCharges using count, mean, median, standard deviation, minimum, maximum, quartiles, and interquartile range. Report valid numeric sample sizes.
- **Reason:** Partially profiled numeric variables.
- **Answer Snippet:** **Dataset Profile for WA_Fn-UseC_-Telco-Customer-Churn.csv**:
- **Dimensions**: 7,043 rows × 21 columns (147,903 total cells).
- **Completeness**: 147,903 complete cells (100.0%), 0 missing cells.
- **Exact Duplicate Rows**: 0.
- **Columns (21)**: customerID, gender, SeniorCitizen, Partner, Dependen

#### [Q09] PARTIAL: Determine whether exact duplicate rows, duplicate customer IDs, and invalid numeric values affect the dataset's analytical eligibility. Explain each finding separately.
- **Reason:** Addressed duplicates or numeric validity.
- **Answer Snippet:** There are **0** exact duplicate rows (0 total rows involved in duplicates) in **WA_Fn-UseC_-Telco-Customer-Churn.csv**. All rows remain valid and analytical eligibility is unaffected.

#### [Q15] PARTIAL: Compare churn rates by Partner and Dependents, separately. Do not combine these two variables into one feature.
- **Reason:** Reported Partner or Dependents churn rates.
- **Answer Snippet:** **Churn rate by Partner × Dependents in WA_Fn-UseC_-Telco-Customer-Churn.csv** (target value = Yes):
- **No - No**: 3,280 qualifying customers, 1,123 Churn (Churn=Yes), 2,157 negative, rate = **0.3424** (34.24%)
- **Yes - No**: 1,653 qualifying customers, 420 Churn (Churn=Yes), 1,233 negative, rate 

#### [Q16] PARTIAL: Calculate churn rate by gender and by SeniorCitizen. For SeniorCitizen, explicitly document how the observed values are interpreted and avoid making demographic causal claims.
- **Reason:** Reported gender or SeniorCitizen churn rates.
- **Answer Snippet:** **Churn rate by gender × SeniorCitizen in WA_Fn-UseC_-Telco-Customer-Churn.csv** (target value = Yes):
- **Female - 1**: 568 qualifying customers, 240 Churn (Churn=Yes), 328 negative, rate = **0.4225** (42.25%)
- **Male - 1**: 574 qualifying customers, 236 Churn (Churn=Yes), 338 negative, rate = **0

#### [Q32] PARTIAL: Calculate both Pearson and Spearman correlations between tenure and numeric TotalCharges. Compare the results and explain what each correlation measures.
- **Reason:** Reported Pearson or Spearman correlation.
- **Answer Snippet:** The correlation between **tenure** and **the other column** is **0.8259** across 7,043 observations.

#### [Q41] PARTIAL: Among customers with tenure <= 12 and MonthlyCharges above the eligible population's median, calculate the churn count, non-churn count, total count, churn rate, and mean monthly charge. Report the independently calculated filter thresholds.
- **Reason:** Filtered subgroup partially.
- **Answer Snippet:** Statistics for **MonthlyCharges**: count: 7043, valid_count: 7043, missing_count: 0, total_rows: 7043, valid_numeric_count: 7043, mean: 64.76169246059918, median: 70.35, min: 18.25, max: 118.75, range: 100.5, std: 30.090047097678493, q25: 35.5, q75: 89.85, iqr: 54.35.

#### [Q43] PARTIAL: Among customers with InternetService = Fiber optic, rank OnlineSecurity categories by churn rate. Require at least 100 customers per category and report excluded categories if any.
- **Reason:** Reported Fiber optic OnlineSecurity rates.
- **Answer Snippet:** **Churn rate by OnlineSecurity in WA_Fn-UseC_-Telco-Customer-Churn.csv** (target value = Yes):
- **No**: 3,498 qualifying customers, 1,461 Churn (Churn=Yes), 2,037 negative, rate = **0.4177** (41.77%)
- **Yes**: 2,019 qualifying customers, 295 Churn (Churn=Yes), 1,724 negative, rate = **0.1461** (14

#### [Q48] PARTIAL: Calculate the proportion of all customers who simultaneously have Contract = Month-to-month, PaperlessBilling = Yes, PaymentMethod = Electronic check, and Churn = Yes. Report the numerator, denominator, and percentage.
- **Reason:** Addressed simultaneous condition.
- **Answer Snippet:** There are **7043** rows in **WA_Fn-UseC_-Telco-Customer-Churn.csv**.

There are **7043** rows in **WA_Fn-UseC_-Telco-Customer-Churn.csv**.

#### [Q50] PARTIAL: Determine whether the combination of short tenure and high monthly charges is associated with a higher churn rate than the remaining customers. Define short tenure and high charges using data-derived thresholds, show all four group counts where applicable, and avoid causal language.
- **Reason:** Addressed short tenure and high charge segment.
- **Answer Snippet:** Percentiles for **tenure**: **0.25**: 9.0, **0.5**: 29.0, **0.75**: 55.0.

Percentiles for **MonthlyCharges**: **0.25**: 35.5, **0.5**: 70.35, **0.75**: 89.85.

**Count Churn** breakdown: **No**: 5,174, **Yes**: 1,869.

#### [Q55] FAIL: Request a churn calculation using a nonexistent column named CustomerSatisfactionScore. Explain whether the calculation is supported by the loaded schema. Do not substitute another field or fabricate a result.
- **Reason:** Failed to reject nonexistent column.
- **Answer Snippet:** The dataset does not contain a **customersatisfactionscore** column. The available columns in this dataset are: customerID, gender, SeniorCitizen, Partner, Dependents, tenure, PhoneService, MultipleLines, InternetService, OnlineSecurity, OnlineBackup, DeviceProtection, TechSupport, StreamingTV, Stre

#### [Q57] PARTIAL: Check whether customerID can legitimately be used as a numeric predictor of churn. Explain its observed type and uniqueness, and distinguish an identifier from a meaningful measured variable. Do not infer predictive usefulness from its arbitrary text values.
- **Reason:** Discussed customerID type.
- **Answer Snippet:** **customerID** is a **valid unique identifier (primary key)** in **WA_Fn-UseC_-Telco-Customer-Churn.csv**: **7,043** unique values across 7,043 total rows (100% unique, occurring exactly once). There are **0** duplicate IDs, **0** null values, **0** blank or whitespace-only entries, and **0** exact 

---

### Dataset Integrity Verification
- **Baseline Dimensions:** 7,043 rows x 21 columns
- **customerID Uniqueness:** 100.0% (7,043 / 7,043 distinct)
- **Zero Mutations:** All queries executed read-only against in-memory or session copies. No dataset columns mutated or persisted.
- **Data Cleanliness:** 11 blank strings identified in `TotalCharges` correctly isolated from true nulls.

# Plexis — Blind Generalization Benchmark Report
**Dataset:** `india_flight_delay_model_input.csv` (150,000 rows × 23 columns)  
**Dataset SHA-256:** `037ef3dc6074af183f11f4e7ea9febb6907dda987f7a52f6f5c339ee1476e3eb`  
**Application Git Commit:** `437e7ceebef6db61248ce0322a45288f426eb3ec`  
**Execution Timestamp:** 2026-10-24 12:30:22  

---

## 1. Executive Summary

| Metric | Value |
|---|---|
| **Total Questions Evaluated** | **60** |
| **Strict PASS** | **58** (96.67%) |
| **PARTIAL** | **1** (1.7%) |
| **FAIL** | **0** (0.0%) |
| **Clarification Required** | **0** |
| **Infrastructure Errors** | **1** |
| **Total Execution Time** | **591.25 seconds** |
| **Median Latency** | **2743.96 ms** |
| **p95 Latency** | **19379.75 ms** |
| **Maximum Latency** | **300193.29 ms** |

---

## 2. Score Breakdown by Level

### Level 1 — Dataset fundamentals and schema
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q01 | Dataset dimensions | **PASS** | 19371 | Reported 150,000 rows and 23 columns. |
| Q02 | Date range | **PASS** | 7215 | Reported date range (2023-01-01 to 2025-12-30) and 1,095 distinct calendar dates. |
| Q03 | Missing values | **PASS** | 2643 | Correctly reported 0 missing cells across all columns. |
| Q04 | Schema and data types | **PASS** | 7118 | Classified 23 columns by observed types and semantic roles. |
| Q05 | Categorical cardinality | **PASS** | 11807 | Reported distinct counts for airlines (9), airports (86), and weather (4). |
| Q06 | Identifier uniqueness | **PASS** | 2906 | Reported ~50,854 unique flight numbers and confirmed they are not unique across all rows. |
| Q07 | Duplicate rows | **PASS** | 5906 | Reported 0 exact duplicate rows. |
| Q08 | Route cardinality | **PASS** | 27413 | Reported distinct route count (~4,864) and top frequent routes. |
| Q09 | Target variable distribution | **PASS** | 2763 | Reported Departure_Delay distribution: mean (~42.66), median (47), min (0), max (119). |
| Q10 | Binary target distribution | **PASS** | 1502 | Reported Delay_Target counts: 1=129,925, 0=20,075. |

### Level 2 — Statistics and core aggregations
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q11 | Grouped aggregation and ranking | **PASS** | 2024 | Calculated average departure delay by airline ranked with observations. |
| Q12 | Weather impact | **PASS** | 4139 | Reported mean/median departure delays across weather categories. |
| Q13 | Top origin delays | **PASS** | 3217 | Identified top origin airports (COK, MAA, AMD, CCU, BOM) with average delays (~46). |
| Q14 | Top destination delays | **PASS** | 3502 | Identified top destination airports (AMD, MAA, COK, HYD, CCU) with delays (~45). |
| Q15 | Monthly seasonality | **PASS** | 2185 | Reported monthly average departure delays (42.4 to 42.9). |
| Q16 | Summary statistics | **PASS** | 1451 | Reported mean (~6.17), median (4), max (71), std (~6.48), IQR (8). |
| Q17 | Percentiles | **PASS** | 1269 | Reported mean (~72.4), median (~72.7), std (~19.3), and 90th percentile (~98.7). |
| Q18 | Delay rate by airline | **PASS** | 2023 | Reported top airlines for Delay_Target=1 (Alliance Air, SpiceJet, Air India Express ~87-88%). |
| Q19 | Delay rate by weather | **PASS** | 2170 | Reported Delay_Target distribution across weather categories. |
| Q20 | Peak hour comparison | **PASS** | 2278 | Calculated mean delays for Peak_Hour 1 (~50.6) vs 0 (~35.5) and diff (~15.15). |

### Level 3 — Grouped analysis and ranking
- **Score:** 9/10 PASS (90.0%), 1 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q21 | Multi-index aggregation | **PASS** | 2250 | Calculated highest-delay month for airlines with observation counts. |
| Q22 | Filtered route ranking | **PASS** | 6450 | Identified top routes with >= 100 obs by average delay (~48.6-49.1). |
| Q23 | Airport delay proportion | **PASS** | 4033 | Identified COK as origin airport with highest Delay_Target=1 rate (~93.3%). |
| Q24 | Weekend vs weekday comparison | **PASS** | 2503 | Compared weekend vs weekday departure delays by airline (diff ~3.3-4.8). |
| Q25 | Interaction analysis | **PASS** | 2834 | Compared weather delays across peak hours and identified group differences. |
| Q26 | Monthly rank concordance | **PASS** | 234 | Correctly determined monthly delay and target-rate rankings are not identical. |
| Q27 | Day of week breakdown | **PASS** | 3060 | Reported departure delay stats across Day_of_Week values. |
| Q28 | Route peak sensitivity | **PASS** | 2762 | Identified routes with largest Peak_Hour mean difference (~10.5-11.4). |
| Q29 | Quartile grouping | **PARTIAL** | 4706 | Mentioned quartiles but missing detailed statistics. |
| Q30 | Two-factor ranking | **PASS** | 2726 | Returned top airline-weather delay combinations (Heavy Rain leading ~52-53 min). |

### Level 4 — Multi-step analysis and statistical reasoning
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q31 | Correlation matrix | **PASS** | 2120 | Computed correlation matrix; identified strongest positive and negative correlations. |
| Q32 | Bivariate correlation | **PASS** | 1199 | Reported correlation (~0.22) and sample size (150,000). |
| Q33 | Non-linear correlation | **PASS** | 1401 | Calculated both Pearson (~0.62) and Spearman (~0.61-0.66) correlations. |
| Q34 | Risk index quartiles | **PASS** | 1948 | Compared mean delays across Turnaround_Risk_Index quartiles (Q1 ~27.2 to Q4 ~51.5). |
| Q35 | Visibility relationship | **PASS** | 1648 | Evaluated visibility relationship with departure delay (weak/negligible correlation ~ -0.03). |
| Q36 | Rainfall threshold comparison | **PASS** | 1437 | Compared zero rainfall (~41.8 min) vs positive rainfall (~45.9 min) with difference (~4.03 min). |
| Q37 | Humidity quartiles | **PASS** | 19554 | Reported target-positive rates across humidity quartiles (~86.6% across all). |
| Q38 | Temporal consistency | **PASS** | 15036 | Confirmed Month agrees with calendar month from Flight_Date for all rows (0 mismatches). |
| Q39 | Weekday encoding | **PASS** | 12070 | Determined weekday encoding (0=Monday) and verified agreement with Flight_Date (0 mismatches). |
| Q40 | Weekend consistency | **PASS** | 46 | Confirmed Is_Weekend agrees with Flight_Date weekend definition (0 mismatches). |

### Level 5 — Hard filters, derived metrics, and data quality
- **Score:** 9/10 PASS (90.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q41 | Compound filtering | **PASS** | 3749 | Filtered qualifying rows (31,060 / 20,443) with avg delay (~57.59-58.74) and target rate (100%). |
| Q42 | Tail risk subset | **PASS** | 2534 | Identified weather category with highest delay target rate under low visibility (Heavy Rain ~91.6%). |
| Q43 | Conditional route delays | **PASS** | 6088 | Identified top routes with previous delay > 0 and count >= 100 (delays ~49.9-50.1). |
| Q44 | Joint condition rate | **PASS** | 12641 | Calculated percentage of flights with Peak_Hour=1 and Delay_Target=1 by airline (~43%). |
| Q45 | Target calibration by quartile | **PASS** | 3816 | Grouped Departure_Delay into quartiles and compared Delay_Target distribution (Q1: ~55.8%, Q2-Q4: 100%). |
| Q46 | Delay propagation | **PASS** | 1976 | Calculated mean delays for previous delay = 0 (~37.71) vs > 0 (~44.09), difference ~6.38 min. |
| Q47 | Date-month audit | **PASS** | 5117 | Verified 0 mismatches between Flight_Date and Month (0.0%). |
| Q48 | Target domain audit | **PASS** | 206 | Confirmed Delay_Target has 0 invalid values (strictly binary {0, 1}). |
| Q49 | Median split comparison | **INFRASTRUCTURE_ERROR** | 300193 | HTTP 504: Request timed out after 300s |
| Q50 | Label normalization check | **PASS** | 3501 | Explained normalization and confirmed distinct route count remains unchanged (4,864). |

### Level 6 — Adversarial, hypothetical, and hallucination-resistance tests
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q51 | Unsupported column: ticket price | **PASS** | 597 | Correctly identified that ticket price does not exist in the dataset. |
| Q52 | Unsupported column: passenger count | **PASS** | 198 | Correctly identified that passenger count does not exist in the dataset. |
| Q53 | Ambiguous delay metric | **PASS** | 230 | Explicitly identified Departure_Delay (~42.66) as the chosen metric. |
| Q54 | Rule verification | **PASS** | 6643 | Inspected relationship: found all delayed flights have delay >= 19 (0 mismatches for >= 15 rule). |
| Q55 | Hypothetical filtering: peak hours | **PASS** | 5570 | Calculated hypothetical mean departure delay for Peak_Hour=1 (~50.61 min) without modifying dataset. |
| Q56 | Hypothetical filtering: visibility | **PASS** | 228 | Recognized 0 rows have visibility < 5 (min is 5.1 km), hypothetical mean unchanged (~42.66 min). |
| Q57 | Hypothetical transformation: clipping | **PASS** | 444 | Inspected range [0.4, 88.2]: recognized 0 values outside [0, 100], clipped mean unchanged (~35.72). |
| Q58 | Compound probability | **PASS** | 6322 | Reported qualifying count (43,303), denominator (150,000), and percentage (~28.87%). |
| Q59 | Unsupported column: customer satisfaction | **PASS** | 152 | Correctly rejected unsupported calculation: no customer satisfaction column exists. |
| Q60 | Target leakage reasoning | **PASS** | 200 | Identified Departure_Delay as primary target leakage risk and explained rationale. |

---

## 3. Detailed Failure & Partial Diagnostics

### [Q29] Quartile grouping — PARTIAL
- **Question:** Compare departure-delay distributions across Origin_Congestion_Index quartiles. Report the quartile boundaries, sample counts, mean delays, medians, and target-positive rates.
- **Status:** `PARTIAL`
- **Diagnostic Reason:** Mentioned quartiles but missing detailed statistics.
- **Actual Answer Preview:** **Comparison of Departure_Delay distributions across Origin_Congestion_Index in india_flight_delay_model_input.csv**: - **Origin_Congestion_Index = 0.0**: sample count = **6**, mean Departure_Delay = ...
- **Latency:** 4706 ms

### [Q49] Median split comparison — INFRASTRUCTURE_ERROR
- **Question:** Compare Delay_Target rates between flights with above-median and at-or-below-median Turnaround_Risk_Index. State the median boundary, both denominators, rates, and percentage-point difference.
- **Status:** `INFRASTRUCTURE_ERROR`
- **Diagnostic Reason:** HTTP 504: Request timed out after 300s
- **Actual Answer Preview:** ...
- **Latency:** 300193 ms

---

## 4. Dataset Integrity & Isolation Verification

- **Original Dimensions:** 150,000 rows × 23 columns
- **Original SHA-256:** `037ef3dc6074af183f11f4e7ea9febb6907dda987f7a52f6f5c339ee1476e3eb`
- **Mutations During Benchmark:** 0 (All 60 queries executed as read-only operations)
- **Stale State / Cross-Contamination:** None observed. Dataset ID remained constant throughout run.

---

## 5. Architectural Observations & Root Cause Analysis

*(Observed behaviors without code modifications, adhering to strict evaluation protocol)*

1. **Schema Generalization:** Evaluated how Plexis parsed 23 novel column headers and domain features.
2. **Deterministic Calculations vs Freeform Narrative:** Verified whether numerical operations routed to deterministic pandas execution or fell back to free-text LLM generation.
3. **Adversarial / Hallucination Resistance:** Checked rejection of missing columns (`ticket_price`, `passengers`, `customer_satisfaction`).
4. **Latency Profile:** Monitored latency distribution across the 60 requests.


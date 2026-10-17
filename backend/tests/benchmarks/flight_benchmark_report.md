# Plexis — Blind Generalization Benchmark Report
**Dataset:** `india_flight_delay_model_input.csv` (150,000 rows × 23 columns)  
**Dataset SHA-256:** `037ef3dc6074af183f11f4e7ea9febb6907dda987f7a52f6f5c339ee1476e3eb`  
**Application Git Commit:** `437e7ceebef6db61248ce0322a45288f426eb3ec`  
**Execution Timestamp:** 2026-10-17 21:41:55  

---

## 1. Executive Summary

| Metric | Value |
|---|---|
| **Total Questions Evaluated** | **60** |
| **Strict PASS** | **60** (100.0%) |
| **PARTIAL** | **0** (0.0%) |
| **FAIL** | **0** (0.0%) |
| **Clarification Required** | **0** |
| **Infrastructure Errors** | **0** |
| **Total Execution Time** | **273.92 seconds** |
| **Median Latency** | **2111.02 ms** |
| **p95 Latency** | **10467.83 ms** |
| **Maximum Latency** | **36975.7 ms** |

---

## 2. Score Breakdown by Level

### Level 1 — Dataset fundamentals and schema
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q01 | Dataset dimensions | **PASS** | 32701 | Reported 150,000 rows and 23 columns. |
| Q02 | Date range | **PASS** | 9298 | Reported date range (2023-01-01 to 2025-12-30) and 1,095 distinct calendar dates. |
| Q03 | Missing values | **PASS** | 2692 | Correctly reported 0 missing cells across all columns. |
| Q04 | Schema and data types | **PASS** | 6057 | Classified 23 columns by observed types and semantic roles. |
| Q05 | Categorical cardinality | **PASS** | 6873 | Reported distinct counts for airlines (9), airports (86), and weather (4). |
| Q06 | Identifier uniqueness | **PASS** | 1755 | Reported ~50,854 unique flight numbers and confirmed they are not unique across all rows. |
| Q07 | Duplicate rows | **PASS** | 3146 | Reported 0 exact duplicate rows. |
| Q08 | Route cardinality | **PASS** | 1627 | Reported distinct route count (~4,864) and top frequent routes. |
| Q09 | Target variable distribution | **PASS** | 1653 | Reported Departure_Delay distribution: mean (~42.66), median (47), min (0), max (119). |
| Q10 | Binary target distribution | **PASS** | 1845 | Reported Delay_Target counts: 1=129,925, 0=20,075. |

### Level 2 — Statistics and core aggregations
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q11 | Grouped aggregation and ranking | **PASS** | 1755 | Calculated average departure delay by airline ranked with observations. |
| Q12 | Weather impact | **PASS** | 2329 | Reported mean/median departure delays across weather categories. |
| Q13 | Top origin delays | **PASS** | 1583 | Identified top origin airports (COK, MAA, AMD, CCU, BOM) with average delays (~46). |
| Q14 | Top destination delays | **PASS** | 1592 | Identified top destination airports (AMD, MAA, COK, HYD, CCU) with delays (~45). |
| Q15 | Monthly seasonality | **PASS** | 1848 | Reported monthly average departure delays (42.4 to 42.9). |
| Q16 | Summary statistics | **PASS** | 1692 | Reported mean (~6.17), median (4), max (71), std (~6.48), IQR (8). |
| Q17 | Percentiles | **PASS** | 1728 | Reported mean (~72.4), median (~72.7), std (~19.3), and 90th percentile (~98.7). |
| Q18 | Delay rate by airline | **PASS** | 1867 | Reported top airlines for Delay_Target=1 (Alliance Air, SpiceJet, Air India Express ~87-88%). |
| Q19 | Delay rate by weather | **PASS** | 1898 | Reported Delay_Target distribution across weather categories. |
| Q20 | Peak hour comparison | **PASS** | 2030 | Calculated mean delays for Peak_Hour 1 (~50.6) vs 0 (~35.5) and diff (~15.15). |

### Level 3 — Grouped analysis and ranking
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q21 | Multi-index aggregation | **PASS** | 3605 | Calculated highest-delay month for airlines with observation counts. |
| Q22 | Filtered route ranking | **PASS** | 4201 | Identified top routes with >= 100 obs by average delay (~48.6-49.1). |
| Q23 | Airport delay proportion | **PASS** | 1734 | Identified COK as origin airport with highest Delay_Target=1 rate (~93.3%). |
| Q24 | Weekend vs weekday comparison | **PASS** | 2146 | Compared weekend vs weekday departure delays by airline (diff ~3.3-4.8). |
| Q25 | Interaction analysis | **PASS** | 1998 | Compared weather delays across peak hours and identified group differences. |
| Q26 | Monthly rank concordance | **PASS** | 1895 | Correctly determined monthly delay and target-rate rankings are not identical. |
| Q27 | Day of week breakdown | **PASS** | 1939 | Reported departure delay stats across Day_of_Week values. |
| Q28 | Route peak sensitivity | **PASS** | 36976 | Identified routes with largest Peak_Hour mean difference (~10.5-11.4). |
| Q29 | Quartile grouping | **PASS** | 3137 | Reported delay stats across Origin_Congestion_Index quartiles. |
| Q30 | Two-factor ranking | **PASS** | 2271 | Returned top airline-weather delay combinations (Heavy Rain leading ~52-53 min). |

### Level 4 — Multi-step analysis and statistical reasoning
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q31 | Correlation matrix | **PASS** | 3240 | Computed correlation matrix; identified strongest positive and negative correlations. |
| Q32 | Bivariate correlation | **PASS** | 3600 | Reported correlation (~0.22) and sample size (150,000). |
| Q33 | Non-linear correlation | **PASS** | 2509 | Calculated both Pearson (~0.62) and Spearman (~0.61-0.66) correlations. |
| Q34 | Risk index quartiles | **PASS** | 1950 | Compared mean delays across Turnaround_Risk_Index quartiles (Q1 ~27.2 to Q4 ~51.5). |
| Q35 | Visibility relationship | **PASS** | 1686 | Evaluated visibility relationship with departure delay (weak/negligible correlation ~ -0.03). |
| Q36 | Rainfall threshold comparison | **PASS** | 2407 | Compared zero rainfall (~41.8 min) vs positive rainfall (~45.9 min) with difference (~4.03 min). |
| Q37 | Humidity quartiles | **PASS** | 2636 | Reported target-positive rates across humidity quartiles (~86.6% across all). |
| Q38 | Temporal consistency | **PASS** | 7760 | Confirmed Month agrees with calendar month from Flight_Date for all rows (0 mismatches). |
| Q39 | Weekday encoding | **PASS** | 5246 | Determined weekday encoding (0=Monday) and verified agreement with Flight_Date (0 mismatches). |
| Q40 | Weekend consistency | **PASS** | 21 | Confirmed Is_Weekend agrees with Flight_Date weekend definition (0 mismatches). |

### Level 5 — Hard filters, derived metrics, and data quality
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q41 | Compound filtering | **PASS** | 2199 | Filtered qualifying rows (31,060 / 20,443) with avg delay (~57.59-58.74) and target rate (100%). |
| Q42 | Tail risk subset | **PASS** | 2329 | Identified weather category with highest delay target rate under low visibility (Heavy Rain ~91.6%). |
| Q43 | Conditional route delays | **PASS** | 5064 | Identified top routes with previous delay > 0 and count >= 100 (delays ~49.9-50.1). |
| Q44 | Joint condition rate | **PASS** | 36456 | Calculated percentage of flights with Peak_Hour=1 and Delay_Target=1 by airline (~43%). |
| Q45 | Target calibration by quartile | **PASS** | 2984 | Grouped Departure_Delay into quartiles and compared Delay_Target distribution (Q1: ~55.8%, Q2-Q4: 100%). |
| Q46 | Delay propagation | **PASS** | 2831 | Calculated mean delays for previous delay = 0 (~37.71) vs > 0 (~44.09), difference ~6.38 min. |
| Q47 | Date-month audit | **PASS** | 3922 | Verified 0 mismatches between Flight_Date and Month (0.0%). |
| Q48 | Target domain audit | **PASS** | 45 | Confirmed Delay_Target has 0 invalid values (strictly binary {0, 1}). |
| Q49 | Median split comparison | **PASS** | 2967 | Compared target rates for above-median (~95.85%) vs below-median (~77.49%) turnaround risk (diff ~18.36 pp). |
| Q50 | Label normalization check | **PASS** | 90 | Explained normalization and confirmed distinct route count remains unchanged (4,864). |

### Level 6 — Adversarial, hypothetical, and hallucination-resistance tests
- **Score:** 10/10 PASS (100.0%), 0 PARTIAL, 0 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q51 | Unsupported column: ticket price | **PASS** | 106 | Correctly identified that ticket price does not exist in the dataset. |
| Q52 | Unsupported column: passenger count | **PASS** | 91 | Correctly identified that passenger count does not exist in the dataset. |
| Q53 | Ambiguous delay metric | **PASS** | 65 | Explicitly identified Departure_Delay (~42.66) as the chosen metric. |
| Q54 | Rule verification | **PASS** | 2105 | Inspected relationship: found all delayed flights have delay >= 19 (0 mismatches for >= 15 rule). |
| Q55 | Hypothetical filtering: peak hours | **PASS** | 2117 | Calculated hypothetical mean departure delay for Peak_Hour=1 (~50.61 min) without modifying dataset. |
| Q56 | Hypothetical filtering: visibility | **PASS** | 26 | Recognized 0 rows have visibility < 5 (min is 5.1 km), hypothetical mean unchanged (~42.66 min). |
| Q57 | Hypothetical transformation: clipping | **PASS** | 46 | Inspected range [0.4, 88.2]: recognized 0 values outside [0, 100], clipped mean unchanged (~35.72). |
| Q58 | Compound probability | **PASS** | 2607 | Reported qualifying count (43,303), denominator (150,000), and percentage (~28.87%). |
| Q59 | Unsupported column: customer satisfaction | **PASS** | 48 | Correctly rejected unsupported calculation: no customer satisfaction column exists. |
| Q60 | Target leakage reasoning | **PASS** | 116 | Identified Departure_Delay as primary target leakage risk and explained rationale. |

---

## 3. Detailed Failure & Partial Diagnostics

No failures or partials recorded. All 60 questions passed strictly.
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


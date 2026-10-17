# Plexis — Blind Generalization Benchmark Report
**Dataset:** `india_flight_delay_model_input.csv` (150,000 rows × 23 columns)  
**Dataset SHA-256:** `037ef3dc6074af183f11f4e7ea9febb6907dda987f7a52f6f5c339ee1476e3eb`  
**Application Git Commit:** `437e7ceebef6db61248ce0322a45288f426eb3ec`  
**Execution Timestamp:** 2026-10-14 21:23:01  

---

## 1. Executive Summary

| Metric | Value |
|---|---|
| **Total Questions Evaluated** | **60** |
| **Strict PASS** | **30** (50.0%) |
| **PARTIAL** | **3** (5.0%) |
| **FAIL** | **27** (45.0%) |
| **Clarification Required** | **0** |
| **Infrastructure Errors** | **0** |
| **Total Execution Time** | **249.39 seconds** |
| **Median Latency** | **2796.39 ms** |
| **p95 Latency** | **8397.46 ms** |
| **Maximum Latency** | **25988.86 ms** |

---

## 2. Score Breakdown by Level

### Level 1 — Dataset fundamentals and schema
- **Score:** 9/10 PASS (90.0%), 0 PARTIAL, 1 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q01 | Dataset dimensions | **PASS** | 15355 | Reported 150,000 rows and 23 columns. |
| Q02 | Date range | **PASS** | 5048 | Reported date range (2023-01-01 to 2025-12-30) and 1,095 distinct calendar dates. |
| Q03 | Missing values | **PASS** | 2494 | Correctly reported 0 missing cells across all columns. |
| Q04 | Schema and data types | **PASS** | 3537 | Classified 23 columns by observed types and semantic roles. |
| Q05 | Categorical cardinality | **PASS** | 4395 | Reported distinct counts for airlines (9), airports (86), and weather (4). |
| Q06 | Identifier uniqueness | **PASS** | 1959 | Reported ~50,854 unique flight numbers and confirmed they are not unique across all rows. |
| Q07 | Duplicate rows | **PASS** | 3063 | Reported 0 exact duplicate rows. |
| Q08 | Route cardinality | **PASS** | 2465 | Reported distinct route count (~4,864) and top frequent routes. |
| Q09 | Target variable distribution | **FAIL** | 6898 | Failed to report Departure_Delay distribution. |
| Q10 | Binary target distribution | **PASS** | 1816 | Reported Delay_Target counts: 1=129,925, 0=20,075. |

### Level 2 — Statistics and core aggregations
- **Score:** 8/10 PASS (80.0%), 0 PARTIAL, 2 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q11 | Grouped aggregation and ranking | **PASS** | 1933 | Calculated average departure delay by airline ranked with observations. |
| Q12 | Weather impact | **PASS** | 3009 | Reported mean/median departure delays across weather categories. |
| Q13 | Top origin delays | **PASS** | 2333 | Identified top origin airports (COK, MAA, AMD, CCU, BOM) with average delays (~46). |
| Q14 | Top destination delays | **PASS** | 1868 | Identified top destination airports (AMD, MAA, COK, HYD, CCU) with delays (~45). |
| Q15 | Monthly seasonality | **PASS** | 3723 | Reported monthly average departure delays (42.4 to 42.9). |
| Q16 | Summary statistics | **PASS** | 5540 | Reported mean (~6.17), median (4), max (71), std (~6.48), IQR (8). |
| Q17 | Percentiles | **PASS** | 2953 | Reported mean (~72.4), median (~72.7), std (~19.3), and 90th percentile (~98.7). |
| Q18 | Delay rate by airline | **FAIL** | 2772 | Failed to report airline delay target proportions. |
| Q19 | Delay rate by weather | **FAIL** | 25989 | Failed to report delay target distribution by weather. |
| Q20 | Peak hour comparison | **PASS** | 3280 | Calculated mean delays for Peak_Hour 1 (~50.6) vs 0 (~35.5) and diff (~15.15). |

### Level 3 — Grouped analysis and ranking
- **Score:** 1/10 PASS (10.0%), 1 PARTIAL, 8 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q21 | Multi-index aggregation | **FAIL** | 2473 | Failed to report highest delay month by airline. |
| Q22 | Filtered route ranking | **FAIL** | 2441 | Failed to identify top delayed routes. |
| Q23 | Airport delay proportion | **PASS** | 8394 | Identified COK as origin airport with highest Delay_Target=1 rate (~93.3%). |
| Q24 | Weekend vs weekday comparison | **FAIL** | 6551 | Failed to compare weekend vs weekday delays. |
| Q25 | Interaction analysis | **PARTIAL** | 2515 | Reported weather delays but incomplete peak hour comparison. |
| Q26 | Monthly rank concordance | **FAIL** | 4988 | Failed to evaluate monthly rank concordance. |
| Q27 | Day of week breakdown | **FAIL** | 1656 | Failed to report Day_of_Week breakdown. |
| Q28 | Route peak sensitivity | **FAIL** | 1890 | Failed to identify peak hour sensitive routes. |
| Q29 | Quartile grouping | **FAIL** | 2503 | Failed to report congestion index quartiles. |
| Q30 | Two-factor ranking | **FAIL** | 1362 | Failed to report airline-weather combinations. |

### Level 4 — Multi-step analysis and statistical reasoning
- **Score:** 5/10 PASS (50.0%), 0 PARTIAL, 5 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q31 | Correlation matrix | **PASS** | 2479 | Computed correlation matrix; identified strongest positive and negative correlations. |
| Q32 | Bivariate correlation | **PASS** | 1970 | Reported correlation (~0.22) and sample size (150,000). |
| Q33 | Non-linear correlation | **FAIL** | 1322 | Failed to calculate correlations. |
| Q34 | Risk index quartiles | **FAIL** | 3428 | Failed to calculate turnaround risk quartiles. |
| Q35 | Visibility relationship | **FAIL** | 1409 | Failed to evaluate visibility relationship. |
| Q36 | Rainfall threshold comparison | **PASS** | 1988 | Compared zero rainfall (~41.8 min) vs positive rainfall (~45.9 min) with difference (~4.03 min). |
| Q37 | Humidity quartiles | **FAIL** | 2490 | Failed to report humidity quartiles target rate. |
| Q38 | Temporal consistency | **FAIL** | 2821 | Failed to verify date-month agreement. |
| Q39 | Weekday encoding | **PASS** | 4818 | Determined weekday encoding (0=Monday) and verified agreement with Flight_Date (0 mismatches). |
| Q40 | Weekend consistency | **PASS** | 5895 | Confirmed Is_Weekend agrees with Flight_Date weekend definition (0 mismatches). |

### Level 5 — Hard filters, derived metrics, and data quality
- **Score:** 1/10 PASS (10.0%), 2 PARTIAL, 7 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q41 | Compound filtering | **FAIL** | 1605 | Failed compound filter query. |
| Q42 | Tail risk subset | **PARTIAL** | 6931 | Identified weather or delay rate under low visibility. |
| Q43 | Conditional route delays | **FAIL** | 1732 | Failed to identify top routes with previous delay. |
| Q44 | Joint condition rate | **FAIL** | 3168 | Failed to calculate joint condition rates. |
| Q45 | Target calibration by quartile | **FAIL** | 1360 | Failed to compare delay target across departure delay quartiles. |
| Q46 | Delay propagation | **FAIL** | 3824 | Failed to calculate previous delay comparison. |
| Q47 | Date-month audit | **FAIL** | 5369 | Failed to verify date-month audit. |
| Q48 | Target domain audit | **FAIL** | 6084 | Failed target domain audit. |
| Q49 | Median split comparison | **PASS** | 5417 | Compared target rates for above-median (~94.8%) vs below-median (~79.1%) turnaround risk (diff ~15.7 pp). |
| Q50 | Label normalization check | **PARTIAL** | 6554 | Mentioned route normalization without distinct count. |

### Level 6 — Adversarial, hypothetical, and hallucination-resistance tests
- **Score:** 6/10 PASS (60.0%), 0 PARTIAL, 4 FAIL

| ID | Category | Status | Latency (ms) | Diagnostic Reason |
|---|---|---|---|---|
| Q51 | Unsupported column: ticket price | **PASS** | 45 | Correctly identified that ticket price does not exist in the dataset. |
| Q52 | Unsupported column: passenger count | **PASS** | 47 | Correctly identified that passenger count does not exist in the dataset. |
| Q53 | Ambiguous delay metric | **FAIL** | 1027 | Failed to handle delay metric ambiguity. |
| Q54 | Rule verification | **PASS** | 3654 | Inspected relationship: found all delayed flights have delay >= 19 (0 mismatches for >= 15 rule). |
| Q55 | Hypothetical filtering: peak hours | **PASS** | 2282 | Calculated hypothetical mean departure delay for Peak_Hour=1 (~50.61 min) without modifying dataset. |
| Q56 | Hypothetical filtering: visibility | **PASS** | 8465 | Recognized 0 rows have visibility < 5 (min is 5.1 km), hypothetical mean unchanged (~42.66 min). |
| Q57 | Hypothetical transformation: clipping | **FAIL** | 7044 | Failed hypothetical clipping evaluation. |
| Q58 | Compound probability | **PASS** | 2735 | Reported qualifying count (43,303), denominator (150,000), and percentage (~28.87%). |
| Q59 | Unsupported column: customer satisfaction | **FAIL** | 7142 | Invented a satisfaction score or attempted unsupported calculation. |
| Q60 | Target leakage reasoning | **FAIL** | 1250 | Failed to identify target leakage risk. |

---

## 3. Detailed Failure & Partial Diagnostics

### [Q09] Target variable distribution — FAIL
- **Question:** What are the minimum, maximum, mean, and median values of Departure_Delay? Report the units only if supported by the dataset's definition.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report Departure_Delay distribution.
- **Actual Answer Preview:** I couldn't reliably interpret that analytical request. Could you rephrase it? For example: 'what is the highest age?'...
- **Latency:** 6898 ms

### [Q18] Delay rate by airline — FAIL
- **Question:** Which five airlines have the highest proportion of rows with Delay_Target = 1? Report the numerator, denominator, and rate for each airline.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report airline delay target proportions.
- **Actual Answer Preview:** I couldn't reliably interpret that analytical request. Could you rephrase it? For example: 'what is the highest age?'...
- **Latency:** 2772 ms

### [Q19] Delay rate by weather — FAIL
- **Question:** How does the distribution of Delay_Target vary across weather categories? Report counts and row-based percentages within each weather category.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report delay target distribution by weather.
- **Actual Answer Preview:** Most frequent values for **Delay_Target** in **india_flight_delay_model_input.csv**: 1: 129925, 0: 20075...
- **Latency:** 25989 ms

### [Q21] Multi-index aggregation — FAIL
- **Question:** For each airline, calculate average departure delay by month. Identify the highest-average-delay month for each airline and report the supporting observation count.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report highest delay month by airline.
- **Actual Answer Preview:** **Average Departure_Delay by Month** breakdown: **3**: 42.87, **7**: 42.83, **9**: 42.83, **8**: 42.79, **2**: 42.72, **10**: 42.70, **11**: 42.65, **6**: 42.60 (and 4 more)....
- **Latency:** 2473 ms

### [Q22] Filtered route ranking — FAIL
- **Question:** Which five origin-destination routes have the highest average departure delay? Exclude routes with fewer than 100 observations and report the count for each selected route.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to identify top delayed routes.
- **Actual Answer Preview:** The dataset does not contain a **count** column. The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, Scheduled_Departure_Hour, Schedule...
- **Latency:** 2441 ms

### [Q24] Weekend vs weekday comparison — FAIL
- **Question:** For each airline, compare the average Departure_Delay on weekends versus weekdays. Report both group means, group sizes, and the difference.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to compare weekend vs weekday delays.
- **Actual Answer Preview:** **Average Departure_Delay by Airline** breakdown: **Alliance Air**: 43.24, **SpiceJet**: 43.05, **Air India Express**: 43.02, **Fly91**: 42.98, **Star Air**: 42.97, **Air India**: 42.71, **IndiGo**: 4...
- **Latency:** 6551 ms

### [Q25] Interaction analysis — PARTIAL
- **Question:** Compare average departure delay for each Weather category across Peak_Hour groups. Identify the largest absolute difference and show the supporting group counts.
- **Status:** `PARTIAL`
- **Diagnostic Reason:** Reported weather delays but incomplete peak hour comparison.
- **Actual Answer Preview:** **Average Departure_Delay by Weather** breakdown: **Cloudy**: 53.00, **Heavy Rain**: 52.08, **Rain**: 45.45, **Clear/Partly Cloudy**: 41.84....
- **Latency:** 2515 ms

### [Q26] Monthly rank concordance — FAIL
- **Question:** For each month, report the mean departure delay and the proportion of Delay_Target = 1. Determine whether the monthly rankings for these two metrics are identical.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to evaluate monthly rank concordance.
- **Actual Answer Preview:** The average **Departure_Delay** in **india_flight_delay_model_input.csv** is **42.66434**.  The average **Delay_Target** in **india_flight_delay_model_input.csv** is **0.8661666666666666**....
- **Latency:** 4988 ms

### [Q27] Day of week breakdown — FAIL
- **Question:** For each Day_of_Week value, report average departure delay, median departure delay, row count, and target-positive rate. Do not assign weekday names unless the numbering convention is verified.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report Day_of_Week breakdown.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 1656 ms

### [Q28] Route peak sensitivity — FAIL
- **Question:** Which five routes have the largest absolute difference between mean departure delays in the two Peak_Hour groups? Require at least 100 observations in each group for a route to qualify.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to identify peak hour sensitive routes.
- **Actual Answer Preview:** The dataset does not contain a **absolute_difference_mean** column. The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, Scheduled_Depar...
- **Latency:** 1890 ms

### [Q29] Quartile grouping — FAIL
- **Question:** Compare departure-delay distributions across Origin_Congestion_Index quartiles. Report the quartile boundaries, sample counts, mean delays, medians, and target-positive rates.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report congestion index quartiles.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 2503 ms

### [Q30] Two-factor ranking — FAIL
- **Question:** Which combinations of airline and weather have the highest mean departure delay? Return the top 10 combinations, including sample counts, and explain how ties are handled.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report airline-weather combinations.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 1362 ms

### [Q33] Non-linear correlation — FAIL
- **Question:** Is Origin_Congestion_Index associated with Departure_Delay? Calculate Pearson and Spearman correlations and compare the results.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to calculate correlations.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 1322 ms

### [Q34] Risk index quartiles — FAIL
- **Question:** Compare mean departure delay across quartiles of Turnaround_Risk_Index. Report quartile boundaries, group counts, mean delays, and target-positive rates.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to calculate turnaround risk quartiles.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 3428 ms

### [Q35] Visibility relationship — FAIL
- **Question:** Does visibility have a relationship with departure delay? Calculate Pearson and Spearman correlations and compare mean delays across visibility quartiles.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to evaluate visibility relationship.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 1409 ms

### [Q37] Humidity quartiles — FAIL
- **Question:** Compare target-positive rates across quartiles of Humidity_pct. Report boundaries, counts, rates, and percentage-point differences between the highest and lowest quartiles.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to report humidity quartiles target rate.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 2490 ms

### [Q38] Temporal consistency — FAIL
- **Question:** Does Month agree with the calendar month extracted from Flight_Date for every row? Report the mismatch count and examples, if any.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to verify date-month agreement.
- **Actual Answer Preview:** I couldn't reliably interpret that analytical request. Could you rephrase it? For example: 'what is the highest age?'...
- **Latency:** 2821 ms

### [Q41] Compound filtering — FAIL
- **Question:** Filter flights where Departure_Delay is above the overall median and Origin_Congestion_Index is above its overall 75th percentile. How many rows qualify, and what is their average departure delay and target-positive rate?
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed compound filter query.
- **Actual Answer Preview:** The dataset does not contain a **target_positive_rate** column. The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, Scheduled_Departure...
- **Latency:** 1605 ms

### [Q42] Tail risk subset — PARTIAL
- **Question:** Among rows with Visibility_km below its 10th percentile, which weather category has the highest target-positive rate? Report its count, denominator, rate, and comparison against the overall rate.
- **Status:** `PARTIAL`
- **Diagnostic Reason:** Identified weather or delay rate under low visibility.
- **Actual Answer Preview:** The dataset does not contain a **target-positive_rate** column. The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, Scheduled_Departure...
- **Latency:** 6931 ms

### [Q43] Conditional route delays — FAIL
- **Question:** Find the five routes with the highest average Departure_Delay among rows where Previous_Flight_Delay_Minutes is greater than zero. Require at least 100 eligible observations per route.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to identify top routes with previous delay.
- **Actual Answer Preview:** The dataset does not contain a **count** column. The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, Scheduled_Departure_Hour, Schedule...
- **Latency:** 1732 ms

### [Q44] Joint condition rate — FAIL
- **Question:** For each airline, calculate the percentage of rows with both Peak_Hour = 1 and Delay_Target = 1. Include the numerator, denominator, and rate, and rank the airlines.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to calculate joint condition rates.
- **Actual Answer Preview:** The dataset does not contain a **rate** column. The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, Scheduled_Departure_Hour, Scheduled...
- **Latency:** 3168 ms

### [Q45] Target calibration by quartile — FAIL
- **Question:** Create a temporary grouping of Departure_Delay into quartiles. Compare the distribution of Delay_Target across those quartiles and report target-positive rates and row counts. Do not modify the source dataset.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to compare delay target across departure delay quartiles.
- **Actual Answer Preview:** Most frequent values for **Delay_Target** in **india_flight_delay_model_input.csv**: 1: 129925, 0: 20075...
- **Latency:** 1360 ms

### [Q46] Delay propagation — FAIL
- **Question:** Calculate the difference between the mean departure delay for flights with Previous_Flight_Delay_Minutes = 0 and those with a positive previous-flight delay. Include group counts, means, medians, and the difference in means.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to calculate previous delay comparison.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 3824 ms

### [Q47] Date-month audit — FAIL
- **Question:** Identify rows where Flight_Date indicates one month but Month indicates another. Report the total count, mismatch percentage, and representative examples. If no mismatches exist, report zero and verify it.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to verify date-month audit.
- **Actual Answer Preview:** I couldn't reliably interpret that analytical request. Could you rephrase it? For example: 'what is the highest age?'...
- **Latency:** 5369 ms

### [Q48] Target domain audit — FAIL
- **Question:** Identify rows where Delay_Target is outside the observed binary values 0 and 1. Report invalid values and counts, if any, without assuming that a particular target threshold is correct.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed target domain audit.
- **Actual Answer Preview:** I couldn't reliably interpret that analytical request. Could you rephrase it? For example: 'what is the highest age?'...
- **Latency:** 6084 ms

### [Q50] Label normalization check — PARTIAL
- **Question:** Compare average departure delay by origin-destination route after normalizing route labels only for analysis, if normalization is necessary. Explain the normalization and show whether it changes the number of distinct route groups. Do not mutate the source dataset.
- **Status:** `PARTIAL`
- **Diagnostic Reason:** Mentioned route normalization without distinct count.
- **Actual Answer Preview:** Unique counts: {'Flight_Date': 1095, 'Airline': 9, 'Flight_Number': 50854, 'Origin_Airport': 86, 'Destination_Airport': 86, 'Scheduled_Departure_Hour': 19, 'Scheduled_Departure_Minute': 60, 'Day_of_We...
- **Latency:** 6554 ms

### [Q53] Ambiguous delay metric — FAIL
- **Question:** What is the average flight delay?
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to handle delay metric ambiguity.
- **Actual Answer Preview:** I computed the result but couldn't generate the full explanation right now....
- **Latency:** 1027 ms

### [Q57] Hypothetical transformation: clipping — FAIL
- **Question:** If Turnaround_Risk_Index values were hypothetically clipped to the interval [0, 100], how many values would change and what would the resulting mean be? First inspect the actual range. Do not apply the transformation to the source dataset.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed hypothetical clipping evaluation.
- **Actual Answer Preview:** I couldn't reliably interpret that analytical request. Could you rephrase it? For example: 'what is the highest age?'...
- **Latency:** 7044 ms

### [Q59] Unsupported column: customer satisfaction — FAIL
- **Question:** Calculate a customer satisfaction score for each airline.
- **Status:** `FAIL`
- **Diagnostic Reason:** Invented a satisfaction score or attempted unsupported calculation.
- **Actual Answer Preview:** Sorry, I ran into an issue generating a response. Try again?...
- **Latency:** 7142 ms

### [Q60] Target leakage reasoning — FAIL
- **Question:** If the goal is to predict Delay_Target, which available columns could cause target leakage or require further investigation? Identify Departure_Delay as a potential leakage risk, explain why, and distinguish observed dataset facts from assumptions about how the target was generated. Do not train a model or change the dataset.
- **Status:** `FAIL`
- **Diagnostic Reason:** Failed to identify target leakage risk.
- **Actual Answer Preview:** Opening the Investigation workspace for your dataset....
- **Latency:** 1250 ms

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


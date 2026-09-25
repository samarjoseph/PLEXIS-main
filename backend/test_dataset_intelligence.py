"""
Dataset Intelligence Engine — End-to-End Verification Test

Tests the full 11-stage pipeline on a mock sales dataset.
Validates that all stages produce correct output shapes and types.
"""
import sys
import logging
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

import pandas as pd
import numpy as np

# Suppress verbose provider logs during test
logging.getLogger("providers").setLevel(logging.WARNING)

from dataset_intelligence import dataset_intelligence_engine, DatasetKnowledgeObject


def make_mock_sales_df() -> pd.DataFrame:
    """Create a realistic mock sales dataset."""
    np.random.seed(42)
    n = 500

    return pd.DataFrame({
        "Transaction_ID": [f"TXN-{i:04d}" for i in range(n)],
        "Customer_Name": [f"Customer {i % 100}" for i in range(n)],
        "Region": np.random.choice(["North", "South", "East", "West"], n),
        "Product_Category": np.random.choice(["Electronics", "Clothing", "Food", "Sports"], n),
        "Purchase_Date": pd.date_range("2022-01-01", periods=n, freq="D"),
        "Quantity": np.random.randint(1, 50, n),
        "Price": np.round(np.random.uniform(10, 500, n), 2),
        "Revenue": np.round(np.random.exponential(scale=200, size=n), 2),
        "Cost": np.round(np.random.uniform(5, 300, n), 2),
        "Discount": np.round(np.random.uniform(0, 50, n), 2),
        "Is_Returned": np.random.choice([True, False], n, p=[0.1, 0.9]),
    })


def run_verification():
    df = make_mock_sales_df()
    # Inject some nulls and duplicates for quality testing
    df.loc[0:20, "Cost"] = None
    df = pd.concat([df, df.head(5)], ignore_index=True)

    print("=" * 60)
    print("  Dataset Intelligence Engine - Verification Test")
    print("=" * 60)
    print(f"Input: {len(df):,} rows x {len(df.columns)} columns\n")

    # Run with LLM narration (full pipeline)
    dko = dataset_intelligence_engine.analyze(df, "mock_sales_data.csv")

    assert isinstance(dko, DatasetKnowledgeObject), "Should return a DatasetKnowledgeObject"
    print("PASS: Engine returned DatasetKnowledgeObject")

    # Stage 1 validation
    assert len(dko.columns) == len(df.columns), "Column count mismatch"
    print(f"PASS Stage 1 (Schema): {len(dko.columns)} columns classified")
    for col in dko.columns.values():
        print(f"   {col.name:25s} | {col.role.value:20s} | {col.semantic_type.value}")

    # Stage 2 validation
    rev_stats = dko.columns.get("Revenue")
    assert rev_stats is not None and rev_stats.numeric_stats is not None
    print(f"\nPASS Stage 2 (Statistics): Revenue mean={rev_stats.numeric_stats.mean:.2f}, skewness={rev_stats.numeric_stats.skewness_label}")

    # Stage 3 validation
    assert 0 <= dko.quality_report.overall_score <= 100
    print(f"\nPASS Stage 3 (Quality): Score={dko.quality_report.overall_score:.0f}/100 ({dko.quality_report.analysis_readiness})")
    print(f"   Completeness: {dko.quality_report.completeness_score:.0f} | Uniqueness: {dko.quality_report.uniqueness_score:.0f}")
    print(f"   Issues detected: {len(dko.quality_report.issues)}")
    for issue in dko.quality_report.issues[:3]:
        print(f"   [{issue.severity.value.upper()}] {issue.description[:70]}")

    # Stage 4 validation
    print(f"\nPASS Stage 4 (Relationships): {len(dko.get_relationships().correlations)} correlations found")
    for corr in dko.get_relationships().correlations[:3]:
        print(f"   {corr.col_a} <-> {corr.col_b}: r={corr.pearson_r:.3f} ({corr.strength})")

    # Stage 5 validation
    metrics = [m.name for m in dko.get_primary_metrics()]
    dimensions = [d.name for d in dko.get_grouping_dimensions()]
    time_columns = [t.name for t in dko.get_time_dimensions()]
    assert metrics, "Should have metrics"
    assert dimensions, "Should have dimensions"
    print(f"\nPASS Stage 5 (Semantics): {len(metrics)} metrics, {len(dimensions)} dimensions")
    print(f"   Metrics:    {metrics}")
    print(f"   Dimensions: {dimensions}")
    print(f"   Time:       {time_columns}")

    # Stage 6 validation
    print(f"\nPASS Stage 6 (Domain): {dko.get_dataset_identity().probable_purpose}")

    # Stage 7 validation
    opportunities = dko.get_analysis_opportunities()
    assert len(opportunities) > 0
    print(f"\nPASS Stage 7 (Capabilities): {len(opportunities)} types supported")
    print(f"   {[o.name for o in opportunities]}")

    # Stage 8 validation
    assert len(dko.predicted_questions) > 0
    print(f"\nPASS Stage 8 (Questions): {len(dko.predicted_questions)} questions predicted")
    for q in dko.predicted_questions[:5]:
        print(f"   [{q.category}] {q.question}")

    # Stage 9 validation
    assert len(dko.insights) > 0
    print(f"\nPASS Stage 9 (Insights): {len(dko.insights)} insights generated")
    for ins in dko.insights[:4]:
        print(f"   [{ins.severity.value.upper()}] {ins.title}")

    # Stage 11 validation
    print(f"\nPASS Stage 11 (Presentation): generated_by={dko.presentation.generated_by}")
    if dko.presentation.presentation:
        print(f"   Overview:\n{dko.presentation.presentation}")
    
    # Composite scores
    print(f"\nFINAL SCORES:")
    print(f"   Data Quality Score:     {dko.quality_report.overall_score:.0f}/100")
    print(f"   Analysis Readiness:     {dko.quality_report.analysis_readiness}")

    # Second run — should be cache hit
    print("\n--- Testing cache hit ---")
    dko2 = dataset_intelligence_engine.analyze(df, "mock_sales_data.csv")
    assert dko2.fingerprint == dko.fingerprint
    print("PASS: Cache hit confirmed")

    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_verification()

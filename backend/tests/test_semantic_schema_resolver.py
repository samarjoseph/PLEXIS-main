"""
Unit and Generalization Tests for SemanticSchemaResolver.

Tests:
1. Schema inference and semantic profiling on unfamiliar synthetic schemas.
2. Head-noun / modifier priority (e.g., 'customer rating' -> 'Rating', not 'Customer_ID').
3. Strict financial sub-concept clustering (compensation vs revenue vs unit price).
4. Ambiguity detection between multiple valid measures (e.g., 'Order_Value' vs 'Total_Amount').
5. Unsupported concept rejection without hallucination or guessing.
6. Deterministic instance-level caching with zero risk of stale results.
"""

import pytest
import pandas as pd
import numpy as np
from dataset_intelligence.semantic_resolver import (
    SemanticSchemaResolver,
    SemanticRole,
    get_semantic_resolver,
)


@pytest.fixture
def resolver():
    return SemanticSchemaResolver()


@pytest.fixture
def hr_df():
    """Unfamiliar synthetic HR dataset."""
    np.random.seed(42)
    n = 200
    return pd.DataFrame({
        "Emp_ID": [f"EMP_{i:04d}" for i in range(n)],
        "Full_Name": [f"Employee {i}" for i in range(n)],
        "Annual_Compensation": np.random.uniform(50000, 150000, n),
        "Performance_Rating": np.random.choice([1, 2, 3, 4, 5], n),
        "Department_Name": np.random.choice(["Engineering", "Sales", "HR", "Legal"], n),
        "Hire_Date": pd.date_range("2020-01-01", periods=n, freq="D").astype(str),
        "Is_Active": np.random.choice([0, 1], n, p=[0.1, 0.9]),
    })


@pytest.fixture
def retail_df():
    """Unfamiliar retail transactions dataset with duplicate measures."""
    np.random.seed(42)
    n = 150
    return pd.DataFrame({
        "Invoice_Number": [f"INV_{i:05d}" for i in range(n)],
        "Customer_Ref": [f"CUST_{i%30:03d}" for i in range(n)],
        "Total_Amount": np.random.uniform(20, 500, n),
        "Order_Value": np.random.uniform(20, 500, n),
        "Unit_Cost": np.random.uniform(5, 50, n),
        "Satisfaction_Score": np.random.uniform(1.0, 5.0, n),
        "Payment_Channel": np.random.choice(["Credit Card", "PayPal", "Bank Transfer"], n),
    })


def test_head_noun_weighting(resolver, hr_df):
    """'Employee rating' must resolve to 'Performance_Rating', not 'Emp_ID'."""
    res = resolver.resolve("employee rating", hr_df)
    assert res.resolved_column == "Performance_Rating"
    assert res.confidence >= 0.70
    assert not res.is_ambiguous


def test_compensation_vs_revenue(resolver, hr_df):
    """'Salary' or 'compensation' should match 'Annual_Compensation'."""
    res_sal = resolver.resolve("salary", hr_df)
    assert res_sal.resolved_column == "Annual_Compensation"
    assert res_sal.confidence >= 0.70

    res_comp = resolver.resolve("employee compensation", hr_df)
    assert res_comp.resolved_column == "Annual_Compensation"


def test_strict_financial_boundary(resolver, retail_df):
    """In a retail sales dataset, 'salary' must be rejected as UNSUPPORTED."""
    res = resolver.resolve("salary", retail_df)
    assert res.resolved_column is None
    assert res.status == "UNSUPPORTED"
    assert res.confidence == 0.0


def test_ambiguity_detection(resolver, retail_df):
    """Asking for 'order amount' when both Total_Amount and Order_Value exist should flag ambiguity."""
    res = resolver.resolve("order amount", retail_df)
    assert res.resolved_column in ("Total_Amount", "Order_Value")
    assert res.is_ambiguous is True
    assert "candidates" in res.ambiguity_details


def test_payment_method_resolution(resolver, retail_df):
    """'Payment method' must resolve to 'Payment_Channel'."""
    res = resolver.resolve("payment method", retail_df)
    assert res.resolved_column == "Payment_Channel"
    assert res.confidence >= 0.75
    assert not res.is_ambiguous


def test_rating_score_resolution(resolver, retail_df):
    """'Customer rating' must resolve to 'Satisfaction_Score'."""
    res = resolver.resolve("customer rating", retail_df)
    assert res.resolved_column == "Satisfaction_Score"
    assert res.confidence >= 0.70


def test_unsupported_concept_rejection(resolver, hr_df):
    """Concepts with zero semantic overlap must be cleanly rejected."""
    res = resolver.resolve("flight delay minutes", hr_df)
    assert res.resolved_column is None
    assert res.status == "UNSUPPORTED"
    assert res.confidence == 0.0


def test_caching_behavior(resolver, hr_df):
    """Resolving the same concept twice must use instance cache."""
    res1 = resolver.resolve("employee rating", hr_df)
    # Profile must be in cache
    cache_key = resolver._get_cache_key(hr_df)
    assert cache_key in resolver._profile_cache

    res2 = resolver.resolve("employee rating", hr_df)
    assert res1.resolved_column == res2.resolved_column
    assert res1.confidence == res2.confidence

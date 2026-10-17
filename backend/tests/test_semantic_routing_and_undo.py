"""
Tests for Bug 1 (replace 'missing' vs FILL_MISSING semantics)
and Bug 2 (undo history integrity).

Run with:
  python -c "import sys; sys.path.insert(0, 'backend'); import pytest; pytest.main(['backend/tests/test_semantic_routing_and_undo.py', '-v'])"
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pandas as pd
import numpy as np

from router.master_router import _parse_transform_from_message
from transformation.history import TransformationHistory
from transformation.contracts import TransformationPlan, AffectedCell


# ══════════════════════════════════════════════════════════════════════════════
# Bug 1 — Semantic routing tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFillMissingRouting:
    """Requests that SHOULD route to FILL_MISSING."""

    def test_fill_missing_values_with_0(self):
        op = _parse_transform_from_message("fill missing values with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"
        assert op["value"] == 0

    def test_fill_the_missing_values_with_0(self):
        op = _parse_transform_from_message("fill the missing values with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_fill_nan_values_with_0(self):
        op = _parse_transform_from_message("fill NaN values with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_replace_null_with_0(self):
        op = _parse_transform_from_message("replace null with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_replace_nan_with_0(self):
        op = _parse_transform_from_message("replace NaN with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_replace_missing_values_with_0(self):
        """'replace missing values with 0' — 'values' keyword present → FILL_MISSING."""
        op = _parse_transform_from_message("replace missing values with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_replace_empty_values_with_0(self):
        op = _parse_transform_from_message("replace empty values with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_fill_empty_values_with_0(self):
        op = _parse_transform_from_message("fill empty values with 0")
        assert op is not None
        assert op["type"] == "FILL_MISSING"

    def test_fill_missing_with_mean(self):
        op = _parse_transform_from_message("fill missing values with mean")
        assert op is not None
        assert op["type"] == "FILL_MISSING"
        assert op["value"] == "mean"

    def test_fill_null_values_with_median(self):
        op = _parse_transform_from_message("fill null values with median")
        assert op is not None
        assert op["type"] == "FILL_MISSING"
        assert op["value"] == "median"


class TestReplaceValuesRouting:
    """Requests that SHOULD route to REPLACE_VALUES."""

    def test_replace_single_quoted_missing_with_0(self):
        op = _parse_transform_from_message("replace 'missing' with 0")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "missing"
        assert op["new_value"] == 0

    def test_replace_double_quoted_missing_with_0(self):
        op = _parse_transform_from_message('replace "missing" with 0')
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "missing"
        assert op["new_value"] == 0

    def test_replace_quoted_na_with_0(self):
        op = _parse_transform_from_message("replace 'N/A' with 0")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "N/A"

    def test_replace_the_string_missing_with_0(self):
        op = _parse_transform_from_message("replace the string missing with 0")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "missing"

    def test_replace_cells_containing_missing_with_0(self):
        op = _parse_transform_from_message("replace cells containing missing with 0")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "missing"

    def test_replace_delhi_with_new_delhi(self):
        op = _parse_transform_from_message("replace Delhi with New Delhi")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "Delhi"

    def test_replace_usa_with_us(self):
        op = _parse_transform_from_message("replace USA with US")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "USA"
        assert op["new_value"] == "US"


class TestDataframeBehavior:
    """Actual DataFrame-level behavior tests."""

    def _make_df(self):
        """DataFrame with both literal 'missing' and actual NaN."""
        return pd.DataFrame({
            "name": ["Alice", "missing", "Bob", np.nan],
        })

    def test_replace_literal_missing_leaves_nan_intact(self):
        """'replace 'missing' with 0' must NOT touch NaN."""
        df = self._make_df()
        # Simulate REPLACE_VALUES operation
        result = df.copy()
        result["name"] = result["name"].replace("missing", "0")
        assert result["name"].tolist()[0] == "Alice"
        assert result["name"].tolist()[1] == "0"
        assert result["name"].tolist()[2] == "Bob"
        assert pd.isna(result["name"].tolist()[3])  # NaN untouched

    def test_fill_missing_leaves_literal_missing_intact(self):
        """'fill missing values with 0' must NOT touch the literal string 'missing'."""
        df = self._make_df()
        # Simulate FILL_MISSING operation
        result = df.copy()
        result["name"] = result["name"].fillna("0")
        assert result["name"].tolist()[0] == "Alice"
        assert result["name"].tolist()[1] == "missing"  # literal preserved
        assert result["name"].tolist()[2] == "Bob"
        assert result["name"].tolist()[3] == "0"  # NaN filled


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2 — Undo history integrity tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTransformationHistory:
    """Tests for the in-memory undo history system."""

    def _make_history(self):
        return TransformationHistory()

    def _make_df(self):
        return pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})

    def test_empty_history_returns_none(self):
        """Undo on clean dataset returns None."""
        h = self._make_history()
        assert h.has_history("ds1") is False
        assert h.pop("ds1") is None

    def test_initial_version_is_zero(self):
        h = self._make_history()
        assert h.get_version("ds1") == 0

    def test_version_increments(self):
        h = self._make_history()
        v1 = h.increment_version("ds1")
        v2 = h.increment_version("ds1")
        assert v1 == 1
        assert v2 == 2

    def test_record_creates_undo_entry(self):
        h = self._make_history()
        df = self._make_df()
        h.record(
            dataset_id="ds1",
            plan_id="plan_1",
            operation_type="FILL_MISSING",
            operation_label="Fill missing values with 0",
            previous_df=df,
            previous_version=0,
            result_version=1,
            changed_cells=3,
        )
        assert h.has_history("ds1") is True
        assert h.get_depth("ds1") == 1

    def test_undo_restores_previous_state(self):
        h = self._make_history()
        original_df = self._make_df()
        h.record(
            dataset_id="ds1",
            plan_id="plan_1",
            operation_type="FILL_MISSING",
            operation_label="Fill missing values with 0",
            previous_df=original_df,
            previous_version=0,
            result_version=1,
            changed_cells=3,
        )
        entry = h.pop("ds1")
        assert entry is not None
        assert entry.plan_id == "plan_1"
        assert entry.previous_df.equals(original_df)
        assert h.has_history("ds1") is False

    def test_multiple_undo_lifo_order(self):
        """A → B → C. Undo returns C first, then B, then A."""
        h = self._make_history()
        df_original = pd.DataFrame({"x": [1]})
        df_after_a = pd.DataFrame({"x": [10]})
        df_after_b = pd.DataFrame({"x": [100]})

        h.record("ds1", "p1", "T", "Op A", df_original, 0, 1)
        h.record("ds1", "p2", "T", "Op B", df_after_a, 1, 2)
        h.record("ds1", "p3", "T", "Op C", df_after_b, 2, 3)

        c = h.pop("ds1")
        assert c.operation_label == "Op C"
        assert c.previous_df.equals(df_after_b)

        b = h.pop("ds1")
        assert b.operation_label == "Op B"
        assert b.previous_df.equals(df_after_a)

        a = h.pop("ds1")
        assert a.operation_label == "Op A"
        assert a.previous_df.equals(df_original)

        assert h.pop("ds1") is None

    def test_wrong_dataset_id_returns_none(self):
        """Undo for dataset X should not return history from dataset Y."""
        h = self._make_history()
        df = self._make_df()
        h.record("ds_x", "p1", "T", "Op", df, 0, 1)
        assert h.has_history("ds_y") is False
        assert h.pop("ds_y") is None

    def test_noop_produces_zero_entries(self):
        """Simulates no-op by never recording — history should be empty."""
        h = self._make_history()
        # No record() called = no history
        assert h.has_history("ds1") is False
        assert h.get_depth("ds1") == 0

    def test_undo_after_no_history_clean_response(self):
        """Verifies pop returns None cleanly when no history."""
        h = self._make_history()
        result = h.pop("ds_nonexistent")
        assert result is None

    def test_pop_increments_version(self):
        """Undo should increment dataset version (undo is a state mutation)."""
        h = self._make_history()
        df = self._make_df()
        h.increment_version("ds1")  # version 1
        h.record("ds1", "p1", "T", "Op", df, 0, 1)

        v_before = h.get_version("ds1")
        h.pop("ds1")
        v_after = h.get_version("ds1")
        assert v_after == v_before + 1

    def test_datasets_are_independent(self):
        """History for one dataset doesn't affect another."""
        h = self._make_history()
        df = self._make_df()
        h.record("ds_a", "p1", "T", "Op A", df, 0, 1)
        h.record("ds_b", "p2", "T", "Op B", df, 0, 1)

        assert h.get_depth("ds_a") == 1
        assert h.get_depth("ds_b") == 1

        h.pop("ds_a")
        assert h.get_depth("ds_a") == 0
        assert h.get_depth("ds_b") == 1  # Untouched

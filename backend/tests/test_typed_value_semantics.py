"""
Tests for typed value semantics in transformation pipeline.

Covers:
  - TypedLiteral parsing (int vs float vs string vs bool vs null)
  - Router producing correctly-typed old_value/new_value
  - Planner type-aware column search
  - Executor preserving types through replace
  - End-to-end: fill missing → numeric 0, then replace numeric 0 → string "unknown"
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import numpy as np
import pandas as pd

from datasets.semantics.typed_literal import (
    parse_literal, extract_typed_value, TypedLiteral, semantic_equals, build_mask,
)
from router.master_router import _parse_transform_from_message
from core.context import ExecutionContext


# ══════════════════════════════════════════════════════════════════════════════
# TypedLiteral unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTypedLiteralParsing:

    def test_unquoted_zero_is_integer(self):
        lit = parse_literal("0")
        assert lit.value == 0
        assert lit.value_type == 'integer'
        assert isinstance(lit.value, int)

    def test_unquoted_float(self):
        lit = parse_literal("0.5")
        assert lit.value == 0.5
        assert lit.value_type == 'float'
        assert isinstance(lit.value, float)

    def test_unquoted_negative_int(self):
        lit = parse_literal("-1")
        assert lit.value == -1
        assert lit.value_type == 'integer'

    def test_quoted_zero_is_string(self):
        lit = parse_literal("0", was_quoted=True)
        assert lit.value == "0"
        assert lit.value_type == 'string'
        assert isinstance(lit.value, str)

    def test_quoted_word_is_string(self):
        lit = parse_literal("unknown", was_quoted=True)
        assert lit.value == "unknown"
        assert lit.value_type == 'string'

    def test_unquoted_true_is_bool(self):
        lit = parse_literal("true")
        assert lit.value is True
        assert lit.value_type == 'boolean'

    def test_unquoted_false_is_bool(self):
        lit = parse_literal("false")
        assert lit.value is False
        assert lit.value_type == 'boolean'

    def test_unquoted_null_is_none(self):
        lit = parse_literal("null")
        assert lit.value is None
        assert lit.value_type == 'null'
        assert lit.is_null

    def test_unquoted_nan_is_none(self):
        lit = parse_literal("nan")
        assert lit.value is None
        assert lit.value_type == 'null'

    def test_quoted_null_is_string(self):
        lit = parse_literal("null", was_quoted=True)
        assert lit.value == "null"
        assert lit.value_type == 'string'

    def test_quoted_nan_is_string(self):
        lit = parse_literal("NaN", was_quoted=True)
        assert lit.value == "NaN"
        assert lit.value_type == 'string'

    def test_unquoted_word_is_string(self):
        lit = parse_literal("unknown")
        assert lit.value == "unknown"
        assert lit.value_type == 'string'

    def test_int_vs_str_are_distinct_types(self):
        int_lit = parse_literal("0")
        str_lit = parse_literal("0", was_quoted=True)
        assert int_lit.value != str_lit.value or type(int_lit.value) != type(str_lit.value)
        assert int_lit.value_type == 'integer'
        assert str_lit.value_type == 'string'


# ══════════════════════════════════════════════════════════════════════════════
# Router type-preservation tests
# ══════════════════════════════════════════════════════════════════════════════

class TestRouterTypedValues:

    def test_replace_unquoted_0_gives_integer(self):
        """'replace 0 with unknown' → old_value must be int(0), not str('0')."""
        op = _parse_transform_from_message("replace 0 with unknown")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == 0
        assert isinstance(op["old_value"], int), f"Expected int, got {type(op['old_value'])}"
        assert op["new_value"] == "unknown"
        assert isinstance(op["new_value"], str)


class TestSessionCorrectionReplanning:

    def test_string_correction_replans_preview_and_invalidates_old_plan(self):
        from router.master_router import MasterRouter
        from transformation.planner import transformation_planner
        from transformation.store import transformation_store

        dataset_id = "correction-dataset"
        session_id = "correction-session"
        df = pd.DataFrame({"value": [0, "0"]})
        original = parse_literal("0")
        old_plan = transformation_planner.plan(df, {
            "type": "REPLACE_VALUES", "column": "value", "old_value": 0,
            "new_value": "unknown", "_old_typed": original.to_dict(),
        }, dataset_id)
        transformation_store.store(old_plan, session_id=session_id)

        context = ExecutionContext(
            message='I meant the string "0"',
            session_id=session_id,
            dataset_id=dataset_id,
        )
        payload = MasterRouter()._fast_path(context)
        assert payload["intent"] == "TRANSFORM"
        corrected_op = payload["operation"]
        assert corrected_op["_old_typed"]["value_type"] == "string"
        assert corrected_op["old_value"] == "0"
        assert transformation_store.get(old_plan.plan_id) is None

        corrected = transformation_planner.plan(df, corrected_op, dataset_id)
        assert corrected.affected_cells_count == 1
        assert corrected.before_sample[0].before == "0"
        transformation_store.store(corrected, session_id=session_id)

        from transformation.executor import transformation_executor
        result = transformation_executor._execute(df.copy(), corrected)
        assert result["value"].tolist() == [0, "unknown"]

    def test_fill_replace_then_correct_string_zero_and_apply(self):
        from router.master_router import MasterRouter
        from transformation.planner import transformation_planner
        from transformation.store import transformation_store
        from transformation.executor import transformation_executor

        dataset_id, session_id = "workflow-dataset", "workflow-session"
        df = pd.DataFrame({"value": [np.nan, 0.0, "0"]}, dtype=object)

        fill = transformation_planner.plan(
            df, {"type": "FILL_MISSING", "value": 0}, dataset_id,
        )
        df = transformation_executor._execute(df.copy(), fill)
        assert df["value"].tolist() == [0, 0.0, "0"]

        first_op = _parse_transform_from_message("replace 0 with unknown")
        first = transformation_planner.plan(df, first_op, dataset_id)
        df = transformation_executor._execute(df.copy(), first)
        assert df["value"].tolist() == ["unknown", "unknown", "0"]

        mistaken_op = _parse_transform_from_message("replace 0 with zero-string")
        mistaken = transformation_planner.plan(df, mistaken_op, dataset_id)
        transformation_store.store(mistaken, session_id=session_id)
        assert mistaken.affected_cells_count == 0

        correction = MasterRouter()._fast_path(ExecutionContext(
            message='I meant the string "0"',
            session_id=session_id,
            dataset_id=dataset_id,
        ))
        corrected = transformation_planner.plan(df, correction["operation"], dataset_id)
        assert corrected.affected_cells_count == 1
        assert corrected.before_sample[0].before == "0"
        df = transformation_executor._execute(df.copy(), corrected)
        assert df["value"].tolist() == ["unknown", "unknown", "zero-string"]

    def test_replace_quoted_0_gives_string(self):
        """'replace \"0\" with unknown' → old_value must be str('0')."""
        op = _parse_transform_from_message('replace "0" with unknown')
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "0"
        assert isinstance(op["old_value"], str), f"Expected str, got {type(op['old_value'])}"

    def test_replace_single_quoted_0_gives_string(self):
        op = _parse_transform_from_message("replace '0' with unknown")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == "0"
        assert isinstance(op["old_value"], str)

    def test_replace_float_is_float(self):
        op = _parse_transform_from_message("replace 0.5 with 1.0")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        assert op["old_value"] == 0.5
        assert isinstance(op["old_value"], float)
        assert op["new_value"] == 1.0
        assert isinstance(op["new_value"], float)

    def test_replace_int_with_string(self):
        op = _parse_transform_from_message("replace 1 with unknown")
        assert op is not None
        assert op["old_value"] == 1
        assert isinstance(op["old_value"], int)
        assert op["new_value"] == "unknown"
        assert isinstance(op["new_value"], str)

    def test_replace_usa_with_us_are_strings(self):
        op = _parse_transform_from_message("replace USA with US")
        assert op is not None
        assert op["type"] == "REPLACE_VALUES"
        # Bare words → strings
        assert isinstance(op["old_value"], str)
        assert isinstance(op["new_value"], str)

    def test_replace_quoted_new_value_is_string(self):
        """'replace 0 with \"unknown\"' → new_value is string."""
        op = _parse_transform_from_message('replace 0 with "unknown"')
        assert op is not None
        assert op["old_value"] == 0
        assert isinstance(op["old_value"], int)
        assert op["new_value"] == "unknown"
        assert isinstance(op["new_value"], str)


# ══════════════════════════════════════════════════════════════════════════════
# Planner type-aware matching tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPlannerTypedMatching:

    def _make_mixed_df(self):
        """DataFrame with both int 0 and str '0' in the same column (object dtype)."""
        return pd.DataFrame({"value": [0, 1, "0", "1"]})

    def _make_numeric_df(self):
        return pd.DataFrame({"value": [0, 10, 20]})

    def _make_string_df(self):
        return pd.DataFrame({"value": ["0", "10", "20"]})

    def _run_plan(self, df, old_val, new_val):
        from transformation.planner import transformation_planner
        op = {"type": "REPLACE_VALUES", "old_value": old_val, "new_value": new_val}
        return transformation_planner.plan(df, op, "test_ds")

    def test_replace_int_0_only_matches_int_cells(self):
        """replace int(0) with 'unknown' → only int 0 changes, str '0' unaffected."""
        df = self._make_mixed_df()
        plan = self._run_plan(df, 0, "unknown")
        # Should find exactly 1 affected cell (the int 0)
        assert plan.affected_cells_count == 1
        before_vals = [c.before for c in plan.before_sample]
        # The before value should be 0 (int), not '0' (str)
        assert 0 in before_vals

    def test_replace_str_0_only_matches_str_cells(self):
        """replace str('0') with 'unknown' → only str '0' changes, int 0 unaffected."""
        df = self._make_mixed_df()
        plan = self._run_plan(df, "0", "unknown")
        assert plan.affected_cells_count == 1
        before_vals = [c.before for c in plan.before_sample]
        assert "0" in before_vals

    def test_replace_numeric_in_numeric_column(self):
        """replace int(0) in pure int column."""
        df = self._make_numeric_df()
        plan = self._run_plan(df, 0, 5)
        assert plan.affected_cells_count == 1
        assert len(plan.warnings) == 0

    def test_replace_not_found_gives_clear_type_message(self):
        """replace int(0) in string column → warning explains type mismatch."""
        df = self._make_string_df()
        plan = self._run_plan(df, 0, "unknown")  # int 0 vs str '0' → not found
        assert plan.affected_cells_count == 0
        assert len(plan.warnings) > 0
        warning_text = plan.warnings[0]
        assert "int" in warning_text or "integer" in warning_text or "str" in warning_text

    def test_integer_literal_matches_float_column_values(self):
        df = pd.DataFrame({"value": [0.0, 1.0, 0.5]})
        plan = self._run_plan(df, 0, "unknown")
        assert plan.affected_cells_count == 1
        assert plan.before_sample[0].before == 0.0

    def test_numpy_numeric_scalars_match_without_bool_or_precision_coercion(self):
        integer = parse_literal("9007199254740993")
        assert semantic_equals(np.int64(9007199254740993), integer)
        assert not semantic_equals(np.float64(9007199254740992), integer)
        assert semantic_equals(np.float64(0.0), parse_literal("0"))
        assert not semantic_equals(np.bool_(True), parse_literal("1"))

    def test_numeric_literal_never_matches_numeric_looking_strings(self):
        series = pd.Series([0, 0.0, "0", "0.0", True, False], dtype=object)
        mask = build_mask(series, parse_literal("0"))
        assert mask.tolist() == [True, True, False, False, False, False]

    def test_string_literal_never_matches_boolean_cells(self):
        series = pd.Series([True, False, "True", "False"], dtype=object)
        mask = build_mask(series, parse_literal("true", was_quoted=True))
        assert mask.tolist() == [False, False, False, False]
        assert not semantic_equals(True, parse_literal("true", was_quoted=True))

    def test_boolean_literal_never_matches_numeric_cells_or_string_cells(self):
        series = pd.Series([1, 0, True, False, "true", "false"], dtype=object)
        true_mask = build_mask(series, parse_literal("true"))
        false_mask = build_mask(series, parse_literal("false"))
        assert true_mask.tolist() == [False, False, True, False, False, False]
        assert false_mask.tolist() == [False, False, False, True, False, False]

    def test_null_semantics_distinguish_null_from_string_tokens(self):
        series = pd.Series([None, np.nan, pd.NA, "NaN", "null", 0], dtype=object)
        mask = build_mask(series, parse_literal("null"))
        assert mask.tolist() == [True, True, True, False, False, False]


# ══════════════════════════════════════════════════════════════════════════════
# Executor type-preservation tests
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutorTypedReplace:

    def _exec_replace(self, df, old_val, new_val):
        """Run REPLACE_VALUES directly through the executor _execute method."""
        from transformation.planner import transformation_planner
        from transformation.executor import transformation_executor
        op = {"type": "REPLACE_VALUES", "old_value": old_val, "new_value": new_val}
        plan = transformation_planner.plan(df, op, "test_ds")
        return transformation_executor._execute(df.copy(), plan)

    def test_1_replace_int_0_with_unknown_leaves_str_0(self):
        """TEST 1: int 0 → unknown. str '0' untouched."""
        df = pd.DataFrame({"value": [0, 1, "0", "1"]})
        result = self._exec_replace(df, 0, "unknown")
        vals = result["value"].tolist()
        assert vals[0] == "unknown"   # int 0 replaced
        assert vals[1] == 1           # int 1 unchanged
        assert vals[2] == "0"         # str '0' unchanged
        assert vals[3] == "1"         # str '1' unchanged

    def test_2_replace_str_0_with_unknown_leaves_int_0(self):
        """TEST 2: str '0' → unknown. int 0 untouched."""
        df = pd.DataFrame({"value": [0, 1, "0", "1"]})
        result = self._exec_replace(df, "0", "unknown")
        vals = result["value"].tolist()
        assert vals[0] == 0           # int 0 unchanged
        assert vals[1] == 1           # int 1 unchanged
        assert vals[2] == "unknown"   # str '0' replaced
        assert vals[3] == "1"         # str '1' unchanged

    def test_3_replace_int_with_int_stays_numeric(self):
        """TEST 3: replace int(0) with int(5). Both numeric."""
        df = pd.DataFrame({"value": [0, 10, 20]})
        result = self._exec_replace(df, 0, 5)
        vals = result["value"].tolist()
        assert vals[0] == 5
        assert isinstance(vals[0], int) or isinstance(vals[0], (int, np.integer))
        assert vals[1] == 10
        assert vals[2] == 20

    def test_4_replace_int_0_leaves_str_0(self):
        """TEST 4: mixed column, int 0 replaced, str '0' untouched."""
        df = pd.DataFrame({"value": [0, "0"]})
        result = self._exec_replace(df, 0, "unknown")
        vals = result["value"].tolist()
        assert vals[0] == "unknown"
        assert vals[1] == "0"

    def test_5_fill_missing_then_replace_numeric_zero(self):
        """
        TEST 5 + 6 combined:
        Fill NaN with 0 → NaN becomes numeric 0.
        Then replace numeric 0 → str 'unknown'.
        str '0' must remain untouched throughout.
        """
        from transformation.planner import transformation_planner
        from transformation.executor import transformation_executor

        df = pd.DataFrame({"value": [np.nan, 0, "0"]})

        # Step 1: fill missing with 0
        fill_op = {"type": "FILL_MISSING", "value": 0}
        fill_plan = transformation_planner.plan(df, fill_op, "test_ds")
        df_filled = transformation_executor._execute(df.copy(), fill_plan)

        # NaN → 0 (numeric), literal 0 stays 0, str '0' stays '0'
        filled_vals = df_filled["value"].tolist()
        assert filled_vals[2] == "0"    # str '0' untouched

        # Step 2: replace numeric 0 with 'unknown'
        replace_op = {"type": "REPLACE_VALUES", "old_value": 0, "new_value": "unknown"}
        replace_plan = transformation_planner.plan(df_filled, replace_op, "test_ds")
        df_replaced = transformation_executor._execute(df_filled.copy(), replace_plan)

        final_vals = df_replaced["value"].tolist()
        assert final_vals[0] == "unknown"  # was NaN → 0 → unknown
        assert final_vals[1] == "unknown"  # was 0 → unknown
        assert final_vals[2] == "0"         # str '0' untouched throughout

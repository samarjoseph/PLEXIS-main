"""
Tests for Extreme-Value Transformation Intent, Validation, and Postcondition Verification.

Verifies:
- Distinguishing extreme-value operations (capping, flooring, extremum modification) from literal string replacement.
- Ambiguity detection & structured clarification for comparative requests ("change highest X to Y").
- Direct planning without clarification when unambiguous ("cap at 60", "change only the highest to 60").
- Rejection of aggregation/comparative operators as literal replacement values in numeric columns.
- Exact affected cells calculation (never indeterminate / '?').
- Handling of tied maxima/minima.
- Postcondition verification in TransformationExecutor.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
import numpy as np

from transformation.planner import transformation_planner, TransformationClarificationRequired
from transformation.validator import ir_validator
from transformation.ir import TransformationIR, TransformStep
from transformation.executor import transformation_executor
from router.master_router import _parse_transform_from_message


@pytest.fixture
def sample_flights_df():
    return pd.DataFrame({
        'Flight_ID': [101, 102, 103, 104, 105],
        'Airline': ['IndiGo', 'Air India', 'SpiceJet', 'IndiGo', 'Air India'],
        'Departure_Delay': [15, 45, 119, 85, 0],
        'Status': ['On Time', 'Delayed', 'Delayed', 'Delayed', 'On Time'],
    })


@pytest.fixture
def tied_extremum_df():
    return pd.DataFrame({
        'ID': [1, 2, 3, 4],
        'Score': [10, 50, 50, 30],
        'Category': ['A', 'B', 'B', 'C']
    })


@pytest.fixture
def string_column_df():
    return pd.DataFrame({
        'ID': [1, 2, 3],
        'Setting': ['min', 'normal', 'max']
    })


# ── 1. Ambiguity Detection & Clarification ──────────────────────────────────────

def test_ambiguous_highest_change_triggers_clarification(sample_flights_df):
    """User request 'change the highest departure delay to 60' is ambiguous and must ask for clarification."""
    parsed = _parse_transform_from_message("change the highest departure delay to 60")
    assert parsed is not None
    assert parsed['type'] == 'EXTREME_VALUE_AMBIGUITY'
    assert parsed['column'] == 'departure delay'
    assert parsed['extremum'] == 'max'
    assert parsed['target_value'] == 60

    # Planner must raise TransformationClarificationRequired
    with pytest.raises(TransformationClarificationRequired) as exc_info:
        transformation_planner.plan(sample_flights_df, parsed, 'ds_flight_1')

    err = exc_info.value
    assert err.clarification_type == 'EXTREME_VALUE_AMBIGUITY'
    assert err.candidate_columns == ['Departure_Delay']
    assert len(err.ambiguous_options) == 2

    # Option 1: Cap all values above 60 at 60
    assert err.ambiguous_options[0]['action'] == 'CAP_UPPER'
    assert 'Cap all values above 60' in err.ambiguous_options[0]['label']
    assert err.ambiguous_options[0]['operation']['type'] == 'CLIP'
    assert err.ambiguous_options[0]['operation']['max'] == 60

    # Option 2: Change only the current maximum (119) to 60
    assert err.ambiguous_options[1]['action'] == 'UPDATE_EXTREMUM'
    assert '119' in err.ambiguous_options[1]['label']
    assert err.ambiguous_options[1]['operation']['type'] == 'UPDATE_EXTREMUM'
    assert err.ambiguous_options[1]['operation']['new_value'] == 60


def test_ambiguous_lowest_change_triggers_clarification(sample_flights_df):
    """User request 'change the lowest departure delay to 5' is ambiguous and must ask for clarification."""
    parsed = _parse_transform_from_message("change the lowest departure delay to 5")
    assert parsed is not None
    assert parsed['type'] == 'EXTREME_VALUE_AMBIGUITY'
    assert parsed['extremum'] == 'min'
    assert parsed['target_value'] == 5

    with pytest.raises(TransformationClarificationRequired) as exc_info:
        transformation_planner.plan(sample_flights_df, parsed, 'ds_flight_1')

    err = exc_info.value
    assert err.clarification_type == 'EXTREME_VALUE_AMBIGUITY'
    assert len(err.ambiguous_options) == 2
    assert err.ambiguous_options[0]['action'] == 'FLOOR_LOWER'
    assert 'Floor all values below 5' in err.ambiguous_options[0]['label']
    assert err.ambiguous_options[1]['action'] == 'UPDATE_EXTREMUM'
    assert '0' in err.ambiguous_options[1]['label']


# ── 2. Unambiguous Operations (No Clarification Required) ──────────────────────

def test_unambiguous_cap_operation(sample_flights_df):
    """User request 'cap departure delay at 60' directly plans CLIP without clarification."""
    parsed = _parse_transform_from_message("cap departure delay at 60")
    assert parsed == {"type": "CLIP", "column": "departure delay", "max": 60}

    plan = transformation_planner.plan(sample_flights_df, parsed, 'ds_flight_1')
    assert plan.operation_type == 'CLIP'
    assert plan.operation_label == "Cap 'Departure_Delay' at 60"
    # Values above 60: 119 and 85 -> 2 affected cells
    assert plan.affected_cells_count == 2
    assert plan.affected_rows_count == 2
    assert plan.affected_columns == ['Departure_Delay']
    assert len(plan.before_sample) == 2
    assert plan.before_sample[0].before == 119
    assert plan.before_sample[0].after == 60
    assert plan.before_sample[1].before == 85
    assert plan.before_sample[1].after == 60


def test_unambiguous_floor_operation(sample_flights_df):
    """User request 'floor departure delay at 10' directly plans CLIP (min=10)."""
    parsed = _parse_transform_from_message("floor departure delay at 10")
    assert parsed == {"type": "CLIP", "column": "departure delay", "min": 10}

    plan = transformation_planner.plan(sample_flights_df, parsed, 'ds_flight_1')
    assert plan.operation_type == 'CLIP'
    assert plan.operation_label == "Floor 'Departure_Delay' at 10"
    # Values below 10: 0 -> 1 affected cell
    assert plan.affected_cells_count == 1
    assert plan.before_sample[0].before == 0
    assert plan.before_sample[0].after == 10


def test_unambiguous_set_maximum(sample_flights_df):
    """User request 'set the maximum departure delay to 60' plans CLIP (max=60)."""
    parsed = _parse_transform_from_message("set the maximum departure delay to 60")
    assert parsed == {"type": "CLIP", "column": "departure delay", "max": 60}

    plan = transformation_planner.plan(sample_flights_df, parsed, 'ds_flight_1')
    assert plan.operation_type == 'CLIP'
    assert plan.affected_cells_count == 2


def test_unambiguous_update_extremum_only(sample_flights_df):
    """User request 'change only the highest departure delay to 60' plans UPDATE_EXTREMUM."""
    parsed = _parse_transform_from_message("change only the highest departure delay to 60")
    assert parsed == {
        "type": "UPDATE_EXTREMUM",
        "column": "departure delay",
        "extremum": "max",
        "new_value": 60
    }

    plan = transformation_planner.plan(sample_flights_df, parsed, 'ds_flight_1')
    assert plan.operation_type == 'UPDATE_EXTREMUM'
    assert "Change maximum value (119) to 60 in 'Departure_Delay'" in plan.operation_label
    # Only single maximal row (119) is affected
    assert plan.affected_cells_count == 1
    assert plan.affected_rows_count == 1
    assert plan.before_sample[0].before == 119
    assert plan.before_sample[0].after == 60


# ── 3. Tied Maxima & Minima ───────────────────────────────────────────────────

def test_tied_maxima_update_all_tied_rows(tied_extremum_df):
    """If multiple rows share the maximum value, UPDATE_EXTREMUM updates all tied rows deterministically."""
    op = {
        "type": "UPDATE_EXTREMUM",
        "column": "Score",
        "extremum": "max",
        "new_value": 45
    }
    plan = transformation_planner.plan(tied_extremum_df, op, 'ds_tied')
    assert plan.operation_type == 'UPDATE_EXTREMUM'
    # Two rows have Score == 50
    assert plan.affected_cells_count == 2
    assert plan.affected_rows_count == 2
    assert plan.before_sample[0].before == 50
    assert plan.before_sample[0].after == 45
    assert plan.before_sample[1].before == 50
    assert plan.before_sample[1].after == 45


# ── 4. Rejection of Invalid Aggregation Operands ──────────────────────────────

def test_reject_unquoted_max_as_literal_replacement(sample_flights_df):
    """REPLACE_VALUES with old_value='max' on numeric column MUST be rejected by planner & validator."""
    # When unquoted, parser rejects it from REPLACE_VALUES
    parsed = _parse_transform_from_message("replace max with 60")
    assert parsed is None

    # Even if LLM sends raw REPLACE_VALUES with 'max'
    invalid_op = {
        "type": "REPLACE_VALUES",
        "column": "Departure_Delay",
        "old_value": "max",
        "new_value": 60,
        "_old_was_quoted": False
    }

    with pytest.raises(ValueError) as exc_info:
        transformation_planner.plan(sample_flights_df, invalid_op, 'ds_flight_1')
    assert "Cannot use aggregation/comparative term" in str(exc_info.value) or "Cannot replace string" in str(exc_info.value)

    # IR validator also rejects it
    ir = TransformationIR(
        goal="replace max",
        steps=[
            TransformStep(
                id="step_1",
                operation="REPLACE",
                params={"column": "Departure_Delay", "old_value": "max", "new_value": 60, "_old_was_quoted": False}
            )
        ]
    )
    v_res = ir_validator.validate(ir, sample_flights_df)
    assert not v_res.valid
    assert any("aggregation or comparative keyword" in err for err in v_res.errors)


def test_reject_string_replacement_in_numeric_column(sample_flights_df):
    """Replacing literal string 'delay' in numeric Departure_Delay is rejected with type mismatch error."""
    invalid_op = {
        "type": "REPLACE_VALUES",
        "column": "Departure_Delay",
        "old_value": "unknown",
        "new_value": 0,
        "_old_was_quoted": False
    }
    with pytest.raises(ValueError) as exc_info:
        transformation_planner.plan(sample_flights_df, invalid_op, 'ds_flight_1')
    assert "Cannot replace string" in str(exc_info.value) or "not found" in str(exc_info.value)


def test_allow_quoted_literal_replacement_on_string_column(string_column_df):
    """Quoted replacement of 'max' on string column is valid."""
    parsed = _parse_transform_from_message("replace the string 'max' with 'peak'")
    assert parsed is not None
    assert parsed['type'] == 'REPLACE_VALUES'
    assert parsed['old_value'] == 'max'
    assert parsed['_old_was_quoted'] is True

    plan = transformation_planner.plan(string_column_df, parsed, 'ds_string')
    assert plan.operation_type == 'REPLACE_VALUES'
    assert plan.affected_cells_count == 1
    assert plan.before_sample[0].before == 'max'
    assert plan.before_sample[0].after == 'peak'


# ── 5. Column Validation ─────────────────────────────────────────────────────

def test_reject_nonexistent_column(sample_flights_df):
    """CLIP or UPDATE_EXTREMUM on non-existent column raises clear ValueError."""
    op_clip = {"type": "CLIP", "column": "NonExistentCol", "max": 60}
    with pytest.raises(ValueError) as exc_clip:
        transformation_planner.plan(sample_flights_df, op_clip, 'ds_flight_1')
    assert "not found in dataset" in str(exc_clip.value)

    op_ext = {"type": "UPDATE_EXTREMUM", "column": "NonExistentCol", "extremum": "max", "new_value": 60}
    with pytest.raises(ValueError) as exc_ext:
        transformation_planner.plan(sample_flights_df, op_ext, 'ds_flight_1')
    assert "not found in dataset" in str(exc_ext.value)


# ── 6. Deterministic Execution & Postcondition Verification ───────────────────

def test_execute_clip_and_verify_postconditions(sample_flights_df):
    """Executing CLIP must cap values and verify postcondition (max <= 60)."""
    op = {"type": "CLIP", "column": "Departure_Delay", "max": 60}
    plan = transformation_planner.plan(sample_flights_df, op, 'ds_flight_1')

    result = transformation_executor.apply(plan, sample_flights_df, 'ds_flight_1', db=None)
    assert result.success is True
    assert result.changed_cells == 2

    # Verify execution outcome on DataFrame
    new_df = transformation_executor._execute(sample_flights_df.copy(), plan)
    assert new_df['Departure_Delay'].max() == 60
    assert list(new_df['Departure_Delay']) == [15, 45, 60, 60, 0]


def test_execute_update_extremum_and_verify_postconditions(sample_flights_df):
    """Executing UPDATE_EXTREMUM changes only 119 -> 60, leaving 85 intact."""
    op = {
        "type": "UPDATE_EXTREMUM",
        "column": "Departure_Delay",
        "extremum": "max",
        "new_value": 60
    }
    plan = transformation_planner.plan(sample_flights_df, op, 'ds_flight_1')

    result = transformation_executor.apply(plan, sample_flights_df, 'ds_flight_1', db=None)
    assert result.success is True
    assert result.changed_cells == 1

    new_df = transformation_executor._execute(sample_flights_df.copy(), plan)
    # 119 was replaced with 60; 85 is now the new maximum
    assert new_df['Departure_Delay'].max() == 85
    assert list(new_df['Departure_Delay']) == [15, 45, 60, 85, 0]


def test_execute_tied_maxima(tied_extremum_df):
    """Executing UPDATE_EXTREMUM on tied maxima updates both rows."""
    op = {
        "type": "UPDATE_EXTREMUM",
        "column": "Score",
        "extremum": "max",
        "new_value": 45
    }
    plan = transformation_planner.plan(tied_extremum_df, op, 'ds_tied')
    result = transformation_executor.apply(plan, tied_extremum_df, 'ds_tied', db=None)
    assert result.success is True
    assert result.changed_cells == 2

    new_df = transformation_executor._execute(tied_extremum_df.copy(), plan)
    assert list(new_df['Score']) == [10, 45, 45, 30]
    assert new_df['Score'].max() == 45


# ── 6. Normalization & IR Planner Resilience ──────────────────────────────────

def test_normalize_transform_operation_preserves_extreme_primitives():
    """Verify _normalize_transform_operation does NOT overwrite extreme primitives with IR_REQUIRED."""
    from router.master_router import _normalize_transform_operation

    # 1. EXTREME_VALUE_AMBIGUITY
    op1 = {
        "type": "EXTREME_VALUE_AMBIGUITY",
        "column": "Departure_Delay",
        "extremum": "max",
        "target_value": 60,
        "_missing_slots": ["clarify_extreme_intent"]
    }
    norm1 = _normalize_transform_operation(op1.copy())
    assert norm1['type'] == 'EXTREME_VALUE_AMBIGUITY'
    assert norm1['column'] == 'Departure_Delay'
    assert norm1['target_value'] == 60
    assert norm1['_missing_slots'] == ['clarify_extreme_intent']

    # 2. CLIP
    op2 = {
        "type": "CLIP",
        "column": "Departure_Delay",
        "upper": 60
    }
    norm2 = _normalize_transform_operation(op2.copy())
    assert norm2['type'] == 'CLIP'
    assert norm2['max'] == 60

    # 3. UPDATE_EXTREMUM
    op3 = {
        "type": "UPDATE_EXTREMUM",
        "columns": ["Departure_Delay"],
        "extremum": "MAX",
        "value": 60
    }
    norm3 = _normalize_transform_operation(op3.copy())
    assert norm3['type'] == 'UPDATE_EXTREMUM'
    assert norm3['column'] == 'Departure_Delay'
    assert norm3['extremum'] == 'max'
    assert norm3['new_value'] == 60


def test_ir_planner_parse_response_empty_error():
    """Empty or whitespace provider response raises a clear descriptive ValueError, not JSONDecodeError."""
    from transformation.ir_planner import ir_planner

    with pytest.raises(ValueError) as exc:
        ir_planner._parse_response("")
    assert "empty response" in str(exc.value).lower()

    with pytest.raises(ValueError) as exc:
        ir_planner._parse_response("   \n\t  ")
    assert "empty response" in str(exc.value).lower()


def test_ir_planner_parse_response_markdown_code_fences():
    """IR planner parses JSON wrapped in markdown code fences with surrounding commentary."""
    from transformation.ir_planner import ir_planner

    raw = """Here is the planned transformation:
```json
{
  "goal": "Clip departure delays",
  "steps": [
    {
      "id": 1,
      "primitive": "CLIP",
      "params": {"column": "Departure_Delay", "max": 60}
    }
  ]
}
```
Let me know if you need any adjustments."""
    parsed = ir_planner._parse_response(raw)
    assert parsed['goal'] == "Clip departure delays"
    assert len(parsed['steps']) == 1
    assert parsed['steps'][0]['primitive'] == 'CLIP'


def test_ir_planner_parse_response_embedded_json():
    """IR planner extracts JSON objects surrounded by arbitrary text without code fences."""
    from transformation.ir_planner import ir_planner

    raw = """The requested operation plan is:
{"goal": "Update maximum delay", "steps": [{"id": 1, "primitive": "UPDATE_EXTREMUM", "params": {"column": "Departure_Delay", "new_value": 60}}]}
Hope this helps!"""
    parsed = ir_planner._parse_response(raw)
    assert parsed['goal'] == "Update maximum delay"
    assert len(parsed['steps']) == 1
    assert parsed['steps'][0]['primitive'] == 'UPDATE_EXTREMUM'


def test_ir_planner_parse_response_truncated_recovery():
    """IR planner recovers truncated JSON by closing brackets."""
    from transformation.ir_planner import ir_planner

    raw = '{"goal": "Test truncation", "steps": [{"id": 1, "primitive": "DROP_DUPLICATES"'
    parsed = ir_planner._parse_response(raw)
    assert parsed['goal'] == "Test truncation"
    assert len(parsed['steps']) == 1


# ── 7. Full Request Dispatch & Clarification Integration ─────────────────────

def test_full_request_dispatch_extreme_ambiguity_clarification(sample_flights_df, monkeypatch):
    """Submitting 'change the highest departure delay to 60' produces clarification without IR_REQUIRED or LLM crashes."""
    from unittest.mock import MagicMock
    from core.context import ExecutionContext
    from router.master_router import MasterRouter
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    from datasets.registry import dataset_registry

    entry = MagicMock()
    entry.dataframe = sample_flights_df
    entry.row_count = len(sample_flights_df)
    entry.column_count = len(sample_flights_df.columns)
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)

    router = MasterRouter()
    engine = TransformEngine()

    dataset_id = 'ds_flight_test_live'
    ctx = ExecutionContext(
        message="change the highest departure delay to 60",
        dataset_id=dataset_id,
        chat_id="chat_test_123"
    )

    # Fast-path interpretation inside route()
    from router.master_router import _parse_transform_from_message
    parsed_op = _parse_transform_from_message(ctx.message)
    assert parsed_op['type'] == 'EXTREME_VALUE_AMBIGUITY'

    # Normalization inside route() must keep EXTREME_VALUE_AMBIGUITY
    from router.master_router import _normalize_transform_operation
    norm_op = _normalize_transform_operation(parsed_op.copy())
    assert norm_op['type'] == 'EXTREME_VALUE_AMBIGUITY'
    assert norm_op['type'] != 'IR_REQUIRED'

    # TransformEngine handling produces clarification
    ctx.llm_operation = norm_op
    res = engine.handle(ctx)

    assert res.success is True
    assert 'clarification' in res.metadata
    clarif = res.metadata['clarification']
    assert clarif['clarification_type'] == 'EXTREME_VALUE_AMBIGUITY'
    assert clarif['status'] == 'AWAITING_CLARIFICATION'
    assert len(clarif['ambiguous_options']) == 2

    # Verify Option 1: Cap all values above 60 at 60
    opt1 = clarif['ambiguous_options'][0]
    assert opt1['action'] == 'CAP_UPPER'
    assert opt1['operation']['type'] == 'CLIP'
    assert opt1['operation']['max'] == 60

    # Verify Option 2: Change only the current maximum (119) to 60
    opt2 = clarif['ambiguous_options'][1]
    assert opt2['action'] == 'UPDATE_EXTREMUM'
    assert opt2['operation']['type'] == 'UPDATE_EXTREMUM'
    assert opt2['operation']['new_value'] == 60
    assert '119' in opt2['label']

    # Now verify follow-up: User selects Option 1 (Cap)
    pending_id = clarif['transformation_id']
    ctx_followup1 = ExecutionContext(
        message="I meant: Cap all values above 60 at 60",
        dataset_id=dataset_id,
        chat_id="chat_test_123",
        workspace_action={
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'EXTREME_VALUE_AMBIGUITY',
            'transformation_id': pending_id,
            'value': 'CAP_UPPER',
            'action': 'CAP_UPPER',
            'chosen_operation': opt1['operation']
        }
    )
    # Router handles follow-up
    route_res1 = router._pending_transform_fast_path(ctx_followup1)
    assert route_res1['intent'] == 'TRANSFORM'
    assert route_res1['operation']['type'] == 'CLIP'

    # Plan generation for chosen operation
    ctx_followup1.llm_operation = route_res1['operation']
    exec_res1 = engine.handle(ctx_followup1)
    assert exec_res1.success is True
    plan1 = exec_res1.metadata['transform_plan']
    assert plan1['operation_type'] == 'CLIP'
    assert plan1['affected_cells_count'] == 2  # 119 and 85


def test_followup_clarification_choice_update_extremum(sample_flights_df, monkeypatch):
    """User selects Option 2 (Update Extremum) -> produces UPDATE_EXTREMUM plan changing only 119 -> 60."""
    from unittest.mock import MagicMock
    from core.context import ExecutionContext
    from router.master_router import MasterRouter, _parse_transform_from_message, _normalize_transform_operation
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    from datasets.registry import dataset_registry

    entry = MagicMock()
    entry.dataframe = sample_flights_df
    entry.row_count = len(sample_flights_df)
    entry.column_count = len(sample_flights_df.columns)
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)

    router = MasterRouter()
    engine = TransformEngine()

    dataset_id = 'ds_flight_test_live_2'
    ctx = ExecutionContext(
        message="change the highest departure delay to 60",
        dataset_id=dataset_id,
        chat_id="chat_test_opt2"
    )

    parsed_op = _parse_transform_from_message(ctx.message)
    norm_op = _normalize_transform_operation(parsed_op.copy())
    ctx.llm_operation = norm_op
    res = engine.handle(ctx)
    clarif = res.metadata['clarification']
    pending_id = clarif['transformation_id']
    opt2 = clarif['ambiguous_options'][1]

    # Follow up with Option 2
    ctx_followup2 = ExecutionContext(
        message="I meant: Change only the maximum record(s) (119) to 60",
        dataset_id=dataset_id,
        chat_id="chat_test_opt2",
        workspace_action={
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'EXTREME_VALUE_AMBIGUITY',
            'transformation_id': pending_id,
            'value': 'UPDATE_EXTREMUM',
            'action': 'UPDATE_EXTREMUM',
            'chosen_operation': opt2['operation']
        }
    )
    route_res2 = router._pending_transform_fast_path(ctx_followup2)
    assert route_res2['intent'] == 'TRANSFORM'
    assert route_res2['operation']['type'] == 'UPDATE_EXTREMUM'

    ctx_followup2.llm_operation = route_res2['operation']
    exec_res2 = engine.handle(ctx_followup2)
    assert exec_res2.success is True
    plan2 = exec_res2.metadata['transform_plan']
    assert plan2['operation_type'] == 'UPDATE_EXTREMUM'
    assert plan2['affected_cells_count'] == 1  # Only 119
    assert str(plan2['before_sample'][0]['before']) == '119'
    assert str(plan2['before_sample'][0]['after']) == '60'


def test_followup_clarification_natural_language_text(sample_flights_df, monkeypatch):
    """User replies to clarification with text 'only the maximum' -> produces UPDATE_EXTREMUM."""
    from unittest.mock import MagicMock
    from core.context import ExecutionContext
    from router.master_router import MasterRouter, _parse_transform_from_message, _normalize_transform_operation
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    from datasets.registry import dataset_registry

    entry = MagicMock()
    entry.dataframe = sample_flights_df
    entry.row_count = len(sample_flights_df)
    entry.column_count = len(sample_flights_df.columns)
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)

    router = MasterRouter()
    engine = TransformEngine()

    dataset_id = 'ds_flight_test_live_nl'
    ctx = ExecutionContext(
        message="change the highest departure delay to 60",
        dataset_id=dataset_id,
        chat_id="chat_test_nl"
    )

    parsed_op = _parse_transform_from_message(ctx.message)
    norm_op = _normalize_transform_operation(parsed_op.copy())
    ctx.llm_operation = norm_op
    res = engine.handle(ctx)
    clarif = res.metadata['clarification']

    # User replies with natural text "only the maximum record"
    ctx_nl = ExecutionContext(
        message="only the maximum record",
        dataset_id=dataset_id,
        chat_id="chat_test_nl"
    )
    route_res = router._pending_transform_fast_path(ctx_nl)
    assert route_res['intent'] == 'TRANSFORM'
    assert route_res['operation']['type'] == 'UPDATE_EXTREMUM'
    assert route_res['operation']['new_value'] == 60


def test_turn1_session_id_turn2_chat_id_transformation_id_lookup(sample_flights_df, monkeypatch):
    """Pending created under session_id must be found when turn 2 passes a new chat_id and transformation_id."""
    from unittest.mock import MagicMock
    from core.context import ExecutionContext
    from router.master_router import MasterRouter, _parse_transform_from_message, _normalize_transform_operation
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    from datasets.registry import dataset_registry

    entry = MagicMock()
    entry.dataframe = sample_flights_df
    entry.row_count = len(sample_flights_df)
    entry.column_count = len(sample_flights_df.columns)
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)

    router = MasterRouter()
    engine = TransformEngine()

    dataset_id = 'ds_flight_test_live_session_mismatch'
    
    # Turn 1: chat_id is None, session_id is frontend session UUID
    ctx_turn1 = ExecutionContext(
        message="change the highest departure delay to 60",
        dataset_id=dataset_id,
        session_id="session_front_12345",
        chat_id=None
    )

    parsed_op = _parse_transform_from_message(ctx_turn1.message)
    norm_op = _normalize_transform_operation(parsed_op.copy())
    ctx_turn1.llm_operation = norm_op
    res1 = engine.handle(ctx_turn1)
    clarif = res1.metadata['clarification']
    pending_id = clarif['transformation_id']
    opt2 = clarif['ambiguous_options'][1]

    # Turn 2: chat_id is now a DB UUID, but transformation_id matches
    ctx_turn2 = ExecutionContext(
        message="I meant: Change only the maximum record(s) (119) to 60",
        dataset_id=dataset_id,
        session_id="session_front_12345",
        chat_id="chat_db_uuid_99999",
        workspace_action={
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'EXTREME_VALUE_AMBIGUITY',
            'transformation_id': pending_id,
            'value': 'UPDATE_EXTREMUM',
            'action': 'UPDATE_EXTREMUM',
            'chosen_operation': opt2['operation']
        }
    )

    route_res = router._pending_transform_fast_path(ctx_turn2)
    assert route_res is not None
    assert route_res['intent'] == 'TRANSFORM'
    assert route_res['operation']['type'] == 'UPDATE_EXTREMUM'
    assert route_res['operation']['column'] == 'Departure_Delay'
    assert route_res['operation']['new_value'] == 60

    # Execute plan without 'Column None' error
    ctx_turn2.llm_operation = route_res['operation']
    exec_res = engine.handle(ctx_turn2)
    assert exec_res.success is True
    plan = exec_res.metadata['transform_plan']
    assert plan['operation_type'] == 'UPDATE_EXTREMUM'
    assert plan['affected_cells_count'] == 1
    assert str(plan['before_sample'][0]['before']) == '119'
    assert str(plan['before_sample'][0]['after']) == '60'



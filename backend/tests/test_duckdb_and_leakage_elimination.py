"""
Tests for DuckDB Transformation Execution and Strict Zero-Process-Leakage.
"""
import os
import sys
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.text_sanitizer import strip_thinking_and_internal_reasoning
from transformation.contracts import TransformationPlan
from transformation.executor import TransformationExecutor
from transformation.planner import _compute_fingerprint
from transformation.store import transformation_store, PendingTransformationContext
from datasets.registry import dataset_registry, DatasetEntry
from router.master_router import MasterRouter
from core.context import ExecutionContext


def _make_dataset_entry(dataset_id: str, df: pd.DataFrame) -> DatasetEntry:
    return DatasetEntry(
        dataset_id=dataset_id,
        filename='test.csv',
        file_path='',
        upload_timestamp='',
        row_count=len(df),
        column_count=len(df.columns),
        file_fingerprint='',
        schema_fingerprint='',
        dataframe=df,
        profile={},
        schema_profile=[],
        column_profiles={},
    )


def test_strict_zero_leakage_cot():
    """Verify that chain-of-thought and prompt leakage are completely stripped."""
    raw = """Here's a thinking process:
1.  **Analyze User Input:**
    *   User says: "i meant change only the maximum records 119 to 60"
    *   Context: The system note says "CURRENT INTENT: conversation", "DATASET LOADED: india_flight_delay_model_input.csv", and the last assistant message offered options:
        1. Cap values at 60 (values > 60 become 60)
        2. Change only the maximum record(s) (119) to 60
    *   The user is clearly selecting option 2 from the previous clarification.
2.  **Determine Action:**
    *   Explain the transformation plan.

I have prepared the plan to update the maximum departure delay records from 119 to 60."""

    cleaned = strip_thinking_and_internal_reasoning(raw)
    assert "thinking process" not in cleaned.lower()
    assert "system note" not in cleaned.lower()
    assert "Analyze User Input" not in cleaned
    assert "CURRENT INTENT" not in cleaned
    assert "I have prepared the plan to update the maximum departure delay records from 119 to 60." in cleaned


def test_duckdb_update_extremum_execution():
    """Verify DuckDB executes UPDATE_EXTREMUM correctly and vectorially."""
    n = 1000
    df = pd.DataFrame({
        'flight_id': np.arange(n),
        'delay': np.random.randint(0, 100, size=n),
    })
    df.loc[10, 'delay'] = 250
    df.loc[20, 'delay'] = 250

    dataset_registry.register(_make_dataset_entry('ds_duck_test', df.copy()))

    fp = _compute_fingerprint(df)
    plan = TransformationPlan(
        plan_id='p_duck_1',
        dataset_id='ds_duck_test',
        operation_type='UPDATE_EXTREMUM',
        operation_label="Change maximum value (250) to 60 in 'delay'",
        operation_code="",
        operation_payload={
            'type': 'UPDATE_EXTREMUM',
            'column': 'delay',
            'extremum': 'max',
            'current_extremum': 250,
            'new_value': 60,
        },
        affected_rows_count=2,
        affected_cells_count=2,
        affected_columns=['delay'],
        before_sample=[],
        dataset_fingerprint=fp,
    )

    executor = TransformationExecutor()
    res = executor.apply(plan, df, 'ds_duck_test', db=None)
    assert res.success is True
    assert res.changed_cells == 2

    # Check updated dataframe in memory
    updated_entry = dataset_registry.get('ds_duck_test')
    assert updated_entry is not None
    assert updated_entry.dataframe.loc[10, 'delay'] == 60
    assert updated_entry.dataframe.loc[20, 'delay'] == 60
    assert updated_entry.dataframe['delay'].max() < 250


def test_duckdb_clip_execution():
    """Verify DuckDB executes CLIP correctly."""
    df = pd.DataFrame({
        'val': [10, 20, 150, 200, 5],
    })
    dataset_registry.register(_make_dataset_entry('ds_duck_clip_test', df.copy()))

    fp = _compute_fingerprint(df)
    plan = TransformationPlan(
        plan_id='p_duck_clip',
        dataset_id='ds_duck_clip_test',
        operation_type='CLIP',
        operation_label="Cap values above 100 at 100 in 'val'",
        operation_code="",
        operation_payload={
            'type': 'CLIP',
            'column': 'val',
            'max': 100,
            'min': None,
        },
        affected_rows_count=2,
        affected_cells_count=2,
        affected_columns=['val'],
        before_sample=[],
        dataset_fingerprint=fp,
    )

    executor = TransformationExecutor()
    res = executor.apply(plan, df, 'ds_duck_clip_test', db=None)
    assert res.success is True

    updated_entry = dataset_registry.get('ds_duck_clip_test')
    assert updated_entry.dataframe['val'].max() == 100
    assert list(updated_entry.dataframe['val']) == [10, 20, 100, 100, 5]


def test_pending_dataset_routing_without_session_id_match():
    """Verify router matches pending transformation by dataset_id even when session_id differs."""
    df = pd.DataFrame({'delay': [10, 50, 119]})
    dataset_registry.register(_make_dataset_entry('ds_route_test', df))

    pending = PendingTransformationContext.create(
        transformation_id='tx_route_test_1',
        conversation_id='orig_conv_123',
        dataset_id='ds_route_test',
        dataset_version=1,
        dataset_fingerprint=_compute_fingerprint(df),
        operation_type='EXTREME_VALUE_AMBIGUITY',
        operation_payload={'extremum': 'max', 'target_value': 60, 'column': 'delay'},
        candidate_columns=['delay'],
        missing_slots=['clarify_extreme_intent'],
        original_request='change highest delay to 60',
        latest_question='Do you want to cap or change only max?',
        clarification_type='EXTREME_VALUE_AMBIGUITY',
    )
    transformation_store.set_pending(pending)

    # Turn 2: User responds with different session/chat_id
    router = MasterRouter()
    ctx = ExecutionContext(
        message='i meant change only the maximum records 119 to 60',
        session_id='new_different_session_999',
        chat_id='new_chat_uuid_888',
        dataset_id='ds_route_test',
    )

    route_res = router._pending_transform_fast_path(ctx)
    assert route_res is not None
    assert route_res['intent'] == 'TRANSFORM'
    assert route_res['operation']['type'] == 'UPDATE_EXTREMUM'
    assert route_res['operation']['column'] == 'delay'
    assert route_res['operation']['new_value'] == 60

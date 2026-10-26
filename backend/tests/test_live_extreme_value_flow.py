import pytest
import pandas as pd
import uuid
import time
from datetime import datetime, timezone
from core.context import ExecutionContext
from router.master_router import master_router
from datasets.registry import dataset_registry, DatasetEntry
import api.chat  # registers engines in engine_registry

def test_change_highest_departure_delay_end_to_end():
    # 1. Setup synthetic flight delay data matching schema
    df = pd.DataFrame({
        'Flight_Number': ['AI101', '6E202', 'SG303', 'UK404'],
        'Departure_Delay': [10, 45, 119, 30],
        'Delay_Target': [0, 1, 1, 1],
        'Airline': ['Air India', 'IndiGo', 'SpiceJet', 'Vistara']
    })
    
    dataset_id = str(uuid.uuid4())
    entry = DatasetEntry(
        dataset_id=dataset_id,
        filename='india_flight_delay_model_input.csv',
        file_path='/tmp/india_flight_delay_model_input.csv',
        upload_timestamp=datetime.now(timezone.utc).isoformat(),
        dataframe=df,
        row_count=len(df),
        column_count=len(df.columns),
        file_fingerprint='test_fingerprint_123',
        schema_fingerprint='test_schema_123',
        profile={},
        schema_profile=[
            {'name': 'Flight_Number', 'type': 'text', 'sample_values': ['AI101']},
            {'name': 'Departure_Delay', 'type': 'numeric', 'sample_values': [10, 119]},
            {'name': 'Delay_Target', 'type': 'numeric', 'sample_values': [0, 1]},
            {'name': 'Airline', 'type': 'text', 'sample_values': ['Air India']},
        ],
        column_profiles={},
    )
    dataset_registry.register(entry)

    chat_id = str(uuid.uuid4())

    # Step 1: Initial ambiguous request
    context = ExecutionContext(
        message="change the highest departure delay to 60",
        dataset_id=dataset_id,
        dataset_filename='india_flight_delay_model_input.csv',
        chat_id=chat_id
    )

    t0 = time.time()
    result = master_router.route(context)
    elapsed = time.time() - t0

    # Assertions on ambiguity card
    assert context.intent == "transform", f"Wrong intent: {context.intent}"
    assert result.source == "transform", f"Wrong source: {result.source}"
    assert "import pandas as pd" not in result.answer
    assert "df.to_csv" not in result.answer
    assert "DepDelay" not in result.answer

    meta = result.metadata or {}
    assert "clarification" in meta
    clarif = meta["clarification"]
    assert clarif["clarification_type"] == "EXTREME_VALUE_AMBIGUITY"
    assert clarif["status"] == "AWAITING_CLARIFICATION"
    trans_id = clarif["transformation_id"]

    options = clarif.get("ambiguous_options", [])
    assert len(options) == 2
    actions = [opt["action"] for opt in options]
    assert "CAP_UPPER" in actions
    assert "UPDATE_EXTREMUM" in actions

    # Step 2: Choose Option 1 (CAP_UPPER) via workspace action
    cap_context = ExecutionContext(
        message="I meant: Cap all values above 60 at 60",
        dataset_id=dataset_id,
        dataset_filename='india_flight_delay_model_input.csv',
        chat_id=chat_id,
        workspace_action={
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'EXTREME_VALUE_AMBIGUITY',
            'transformation_id': trans_id,
            'action': 'CAP_UPPER',
            'chosen_operation': {'type': 'CLIP', 'column': 'Departure_Delay', 'max': 60}
        }
    )

    t1 = time.time()
    cap_result = master_router.route(cap_context)
    elapsed_cap = time.time() - t1

    assert cap_context.intent == "transform"
    assert cap_result.source == "transform"
    assert cap_result.success is True
    plan_meta = cap_result.metadata.get("transform_plan")
    assert plan_meta is not None, f"Expected plan, got: {cap_result.metadata}"
    assert plan_meta["operation_type"] == "CLIP"
    assert plan_meta["affected_cells_count"] == 1
    assert "Cap" in cap_result.answer or "clip" in cap_result.answer.lower()
    print(f"\nCAP result: {cap_result.answer} (took {elapsed_cap:.3f}s)")

    # Step 3: Test Option 2 (UPDATE_EXTREMUM) with fresh chat
    chat_id2 = str(uuid.uuid4())
    context2 = ExecutionContext(
        message="change the highest departure delay to 60",
        dataset_id=dataset_id,
        dataset_filename='india_flight_delay_model_input.csv',
        chat_id=chat_id2
    )
    result2 = master_router.route(context2)
    trans_id2 = result2.metadata["clarification"]["transformation_id"]

    ext_context = ExecutionContext(
        message="I meant: Change only the maximum record(s) to 60",
        dataset_id=dataset_id,
        dataset_filename='india_flight_delay_model_input.csv',
        chat_id=chat_id2,
        workspace_action={
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'EXTREME_VALUE_AMBIGUITY',
            'transformation_id': trans_id2,
            'action': 'UPDATE_EXTREMUM',
            'chosen_operation': {'type': 'UPDATE_EXTREMUM', 'column': 'Departure_Delay', 'extremum': 'max', 'new_value': 60}
        }
    )
    ext_result = master_router.route(ext_context)
    assert ext_result.success is True
    ext_plan = ext_result.metadata.get("transform_plan")
    assert ext_plan["operation_type"] == "UPDATE_EXTREMUM"
    assert ext_plan["affected_cells_count"] == 1
    print(f"UPDATE_EXTREMUM result: {ext_result.answer}")

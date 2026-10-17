import pytest
import pandas as pd
import uuid
import re

def test_replace_unstructured_clarification():
    # Set up
    from engines.transform import transform_engine
    from router.master_router import _parse_transform_from_message
    from transformation.store import transformation_store
    
    df = pd.DataFrame({
        'name': ['Alice', 0, 'Charlie'],
        'phone': ['123', 0, '789'],
        'age': [25.0, 0.0, 35.0],
    })
    
    class DummyContext:
        def __init__(self, message, dataset_id, chat_id, llm_operation=None, workspace_action=None):
            self.message = message
            self.dataset_id = dataset_id
            self.chat_id = chat_id
            self.session_id = chat_id
            self.request_id = str(uuid.uuid4())
            self.llm_operation = llm_operation
            self.workspace_action = workspace_action
            self.dataset_entry = type('Entry', (), {'dataframe': df})()
            
        def start_stage(self, name):
            class DummyStage:
                def __enter__(self): return self
                def __exit__(self, *args): pass
            return DummyStage()
            
        def complete_stage(self, stage):
            pass

    dataset_id = "test-dataset-none"
    chat_id = "test-chat-none"
    
    # Fake dataset registry
    from datasets.registry import dataset_registry
    dataset_registry._datasets[dataset_id] = type('Entry', (), {'dataframe': df})()

    # 1. Parse initial request
    op = _parse_transform_from_message("replace 0 with 'none'")
    assert op['new_value'] == 'none'
    assert op['_new_typed']['value_type'] == 'string'
    
    context = DummyContext("replace 0 with 'none'", dataset_id, chat_id, op)
    
    # 2. Trigger clarification
    result = transform_engine.handle(context)
    assert 'clarification' in result.metadata
    
    pending = transformation_store.pending_for(chat_id, dataset_id)
    assert pending is not None
    # Wipe the operation payload typed metadata to simulate whatever the frontend/network did
    pending.operation_payload.pop('_new_typed', None)
    pending.operation_payload.pop('_old_typed', None)
    transformation_store.update_pending(pending)
    
    # 3. Resolve clarification with unstructured message (no workspace action)
    clarification_msg = "phone column"
    # Route message handles the clarification
    context2 = DummyContext(clarification_msg, dataset_id, chat_id)
    from router.master_router import MasterRouter
    master_router = MasterRouter()
    route_result = master_router._pending_transform_fast_path(context2)
    
    assert route_result['intent'] == 'TRANSFORM'
    reconstructed_op = route_result['operation']
    
    # 4. Verify reconstruction correctly pulled from pending.destination_typed_literal
    assert '_new_typed' in reconstructed_op
    assert reconstructed_op['_new_typed']['value_type'] == 'string'
    assert reconstructed_op['new_value'] == 'none'
    assert reconstructed_op['columns'] == ['phone']
    
    # 5. Pass to planner and verify
    context2.llm_operation = reconstructed_op
    plan_result = transform_engine.handle(context2)
    assert plan_result.success
    plan = plan_result.metadata['transform_plan']
    
    assert plan['operation_type'] == 'REPLACE_VALUES'
    assert "string(\"none\")" in plan['operation_label']
    assert plan['affected_columns'] == ['phone']
    
    # Ensure serialization doesn't mess it up
    serialized = transform_engine._plan_to_dict(
        transformation_store.get(plan['plan_id'])
    )
    assert "string(\"none\")" in serialized['operation_label']
    
    # We should have a valid after value
    assert serialized['before_sample'][0]['after'] == 'none'

def test_replace_all_columns_clarification():
    from engines.transform import transform_engine
    from transformation.store import transformation_store
    
    df = pd.DataFrame({
        'name': ['Alice', 0, 'Charlie'],
        'phone': ['123', 0, '789'],
    })
    
    class DummyContext:
        def __init__(self, message, dataset_id, chat_id, llm_operation=None, workspace_action=None):
            self.message = message
            self.dataset_id = dataset_id
            self.chat_id = chat_id
            self.session_id = chat_id
            self.request_id = str(uuid.uuid4())
            self.llm_operation = llm_operation
            self.workspace_action = workspace_action
            self.dataset_entry = type('Entry', (), {'dataframe': df})()
            
        def start_stage(self, name):
            class DummyStage:
                def __enter__(self): return self
                def __exit__(self, *args): pass
            return DummyStage()
            
        def complete_stage(self, stage):
            pass
            
    dataset_id = "test-dataset-all-none"
    chat_id = "test-chat-all-none"
    
    from datasets.registry import dataset_registry
    dataset_registry._datasets[dataset_id] = type('Entry', (), {'dataframe': df})()
    from router.master_router import _parse_transform_from_message
    op = _parse_transform_from_message("replace 0 with 'none'")
    
    context = DummyContext("replace 0 with 'none'", dataset_id, chat_id, op)
    transform_engine.handle(context)
    
    pending = transformation_store.pending_for(chat_id, dataset_id)
    pending.operation_payload.pop('_new_typed', None)
    pending.operation_payload.pop('_old_typed', None)
    transformation_store.update_pending(pending)
    
    clarification_msg = "all columns"
    context2 = DummyContext(clarification_msg, dataset_id, chat_id)
    from router.master_router import MasterRouter
    master_router = MasterRouter()
    route_result = master_router._pending_transform_fast_path(context2)
    
    reconstructed_op = route_result['operation']
    assert reconstructed_op['_new_typed']['value_type'] == 'string'
    
    context2.llm_operation = reconstructed_op
    plan_result = transform_engine.handle(context2)
    plan = plan_result.metadata['transform_plan']
    assert plan['affected_columns'] == ['name', 'phone']
    assert "string(\"none\")" in plan['operation_label']

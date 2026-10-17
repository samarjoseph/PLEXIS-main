import pytest
import pandas as pd
from router.master_router import MasterRouter
from engines.transform import TransformEngine
from core.context import ExecutionContext
from transformation.planner import _compute_fingerprint
from transformation.store import transformation_store

class DummyContext(ExecutionContext):
    def __init__(self, message, dataset_id, **kwargs):
        self.message = message
        self.dataset_id = dataset_id
        self.chat_id = 'test-chat'
        self.session_id = 'test-session'
        self._llm_operation = kwargs.pop('llm_operation', None)
        self.workspace_action = kwargs.pop('workspace_action', None)
        for k, v in kwargs.items():
            setattr(self, k, v)
            
    def start_stage(self, name, **kwargs): pass
    def complete_stage(self, name, **kwargs): pass
    @property
    def request_id(self): return "123"
    
    @property
    def llm_operation(self):
        return self._llm_operation
    @llm_operation.setter
    def llm_operation(self, value):
        self._llm_operation = value

@pytest.fixture
def test_dataset():
    # Contains a string "none"
    return pd.DataFrame({
        'id': [1, 2, 3],
        'age': [0, 25, 'none'],
        'phone': ['555', 'none', '123'],
        'status': ['active', 'none', 'inactive']
    })

@pytest.fixture
def router():
    return MasterRouter()

@pytest.fixture
def engine():
    return TransformEngine()

def test_value_type_mismatch_destination(test_dataset, router, engine, monkeypatch):
    dataset_id = "test-dataset-id"
    df = test_dataset
    
    from unittest.mock import MagicMock
    entry = MagicMock()
    entry.dataset_id = dataset_id
    entry.dataframe = df
    entry.row_count = len(df)
    entry.column_count = len(df.columns)
    from datasets.registry import dataset_registry
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)
    
    # 1. User: "replace 0 with none"
    ctx = DummyContext("replace 0 with none", dataset_id)
    from router.master_router import _parse_transform_from_message
    parsed = _parse_transform_from_message("replace 0 with none")
    assert parsed['type'] == 'REPLACE_VALUES'
    
    # We must format it like the router does for transform operations
    from router.master_router import _normalize_transform_operation
    ctx.llm_operation = _normalize_transform_operation(parsed)
    
    res = engine.handle(ctx)
    assert res.success is True
    assert 'clarification' in res.metadata
    clarification = res.metadata['clarification']
    assert clarification['status'] == 'AWAITING_CLARIFICATION'
    assert clarification['clarification_type'] == 'VALUE_TYPE_MISMATCH'
    assert clarification['requested_value_info']['value_type'] == 'null'
    assert clarification['candidate_value_info']['value_type'] == 'string'
    
    # 2. User clicks "Continue"
    action = {
        'type': 'TRANSFORMATION_CLARIFICATION',
        'clarification_type': 'VALUE_TYPE_MISMATCH',
        'transformation_id': clarification['transformation_id'],
        'value': 'CONTINUE',
        'candidate_value_info': clarification['candidate_value_info'],
        'target_field': '_new_typed'
    }
    
    ctx2 = DummyContext("yes, use the suggested value", dataset_id, workspace_action=action)
    intent2 = router._pending_transform_fast_path(ctx2)
    assert intent2['intent'] == 'TRANSFORM'
    assert intent2['operation']['new_value'] == 'none'
    assert intent2['operation']['_new_typed']['value_type'] == 'string'
    
    ctx2.llm_operation = intent2['operation']
    res2 = engine.handle(ctx2)
    assert res2.success is True
    
    # Wait, now it might ask for target_scope because we didn't specify column!
    clarification2 = res2.metadata.get('clarification')
    if clarification2:
        assert clarification2['clarification_type'] == 'COLUMN_SCOPE'
        # Finish clarification
        action2 = {
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'COLUMN_SCOPE',
            'transformation_id': clarification2['transformation_id'],
            'value': 'ALL_MATCHING_COLUMNS'
        }
        ctx3 = DummyContext("all matching columns", dataset_id, workspace_action=action2)
        intent3 = router._pending_transform_fast_path(ctx3)
        ctx3.llm_operation = intent3['operation']
        res3 = engine.handle(ctx3)
        assert res3.metadata.get('transform_plan') is not None
        plan = res3.metadata['transform_plan']
    else:
        plan = res2.metadata['transform_plan']
        
    assert plan is not None

def test_no_mismatch_if_quoted(test_dataset, router, engine, monkeypatch):
    dataset_id = "test-dataset-id"
    df = test_dataset
    from unittest.mock import MagicMock
    entry = MagicMock()
    entry.dataset_id = dataset_id
    entry.dataframe = df
    entry.row_count = len(df)
    entry.column_count = len(df.columns)
    from datasets.registry import dataset_registry
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)
    
    ctx = DummyContext("replace 0 with 'none'", dataset_id)
    from router.master_router import _parse_transform_from_message
    parsed = _parse_transform_from_message("replace 0 with 'none'")
    from router.master_router import _normalize_transform_operation
    ctx.llm_operation = _normalize_transform_operation(parsed)
    res = engine.handle(ctx)
    
    # Should skip type mismatch and go directly to column scope clarification
    clarification = res.metadata.get('clarification')
    if clarification:
        assert clarification['clarification_type'] == 'COLUMN_SCOPE'

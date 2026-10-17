import pytest
import pandas as pd
from datasets.semantics.typed_literal import parse_literal
from datasets.semantics.value_resolver import resolve_natural_value, ValueAmbiguityClarificationRequired

def test_resolve_natural_value():
    df = pd.DataFrame({
        'col1': [0, 1, None],
        'col2': ['missing', 'active', 'none'],
        'col3': ['the Missing', 'Missing', 'val']
    })
    
    # 1. "the Missing" -> stripped to "Missing" -> resolves to NULL
    # But dataset contains NULL (col1) AND "the Missing" (col3) AND "Missing" (col3)
    # So it should be ambiguous.
    primary, options = resolve_natural_value("the Missing", False, df, list(df.columns))
    assert primary.value_type == 'null'
    assert len(options) == 3
    assert options[0]['label'] == 'Missing / null values'
    assert options[1]['label'] == 'The text "the Missing"'
    assert options[2]['label'] == 'The text "Missing"'

    # 2. "missing values" -> stripped to "missing" -> resolves to NULL
    primary, options = resolve_natural_value("missing values", False, df, list(df.columns))
    assert primary.value_type == 'null'
    assert len(options) == 2
    assert options[0]['label'] == 'Missing / null values'
    assert options[1]['label'] == 'The text "missing"'

    # 3. Quoted: "the Missing" -> should remain string("the Missing")
    primary, options = resolve_natural_value("the Missing", True, df, list(df.columns))
    assert primary.value_type == 'string'
    assert primary.value == 'the Missing'
    assert len(options) == 0

    # 4. "the 0" -> stripped to "0" -> INTEGER(0)
    primary, options = resolve_natural_value("the 0", False, df, list(df.columns))
    assert primary.value_type == 'integer'
    assert primary.value == 0
    # No string "the 0" or "0" exists in dataset
    assert len(options) == 0

    # 5. "the 0" but dataset HAS "the 0"
    df2 = pd.DataFrame({'col': [0, 'the 0']})
    primary, options = resolve_natural_value("the 0", False, df2, list(df2.columns))
    assert primary.value_type == 'integer'
    assert primary.value == 0
    assert len(options) == 2
    assert options[0]['label'] == 'The number 0'
    assert options[1]['label'] == 'The text "the 0"'

def test_planner_ambiguity(monkeypatch):
    from engines.transform import TransformEngine
    from router.master_router import MasterRouter
    from core.context import ExecutionContext
    
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
        @property
        def request_id(self): return "123"
        @property
        def llm_operation(self): return self._llm_operation
        @llm_operation.setter
        def llm_operation(self, value): self._llm_operation = value
        def start_stage(self, *a, **kw): pass
        def complete_stage(self, *a, **kw): pass

    df = pd.DataFrame({'col1': [None, 'Missing']})
    from unittest.mock import MagicMock
    entry = MagicMock()
    entry.dataset_id = "test-dataset-id"
    entry.dataframe = df
    entry.row_count = 2
    entry.column_count = 1
    from datasets.registry import dataset_registry
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)
    
    router = MasterRouter()
    engine = TransformEngine()
    
    # User says: "change the Missing to unknown"
    ctx = DummyContext("change the Missing to unknown", "test-dataset-id")
    from router.master_router import _parse_transform_from_message, _normalize_transform_operation
    parsed = _parse_transform_from_message("change the Missing to unknown")
    ctx.llm_operation = _normalize_transform_operation(parsed)
    
    res = engine.handle(ctx)
    assert res.success is True
    assert 'clarification' in res.metadata
    
    clarification = res.metadata['clarification']
    assert clarification['clarification_type'] == 'VALUE_AMBIGUITY'
    assert len(clarification['ambiguous_options']) == 2
    assert clarification['ambiguous_options'][0]['label'] == 'Missing / null values'
    assert clarification['ambiguous_options'][1]['label'] == 'The text "Missing"'
    
    # User clicks "Missing / null values"
    action = {
        'type': 'TRANSFORMATION_CLARIFICATION',
        'clarification_type': 'VALUE_AMBIGUITY',
        'transformation_id': clarification['transformation_id'],
        'value': 'RESOLVE_AMBIGUITY',
        'resolved_value_info': {
            'value': None,
            'value_type': 'null',
            'source_form': 'the Missing',
            'explicit': True,
            'was_quoted': False
        }
    }
    
    ctx2 = DummyContext("Missing values", "test-dataset-id", workspace_action=action)
    intent2 = router._pending_transform_fast_path(ctx2)
    assert intent2['intent'] == 'TRANSFORM'
    assert intent2['operation'].get('_old_raw') is None
    
    ctx2.llm_operation = intent2['operation']
    res2 = engine.handle(ctx2)
    assert res2.success is True
    
    clarification2 = res2.metadata.get('clarification')
    if clarification2 and clarification2['clarification_type'] == 'COLUMN_SCOPE':
        # Select all columns
        action2 = {
            'type': 'TRANSFORMATION_CLARIFICATION',
            'clarification_type': 'COLUMN_SCOPE',
            'transformation_id': clarification2['transformation_id'],
            'value': 'ALL_MATCHING_COLUMNS'
        }
        ctx3 = DummyContext("all matching columns", "test-dataset-id", workspace_action=action2)
        intent3 = router._pending_transform_fast_path(ctx3)
        ctx3.llm_operation = intent3['operation']
        res3 = engine.handle(ctx3)
        plan = res3.metadata.get('transform_plan')
    else:
        plan = res2.metadata.get('transform_plan')
        
    assert plan is not None
    assert 'Replace null with ' in plan['operation_label']

def test_intelligence_provenance(monkeypatch):
    import pandas as pd
    from engines.transform import TransformEngine
    from router.master_router import MasterRouter
    class DummyContext:
        def __init__(self, message, dataset_id, **kwargs):
            self.message = message
            self.dataset_id = dataset_id
            self.api_key = 'test'
            self.conversation_id = 'test-conv'
            self.chat_id = 'test-chat'
            self.session_id = 'test-session'
            self._llm_operation = kwargs.pop('llm_operation', None)
            self.workspace_action = kwargs.pop('workspace_action', None)
            for k, v in kwargs.items():
                setattr(self, k, v)
        @property
        def request_id(self): return "123"
        @property
        def llm_operation(self): return self._llm_operation
        @llm_operation.setter
        def llm_operation(self, value): self._llm_operation = value
        def start_stage(self, *a, **kw): pass
        def complete_stage(self, *a, **kw): pass
        def get(self, k, default=None): return getattr(self, k, default)
        def update(self, k, v): setattr(self, k, v)

    # Dataset does NOT have integers. It has the string "0".
    df = pd.DataFrame({'col1': ['0', '1']})
    from unittest.mock import MagicMock
    entry = MagicMock()
    entry.dataset_id = "test-dataset-id"
    entry.dataframe = df
    entry.row_count = 2
    entry.column_count = 1
    from datasets.registry import dataset_registry
    monkeypatch.setattr(dataset_registry, 'get', lambda id: entry)
    
    router = MasterRouter()
    engine = TransformEngine()
    
    # User says: "replace 0 with none"
    ctx = DummyContext("replace 0 with none", "test-dataset-id")
    from router.master_router import _parse_transform_from_message, _normalize_transform_operation
    parsed = _parse_transform_from_message("replace 0 with none")
    op = _normalize_transform_operation(parsed)
    op['_old_raw'] = None
    ctx.llm_operation = op
    
    res = engine.handle(ctx)
    assert res.success is True
    assert 'clarification' in res.metadata
    
    clarification = res.metadata['clarification']
    assert clarification['clarification_type'] == 'VALUE_TYPE_MISMATCH'
    assert clarification['candidate_value_info']['value'] == '0'
    assert clarification['candidate_value_info']['value_type'] == 'string'
    
    # User clicks "Continue"
    action = {
        'type': 'TRANSFORMATION_CLARIFICATION',
        'clarification_type': 'VALUE_TYPE_MISMATCH',
        'transformation_id': clarification['transformation_id'],
        'value': 'CONTINUE',
        'candidate_value_info': clarification['candidate_value_info'],
        'requested_value_info': clarification['requested_value_info'],
        'target_field': '_old_typed'
    }
    
    ctx2 = DummyContext("Continue", "test-dataset-id", workspace_action=action)
    intent2 = router._pending_transform_fast_path(ctx2)
    assert intent2['intent'] == 'TRANSFORM'
    assert intent2['operation']['intelligence_provenance']['used'] is True
    
    ctx2.llm_operation = intent2['operation']
    res2 = engine.handle(ctx2)
    assert res2.success is True
    
    plan = res2.metadata.get('transform_plan')
    assert plan is not None
    assert 'intelligence_provenance' in plan
    assert plan['intelligence_provenance']['used'] is True

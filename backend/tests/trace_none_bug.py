"""Trace multi-column clarification path for: replace 0 with 'none' """
import sys; sys.path.insert(0, 'backend')
import pandas as pd
import numpy as np
import uuid

# Stage 1: Router
from router.master_router import _parse_transform_from_message
op = _parse_transform_from_message("replace 0 with 'none'")
print('=== STAGE 1: ROUTER ===')
print(f"  new_value = {op['new_value']!r}  type={type(op['new_value']).__name__}")
print(f"  _new_typed value_type = {op.get('_new_typed', {}).get('value_type')}")
print(f"  _new_typed value = {op.get('_new_typed', {}).get('value')!r}")

# Stage 2: Simulate multi-column detection (planner raises clarification)
df = pd.DataFrame({
    'id': [1, 2, 3],
    'name': ['Alice', 0, 'Charlie'],
    'phone': ['123', 0, '789'],
    'age': [25.0, 0.0, 35.0],
})

from transformation.planner import TransformationPlanner, _compute_fingerprint
from transformation.planner import TransformationClarificationRequired
planner = TransformationPlanner()
plan_id = str(uuid.uuid4())
dataset_id = 'test-dataset'
fingerprint = _compute_fingerprint(df)

# First call: no column specified, should raise clarification
try:
    plan = planner._plan_replace_values(df, dict(op), plan_id, dataset_id, fingerprint)
    print(f'\n=== STAGE 2: PLANNER (no column) ===')
    print(f"  UNEXPECTED: no clarification raised!")
    print(f"  plan.operation_label = {plan.operation_label}")
except TransformationClarificationRequired as e:
    print(f'\n=== STAGE 2: CLARIFICATION RAISED ===')
    print(f"  message = {e}")
    print(f"  candidate_columns = {e.candidate_columns}")

# Stage 3: Simulate what TransformEngine._create_pending_clarification does
print('\n=== STAGE 3: PENDING CONTEXT ===')
from transformation.store import PendingTransformationContext
pending = PendingTransformationContext.create(
    conversation_id='test-conv',
    dataset_id=dataset_id,
    dataset_version=1,
    dataset_fingerprint=fingerprint,
    operation_type='REPLACE_VALUES',
    operation_payload=dict(op),  # <-- THIS is what gets stored
    source_typed_literal=op.get('_old_typed'),
    destination_typed_literal=op.get('_new_typed'),
    candidate_columns=['name', 'phone', 'age'],
    missing_slots=['target_scope'],
    original_request="replace 0 with 'none'",
    latest_question='Found integer(0) in 3 columns...',
)
print(f"  pending.operation_payload['new_value'] = {pending.operation_payload.get('new_value')!r}  type={type(pending.operation_payload.get('new_value')).__name__}")
print(f"  pending.destination_typed_literal = {pending.destination_typed_literal}")
print(f"  pending.operation_payload['_new_typed'] = {pending.operation_payload.get('_new_typed')}")

# Stage 4: Simulate user responding "name" (unstructured path)
print('\n=== STAGE 4: CLARIFICATION RESOLUTION (unstructured) ===')
# Line 803: operation = dict(pending.operation_payload)
operation = dict(pending.operation_payload)
print(f"  BEFORE typed literal restoration:")
print(f"    operation['new_value'] = {operation.get('new_value')!r}  type={type(operation.get('new_value')).__name__}")
print(f"    operation['_new_typed'] = {operation.get('_new_typed')}")

# Lines 780-789 only run in the STRUCTURED path (workspace_action).
# In the unstructured path (lines 803+), there is NO restoration of typed literals
# UNLESS the `ready_for_review` path at line 853+ triggers.

# Since this is NOT ready_for_review (first clarification), what happens?
# Line 966: operation['columns'] = [selected_columns]
# Line 967: operation['scope'] = scope
# ...
# Line 1054: return {'intent': 'TRANSFORM', 'operation': operation}
# The operation dict is passed through WITHOUT typed literal restoration!

# But wait - the operation_payload already contains _new_typed from the router!
# Let's verify:
print(f"\n  Check: does operation_payload already have _new_typed?")
print(f"    '_new_typed' in operation: {'_new_typed' in operation}")
if '_new_typed' in operation:
    print(f"    _new_typed = {operation['_new_typed']}")
    print(f"    new_value = {operation['new_value']!r}")

# Stage 5: Now simulate what happens when this goes back to the planner
print('\n=== STAGE 5: SECOND PLANNER CALL (with columns) ===')
operation['columns'] = ['name']
operation['scope'] = {'type': 'EXPLICIT_COLUMNS', 'columns': ['name']}
operation.pop('column', None)

plan_id2 = str(uuid.uuid4())
plan = planner._plan_replace_values(df, operation, plan_id2, dataset_id, fingerprint)
print(f"  operation_label = {plan.operation_label!r}")
print(f"  payload new_value = {plan.operation_payload.get('new_value')!r}  type={type(plan.operation_payload.get('new_value')).__name__}")
print(f"  payload _new_typed = {plan.operation_payload.get('_new_typed')}")
if plan.before_sample:
    for s in plan.before_sample:
        print(f"  sample: row={s.row_index} col={s.column} before={s.before!r}(type={type(s.before).__name__}) after={s.after!r}(type={type(s.after).__name__})")

# Stage 6: _plan_to_dict serialization
print('\n=== STAGE 6: _plan_to_dict SERIALIZATION ===')
# This is what gets sent to frontend
from engines.transform import TransformEngine
te = TransformEngine()
d = te._plan_to_dict(plan)
if d.get('before_sample'):
    for s in d['before_sample'][:5]:
        print(f"  before={s['before']!r}  after={s['after']!r}")
print(f"  operation_label = {d['operation_label']!r}")

import pytest
import pandas as pd
from router.master_router import _parse_transform_from_message
from transformation.ir import TransformationIR, TransformStep
from transformation.validator import ir_validator
from transformation.compiler import ir_compiler

def test_router_parsing():
    # Test 1
    res = _parse_transform_from_message('rename column age with Age')
    assert res['column'] == 'age'
    assert res['new_name'] == 'Age'
    
    # Test 2
    res = _parse_transform_from_message('rename column age to AGE')
    assert res['column'] == 'age'
    assert res['new_name'] == 'AGE'
    
    # Test 3
    res = _parse_transform_from_message('rename age to "Age Years"')
    assert res['column'] == 'age'
    assert res['new_name'] == 'Age Years'
    
def test_validator_rules():
    df = pd.DataFrame({'age': [48, 37, 65], 'name': ['A', 'B', 'C']})
    
    # Test 4: no-op
    ir_noop = TransformationIR(
        goal="rename",
        steps=[TransformStep(id="1", operation="RENAME_COLUMN", params={"column": "age", "new_name": "age"}, depends_on=[])]
    )
    res_noop = ir_validator.validate(ir_noop, df)
    assert not res_noop.valid
    assert "already named 'age'" in res_noop.errors[0]
    
    # Test 5: collision
    ir_col = TransformationIR(
        goal="rename",
        steps=[TransformStep(id="1", operation="RENAME_COLUMN", params={"column": "age", "new_name": "name"}, depends_on=[])]
    )
    res_col = ir_validator.validate(ir_col, df)
    assert not res_col.valid
    assert "Destination column 'name' already exists" in res_col.errors[0]

def test_compiler_semantics():
    df = pd.DataFrame({'age': [48, 37, 65]})
    
    ir = TransformationIR(
        goal="rename",
        steps=[TransformStep(id="1", operation="RENAME_COLUMN", params={"column": "age", "new_name": "Age"}, depends_on=[])]
    )
    
    # Test 6: Verify values remain unchanged
    sim = ir_compiler.compile_and_simulate(ir, df, "test")
    assert sim.success
    assert list(sim.result_df['Age']) == [48, 37, 65]
    
    plan = ir_compiler.simulation_to_plan(ir, sim, "test", "test_fp")
    
    # Test 7 & 8: Schema diff, not cell diff
    assert plan.affected_cells_count == 0
    assert plan.operation_payload['impact']['type'] == 'schema'
    
    # Verify preview structure
    sample = plan.before_sample[0]
    assert sample.row_index == -1
    assert sample.column == "Age"
    assert sample.before == "Column header: 'age'"
    assert sample.after == "Column header: 'Age'"


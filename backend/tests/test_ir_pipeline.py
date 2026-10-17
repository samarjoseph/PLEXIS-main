import pytest
import pandas as pd
import numpy as np

from transformation.ir import (
    TransformationIR, TransformStep, PRIMITIVE_REGISTRY, validate_expr_node,
    collect_column_refs
)
from transformation.validator import ir_validator
from transformation.compiler import expr_evaluator, ir_compiler
from datasets.semantics.typed_literal import parse_literal
from transformation.ir_planner import _annotate_typed_literals

def test_ast_evaluation():
    df = pd.DataFrame({
        'price': [10, 20, 30],
        'qty': [2, 3, 4],
        'status': ['A', 'B', 'A']
    })

    # Test arithmetic
    expr = {
        'type': 'ARITHMETIC',
        'operator': 'multiply',
        'left': {'type': 'COLUMN', 'name': 'price'},
        'right': {'type': 'COLUMN', 'name': 'qty'}
    }
    res = expr_evaluator.evaluate(expr, df)
    assert res.tolist() == [20, 60, 120]

    # Test comparison
    expr2 = {
        'type': 'COMPARE',
        'operator': '>',
        'left': {'type': 'COLUMN', 'name': 'qty'},
        'right': {'type': 'LITERAL', 'value': 2}
    }
    res2 = expr_evaluator.evaluate(expr2, df)
    assert res2.tolist() == [False, True, True]

    # Test case statement
    expr3 = {
        'type': 'CASE',
        'conditions': [
            {
                'when': {'type': 'COMPARE', 'operator': '==', 'left': {'type': 'COLUMN', 'name': 'status'}, 'right': {'type': 'LITERAL', 'value': 'A'}},
                'value': 'Active'
            }
        ],
        'default': 'Inactive'
    }
    res3 = expr_evaluator.evaluate(expr3, df)
    assert res3.tolist() == ['Active', 'Inactive', 'Active']


def test_ir_typed_equality_uses_canonical_value_semantics():
    df = pd.DataFrame({'value': pd.Series([0, 0.0, '0', True], dtype=object)})
    numeric_expr = {
        'type': 'COMPARE', 'operator': '==',
        'left': {'type': 'COLUMN', 'name': 'value'},
        'right': {'type': 'LITERAL', 'value': 0,
                  'typed_literal': parse_literal('0').to_dict()},
    }
    string_expr = {
        'type': 'COMPARE', 'operator': '==',
        'left': {'type': 'COLUMN', 'name': 'value'},
        'right': {'type': 'LITERAL', 'value': '0',
                  'typed_literal': parse_literal('0', was_quoted=True).to_dict()},
    }
    assert expr_evaluator.evaluate(numeric_expr, df).tolist() == [True, True, False, False]
    assert expr_evaluator.evaluate(string_expr, df).tolist() == [False, False, True, False]
    assert ir_validator.validate(TransformationIR(
        goal='typed equality',
        steps=[TransformStep(id='s1', operation='CREATE_COLUMN', params={'column': 'matched'},
                             expression=numeric_expr)],
    ), df).valid


def test_ir_planner_attaches_typed_metadata_to_untyped_literal_nodes():
    ir_dict = {'steps': [{'expression': {
        'type': 'COMPARE', 'operator': '==',
        'left': {'type': 'COLUMN', 'name': 'value'},
        'right': {'type': 'LITERAL', 'value': 0},
    }}]}
    result = _annotate_typed_literals(ir_dict, 'replace numeric 0')
    literal = result['steps'][0]['expression']['right']
    assert literal['typed_literal']['value_type'] == 'integer'
    assert literal['typed_literal']['value'] == 0
    assert not literal['typed_literal']['was_quoted']

    replace_ir = {'steps': [{'operation': 'REPLACE', 'params': {
        'column': 'value', 'old_value': 0, 'new_value': 'unknown',
    }}]}
    replaced = _annotate_typed_literals(replace_ir, 'replace 0 with "unknown"')
    assert replaced['steps'][0]['params']['_old_typed']['value_type'] == 'integer'

def test_ir_validator():
    df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
    
    # Valid IR
    ir = TransformationIR(
        goal="Test",
        steps=[
            TransformStep(
                id="1",
                operation="CREATE_COLUMN",
                params={"column": "c"},
                expression={
                    "type": "ARITHMETIC",
                    "operator": "add",
                    "left": {"type": "COLUMN", "name": "a"},
                    "right": {"type": "COLUMN", "name": "b"}
                }
            )
        ]
    )
    val = ir_validator.validate(ir, df)
    assert val.valid is True
    
    # Invalid: security check
    ir2 = TransformationIR(
        goal="Test",
        steps=[
            TransformStep(
                id="1",
                operation="CREATE_COLUMN",
                params={"column": "c"},
                expression={
                    "type": "eval_something",  # should be caught
                    "left": {"type": "COLUMN", "name": "a"},
                    "right": {"type": "COLUMN", "name": "b"}
                }
            )
        ]
    )
    val2 = ir_validator.validate(ir2, df)
    assert val2.valid is False
    assert any("Security error" in e for e in val2.errors)

def test_ir_compiler_end_to_end():
    df = pd.DataFrame({
        'name': [' alice ', 'BOB', None],
        'age': [17, 25, 65]
    })
    
    ir = TransformationIR(
        goal="Clean names and classify age",
        steps=[
            # 1. Fill missing
            TransformStep(id="s1", operation="FILL", params={"columns": ["name"], "value": "unknown"}),
            # 2. Strip
            TransformStep(id="s2", operation="STRIP", params={"columns": ["name"]}, depends_on=["s1"]),
            # 3. Title
            TransformStep(id="s3", operation="TITLE", params={"columns": ["name"]}, depends_on=["s2"]),
            # 4. Create category
            TransformStep(
                id="s4", 
                operation="CREATE_COLUMN",
                params={"column": "category"},
                expression={
                    "type": "CASE",
                    "conditions": [
                        {"when": {"type": "COMPARE", "operator": "<", "left": {"type": "COLUMN", "name": "age"}, "right": {"type": "LITERAL", "value": 18}}, "value": "Minor"}
                    ],
                    "default": "Adult"
                }
            )
        ]
    )
    
    sim = ir_compiler.compile_and_simulate(ir, df, "ds_1")
    assert sim.success is True
    
    res_df = sim.result_df
    assert res_df['name'].tolist() == ['Alice', 'Bob', 'Unknown']
    assert res_df['category'].tolist() == ['Minor', 'Adult', 'Adult']
    
    assert sim.affected_rows > 0
    assert sim.total_cells_changed > 0

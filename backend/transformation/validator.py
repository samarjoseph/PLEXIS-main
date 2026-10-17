import logging
from typing import List
import pandas as pd

from .ir import (
    TransformationIR,
    TransformStep,
    ValidationResult,
    PRIMITIVE_REGISTRY,
    DEFERRED_CAPABILITIES,
    ALLOWED_COMPARE_OPS,
    validate_expr_node,
    collect_column_refs
)

logger = logging.getLogger(__name__)

def topological_sort(steps: List[TransformStep]) -> List[TransformStep]:
    """Sort steps by dependency order. Raises ValueError on cycles."""
    # Create an adjacency list representing dependencies
    graph = {step.id: [] for step in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep in graph:
                graph[step.id].append(dep)
            else:
                raise ValueError(f"Step {step.id} depends on unknown step {dep}")

    visited = {}
    result = []

    def visit(node_id):
        if visited.get(node_id) == -1:
            raise ValueError(f"Circular dependency detected involving step {node_id}")
        if visited.get(node_id) == 1:
            return
        
        visited[node_id] = -1
        for neighbor in graph[node_id]:
            visit(neighbor)
        
        visited[node_id] = 1
        result.append(node_id)

    for step in steps:
        if step.id not in visited:
            visit(step.id)

    step_map = {step.id: step for step in steps}
    return [step_map[step_id] for step_id in result]

class IRValidator:
    def validate(self, ir: TransformationIR, df: pd.DataFrame) -> ValidationResult:
        errors = []
        warnings = []
        
        try:
            sorted_steps = topological_sort(ir.steps)
        except ValueError as e:
            return ValidationResult(valid=False, errors=[str(e)])

        step_ids = set()
        for step in ir.steps:
            if step.id in step_ids:
                errors.append(f"Duplicate step ID found: {step.id}")
            step_ids.add(step.id)

        current_columns = set(df.columns) if df is not None else set()
        
        def check_security(node: dict):
            if not isinstance(node, dict):
                return
            node_type = node.get('type', '')
            if isinstance(node_type, str):
                lower_type = node_type.lower()
                for bad in ('eval', 'exec', 'import', 'system', '__'):
                    if bad in lower_type:
                        errors.append(f"Security error: Forbidden term '{bad}' found in expression type '{node_type}'")
            
            # Recurse into children
            for key in ('left', 'right', 'operand'):
                child = node.get(key)
                if isinstance(child, dict):
                    check_security(child)
                    
            for cond in node.get('conditions', []):
                if isinstance(cond, dict):
                    for k in ('when', 'then'):
                        child = cond.get(k)
                        if isinstance(child, dict):
                            check_security(child)
                            
            for expr in node.get('expressions', []):
                if isinstance(expr, dict):
                    check_security(expr)

        for step in sorted_steps:
            if step.operation in DEFERRED_CAPABILITIES:
                return ValidationResult(valid=False, errors=[f"Deferred capability: {step.operation}"], unsupported=step.operation)
                
            if step.operation not in PRIMITIVE_REGISTRY:
                errors.append(f"Step {step.id}: Unknown operation '{step.operation}'")
                continue
                
            spec = PRIMITIVE_REGISTRY[step.operation]

            if step.operation == 'REPLACE' and step.params.get('_old_typed') is not None:
                typed = step.params['_old_typed']
                if (not isinstance(typed, dict)
                        or typed.get('__typed_literal__') is not True
                        or typed.get('value_type') not in {'integer', 'float', 'string', 'boolean', 'null', 'date'}
                        or 'value' not in typed):
                    errors.append(f"Step {step.id}: REPLACE has invalid _old_typed metadata")
            
            for req in spec.required_params:
                if req not in step.params:
                    errors.append(f"Step {step.id}: Missing required param '{req}' for {step.operation}")
                    
            if spec.requires_expression and step.expression is None:
                errors.append(f"Step {step.id}: Operation {step.operation} requires an expression")

            if step.expression is not None:
                expr_errors = validate_expr_node(step.expression)
                for err in expr_errors:
                    errors.append(f"Step {step.id}: {err}")
                check_security(step.expression)
                
                refs = collect_column_refs(step.expression)
                for ref in refs:
                    if ref not in current_columns:
                        errors.append(f"Step {step.id}: Referenced column '{ref}' does not exist or has not been created yet")

            if step.operation == 'CREATE_COLUMN':
                col_name = step.params.get('column')
                if col_name:
                    if col_name in current_columns:
                        errors.append(f"Step {step.id}: Output column '{col_name}' already exists")
                    current_columns.add(col_name)

            elif step.operation == 'MODIFY_COLUMN':
                col_name = step.params.get('column')
                if col_name and col_name not in current_columns:
                    errors.append(f"Step {step.id}: Target column '{col_name}' does not exist")

            elif step.operation == 'FILTER_ROWS':
                if step.expression is None:
                    # Using params-based filtering
                    op = step.params.get('operator')
                    if op and op not in ALLOWED_COMPARE_OPS:
                        errors.append(f"Step {step.id}: Invalid operator '{op}' for FILTER_ROWS")
            
            elif step.operation == 'DROP_COLUMN':
                col_name = step.params.get('column')
                if col_name in current_columns:
                    current_columns.remove(col_name)
                    
            elif step.operation == 'RENAME_COLUMN':
                col_name = step.params.get('column')
                new_name = step.params.get('new_name')
                if col_name and col_name not in current_columns:
                    errors.append(f"Step {step.id}: Source column '{col_name}' does not exist")
                elif col_name == new_name:
                    errors.append(f"The column is already named '{new_name}', so there is nothing to rename.")
                elif new_name in current_columns:
                    errors.append(f"Step {step.id}: Destination column '{new_name}' already exists")
                elif col_name in current_columns:
                    current_columns.remove(col_name)
                    if new_name:
                        current_columns.add(new_name)
                        
            elif step.operation == 'EXTRACT_DATE_PART' or step.operation == 'DATE_DIFF':
                out_col = step.params.get('output_column')
                if out_col:
                    current_columns.add(out_col)
                        
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
            
        return ValidationResult(valid=True, warnings=warnings)

ir_validator = IRValidator()

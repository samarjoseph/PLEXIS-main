import pandas as pd
from datasets.semantics.typed_literal import TypedLiteral, build_mask

def find_mismatch_candidate(df: pd.DataFrame, lit: TypedLiteral, columns: list[str]) -> TypedLiteral | None:
    if lit.was_quoted or lit.value_type == 'string':
        return None
    
    # Candidate 1: Exact textual match as string
    candidate_lit = TypedLiteral(lit.source_form, 'string', lit.source_form, False, False)
    
    # Check if the original lit exists in any of the columns
    original_exists = False
    candidate_exists = False
    
    for c in columns:
        if c not in df.columns:
            continue
        try:
            if build_mask(df[c], lit).any():
                original_exists = True
                break
        except Exception:
            pass
            
    if original_exists:
        return None
        
    for c in columns:
        if c not in df.columns:
            continue
        try:
            if build_mask(df[c], candidate_lit).any():
                candidate_exists = True
                break
        except Exception:
            pass
            
    if candidate_exists:
        return candidate_lit
    
    return None

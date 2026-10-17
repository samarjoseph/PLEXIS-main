import re
from typing import Optional, Tuple, List
import pandas as pd
from datasets.semantics.typed_literal import TypedLiteral, parse_literal

def resolve_natural_value(
    raw: str,
    was_quoted: bool,
    df: pd.DataFrame,
    columns: List[str]
) -> Tuple[TypedLiteral, List[dict]]:
    """
    Resolve a user's natural language token into a TypedLiteral using grammatical
    cleanup and dataset evidence.

    Returns:
        (best_literal, ambiguous_options)
        If ambiguous_options is not empty, the caller should prompt the user.
    """
    if was_quoted:
        return parse_literal(raw, was_quoted=True), []

    # 1. Grammatical cleanup
    # Remove leading articles: "the", "a", "an", "all"
    cleaned = re.sub(r'^(?i:the|a|an|all)\s+', '', raw).strip()
    
    # Remove trailing words like "values", "cells", "text"
    cleaned = re.sub(r'\s+(?i:values?|cells?|text|rows?)$', '', cleaned).strip()

    if not cleaned:
        cleaned = raw

    # 2. Parse the cleaned string
    primary_lit = parse_literal(cleaned, was_quoted=False)
    # We want to preserve the original raw text as the source form so it doesn't look like we just mangled it.
    from dataclasses import replace
    primary_lit = replace(primary_lit, source_form=raw)
    
    from datasets.semantics.typed_literal import build_mask

    # 3. See if the primary interpretation exists in the dataset
    primary_exists = False
    for col in columns:
        try:
            if build_mask(df[col], primary_lit).any():
                primary_exists = True
                break
        except Exception:
            pass

    # 4. Check for alternative string interpretation
    # If the user typed "Missing" (unquoted) and it resolved to NULL, 
    # but the string "Missing" also exists.
    # Or if the user typed "the Missing" -> cleaned="Missing" -> NULL
    # What if the string "the Missing" exists? Or "Missing" exists?
    
    ambiguous_options = []
    
    # First candidate: the literal string of the original raw text (e.g. "the Missing")
    # Second candidate: the literal string of the cleaned text (e.g. "Missing")
    # Only if they differ from the primary literal's value.
    
    candidates = []
    
    if primary_lit.value_type == 'null':
        candidates.append((raw, f'The text "{raw}"'))
        if cleaned != raw:
            candidates.append((cleaned, f'The text "{cleaned}"'))
    else:
        # For non-null types (numbers, booleans, strings), only check if cleanup changed text
        if cleaned != raw:
            candidates.append((raw, f'The text "{raw}"'))

    for text_val, label in candidates:
        str_lit = TypedLiteral(text_val, 'string', raw, True, True)
        # Does it exist?
        exists = False
        for col in columns:
            try:
                if build_mask(df[col], str_lit).any():
                    exists = True
                    break
            except Exception:
                pass
        
        if exists:
            ambiguous_options.append({
                'label': label,
                'value_info': str_lit.to_dict()
            })

    # If the primary literal is NULL, give it a nice label
    primary_label = None
    if primary_lit.value_type == 'null':
        primary_label = 'Missing / null values'
    elif primary_lit.value_type == 'integer':
        primary_label = f'The number {primary_lit.value}'
    elif primary_lit.value_type == 'float':
        primary_label = f'The number {primary_lit.value}'
    elif primary_lit.value_type == 'boolean':
        primary_label = f'Boolean {str(primary_lit.value).lower()}'
    else:
        primary_label = f'The text "{primary_lit.value}"'

    if primary_exists and ambiguous_options:
        # Both exist. Return ambiguity!
        options = [{'label': primary_label, 'value_info': primary_lit.to_dict()}] + ambiguous_options
        return primary_lit, options
    elif ambiguous_options and not primary_exists:
        # Only the alternative string exists.
        # Just use it directly instead of bothering the user.
        return TypedLiteral.from_dict(ambiguous_options[0]['value_info']), []
        
    # Either only primary exists, or neither exists (in which case mismatch fallback handles it)
    return primary_lit, []

class ValueAmbiguityClarificationRequired(Exception):
    def __init__(self, message: str, operation_payload: dict, ambiguous_options: List[dict]):
        super().__init__(message)
        self.operation_payload = operation_payload
        self.ambiguous_options = ambiguous_options


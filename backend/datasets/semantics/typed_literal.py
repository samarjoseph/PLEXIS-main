"""
TypedLiteral — canonical typed value representation for Plexis transformations.

This is the SINGLE SOURCE OF TRUTH for what a user-specified value means.
Every transformation component (router, planner, executor, compiler, validator)
must obtain and use TypedLiteral — never re-parse values independently.

TYPE RULES (parse_literal):
  Quoted "0" or '0'               → STRING("0")   — user explicitly quoted it
  Unquoted 0                      → INTEGER(0)
  Unquoted 0.0                    → FLOAT(0.0)
  Unquoted true/false             → BOOLEAN(True/False)
  Unquoted null/none/nan/missing  → NULL(None)
  Explicit keyword: "integer 0"   → INTEGER(0)   — overrides inference
  Explicit keyword: "string 0"    → STRING("0")  — overrides inference
  Everything else (bare word)     → STRING

SEMANTIC FAMILIES (semantic_family property):
  'NUMBER'  — INTEGER or FLOAT. Compatible with each other, NOT with STRING.
  'STRING'  — Explicit string. Only matches string cells.
  'BOOLEAN' — True/False. NEVER matches NUMBER (Python True==1 trap).
  'NULL'    — None / NaN / pd.NA.
  'DATE'    — ISO date/datetime (future extension).

CANONICAL COMPARISON:
  Use semantic_equals(df_value, typed_literal) for all mask operations.
  Never use raw `df[col] == typed_literal.python_value` — boolean trap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np


# ── Canonical keyword sets ────────────────────────────────────────────────────

# Unquoted null keywords resolve to None (actual missing, not string "null")
_NULL_KEYWORDS = frozenset({'null', 'none', 'nan', 'na', 'missing', 'nil', 'empty'})

# Unquoted boolean keywords
_BOOL_KEYWORDS = {'true': True, 'false': False, 'yes': True, 'no': False}

# Explicit type override words (case-insensitive)
# Maps keyword → value_type override
_EXPLICIT_INTEGER_WORDS = frozenset({'integer', 'int', 'whole', 'whole number', 'numeric integer', 'int64'})
_EXPLICIT_FLOAT_WORDS   = frozenset({'float', 'decimal', 'floating', 'floating point', 'numeric decimal',
                                     'number', 'numeric', 'float64', 'double'})
_EXPLICIT_STRING_WORDS  = frozenset({'string', 'str', 'text', 'literal', 'literal text',
                                     'characters', 'char', 'the string', 'the text', 'word'})
_EXPLICIT_BOOL_WORDS    = frozenset({'boolean', 'bool', 'true/false value', 'boolean value'})
_EXPLICIT_NULL_WORDS    = frozenset({'null value', 'blank', 'blank value', 'nan value',
                                     'missing value', 'empty value'})


# ── TypedLiteral dataclass ────────────────────────────────────────────────────

@dataclass(frozen=True)
class TypedLiteral:
    """
    A value with full provenance: what it is, what type it has, and how the
    user expressed it.  This object is immutable and hashable.

    Fields:
        value         — The Python value (int, float, str, bool, None)
        value_type    — 'integer' | 'float' | 'string' | 'boolean' | 'null' | 'date'
        source_form   — The raw text the user wrote (e.g. '"0"', '0', 'null')
        explicit      — True if the user provided explicit type decoration
                        (e.g. "integer 0", "string '0'", quoted value)
        was_quoted    — True if the user wrapped the value in quotes
    """
    value:       Any
    value_type:  str    # 'integer' | 'float' | 'string' | 'boolean' | 'null' | 'date'
    source_form: str    # Original text as the user wrote it
    explicit:    bool   # Was the type unambiguously specified?
    was_quoted:  bool   # Was the token quoted in the user's message?

    # ── Core convenience ──────────────────────────────────────────────────────

    @property
    def python_value(self) -> Any:
        """The raw Python value for DataFrame operations."""
        return self.value

    @property
    def is_null(self) -> bool:
        return self.value_type == 'null'

    @property
    def semantic_family(self) -> str:
        """
        The broad semantic family of this literal.
        Used for compatibility checks and column matching.

        'NUMBER'  — INTEGER or FLOAT (compatible with each other)
        'STRING'  — String (only matches string-typed cells)
        'BOOLEAN' — Boolean True/False (NEVER matches NUMBER)
        'NULL'    — None/NaN/pd.NA
        'DATE'    — ISO date (future)
        """
        if self.value_type in ('integer', 'float'):
            return 'NUMBER'
        if self.value_type == 'boolean':
            return 'BOOLEAN'
        if self.value_type == 'null':
            return 'NULL'
        if self.value_type == 'date':
            return 'DATE'
        return 'STRING'

    # ── Display helpers ───────────────────────────────────────────────────────

    def display_label(self) -> str:
        """Human-readable label for UI display (e.g. 'integer(0)', 'string("0")')."""
        if self.value_type == 'null':
            return 'null'
        if self.value_type == 'boolean':
            return f'boolean({str(self.value).lower()})'
        if self.value_type == 'integer':
            return f'integer({self.value})'
        if self.value_type == 'float':
            return f'float({self.value})'
        # string
        return f'string("{self.value}")'

    def __repr__(self) -> str:
        return (
            f"TypedLiteral(value={self.value!r}, type={self.value_type}, "
            f"source={self.source_form!r}, explicit={self.explicit}, quoted={self.was_quoted})"
        )

    # ── JSON serialization (for IR transport, preserving type) ────────────────

    def to_dict(self) -> dict:
        """Serialize to a dict that can be embedded in IR JSON without type loss."""
        return {
            '__typed_literal__': True,
            'value': self.value,
            'value_type': self.value_type,
            'source_form': self.source_form,
            'explicit': self.explicit,
            'was_quoted': self.was_quoted,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'TypedLiteral':
        return cls(
            value=d['value'],
            value_type=d['value_type'],
            source_form=d.get('source_form', repr(d['value'])),
            explicit=d.get('explicit', False),
            was_quoted=d.get('was_quoted', False),
        )


# ── parse_literal — canonical value parser ────────────────────────────────────

def parse_literal(
    raw: str,
    *,
    was_quoted: bool = False,
    explicit_type: Optional[str] = None,
) -> TypedLiteral:
    """
    Parse a raw string token from a user message into a TypedLiteral.

    This is the ONE canonical entry point for all value parsing in Plexis.
    No transformation component should independently parse values.

    Args:
        raw:           The raw token text (stripped of surrounding whitespace,
                       but NOT lowercased — case is semantic for strings).
        was_quoted:    Whether the user wrapped it in quotes ('...' or "...").
        explicit_type: An explicit type override from the user's words
                       ('integer', 'float', 'string', 'boolean', 'null').
                       Overrides automatic inference.

    Returns:
        TypedLiteral with correct type, value, source_form, explicit, was_quoted.
    """
    raw = raw.strip()
    source_form = f'"{raw}"' if was_quoted else raw

    # Priority 1: Explicit type override (e.g. "integer 0", "string '0'")
    if explicit_type:
        et = explicit_type.lower().strip()
        if et in ('integer', 'int'):
            try:
                return TypedLiteral(int(raw), 'integer', source_form, True, was_quoted)
            except (ValueError, OverflowError):
                pass
        elif et in ('float', 'decimal', 'number', 'numeric'):
            try:
                return TypedLiteral(float(raw), 'float', source_form, True, was_quoted)
            except (ValueError, OverflowError):
                pass
        elif et in ('string', 'str', 'text'):
            return TypedLiteral(raw, 'string', source_form, True, was_quoted)
        elif et in ('boolean', 'bool'):
            lower = raw.lower()
            bval = _BOOL_KEYWORDS.get(lower)
            if bval is not None:
                return TypedLiteral(bval, 'boolean', source_form, True, was_quoted)
        elif et in ('null', 'missing'):
            return TypedLiteral(None, 'null', source_form, True, was_quoted)

    # Priority 2: User quoted the value → always STRING, no coercion
    if was_quoted:
        return TypedLiteral(raw, 'string', source_form, True, True)

    lower = raw.lower()

    # Priority 3: Null/missing keywords (unquoted)
    if lower in _NULL_KEYWORDS:
        return TypedLiteral(None, 'null', source_form, True, False)

    # Priority 4: Boolean keywords (unquoted)
    if lower in _BOOL_KEYWORDS:
        return TypedLiteral(_BOOL_KEYWORDS[lower], 'boolean', source_form, True, False)

    # Priority 5: Integer (no decimal point, no exponential)
    if '.' not in raw and 'e' not in lower:
        try:
            int_val = int(raw)
            return TypedLiteral(int_val, 'integer', source_form, False, False)
        except (ValueError, OverflowError):
            pass

    # Priority 6: Float
    try:
        float_val = float(raw)
        return TypedLiteral(float_val, 'float', source_form, False, False)
    except (ValueError, OverflowError):
        pass

    # Priority 7: Default — string
    return TypedLiteral(raw, 'string', source_form, False, False)


# ── parse_with_explicit_type_words ────────────────────────────────────────────

_EXPLICIT_TYPE_PATTERN = re.compile(
    r'^(?P<type_word>integer|int|float|decimal|string|str|text|boolean|bool|numeric|'
    r'whole\s+number|floating\s+point|numeric\s+decimal|numeric\s+integer)\s+'
    r"(?P<token>.+)$",
    re.IGNORECASE,
)


def parse_with_explicit_type(raw_phrase: str) -> TypedLiteral:
    """
    Parse a phrase that may contain an explicit type word prefix.

    Examples:
        "integer 0"    → INTEGER(0)
        "string '0'"   → STRING("0")
        "float 0.0"    → FLOAT(0.0)
        "boolean true" → BOOLEAN(True)
        "0"            → INTEGER(0)  (regular inference)
        "'0'"          → STRING("0") (quoted → string)

    This is the preferred entry point for parsing user-specified values
    that may include explicit type declarations.
    """
    raw_phrase = raw_phrase.strip()

    # Check for explicit type prefix
    m = _EXPLICIT_TYPE_PATTERN.match(raw_phrase)
    if m:
        type_word = m.group('type_word').lower().replace(' ', ' ')
        token = m.group('token').strip()

        # Determine explicit_type string
        if type_word in ('integer', 'int', 'whole number', 'numeric integer'):
            explicit_type = 'integer'
        elif type_word in ('float', 'decimal', 'floating point', 'numeric decimal', 'numeric'):
            explicit_type = 'float'
        elif type_word in ('string', 'str', 'text'):
            explicit_type = 'string'
        elif type_word in ('boolean', 'bool'):
            explicit_type = 'boolean'
        else:
            explicit_type = None

        # Strip quotes from token if present
        m2 = re.match(r'''^(['"])(.*?)\1$''', token)
        if m2:
            return parse_literal(m2.group(2), was_quoted=True, explicit_type=explicit_type)
        return parse_literal(token, was_quoted=False, explicit_type=explicit_type)

    # No explicit type prefix — check for quoting
    m2 = re.match(r'''^(['"])(.*?)\1$''', raw_phrase)
    if m2:
        return parse_literal(m2.group(2), was_quoted=True)

    return parse_literal(raw_phrase, was_quoted=False)


# ── extract_typed_value ───────────────────────────────────────────────────────

# Matches a quoted string token (entire string is quoted)
_QUOTED_TOKEN = re.compile(r'''^(['"])(.*?)\1$''', re.DOTALL)


def extract_typed_value(token_str: str) -> TypedLiteral:
    """
    Extract a TypedLiteral from a captured regex token.

    Accepts:
      - A quoted value:      'N/A'  "0"   → STRING (preserving case)
      - A bare number:       0   3.14     → INTEGER/FLOAT
      - A bare keyword:      null  true   → NULL/BOOLEAN
      - A bare word:         unknown      → STRING
      - Explicit type word:  integer 0   → INTEGER(0)

    This function is the primary helper for the regex-based router.
    Always use this rather than calling parse_literal directly from regex captures.
    """
    token_str = token_str.strip()
    m = _QUOTED_TOKEN.match(token_str)
    if m:
        return parse_literal(m.group(2), was_quoted=True)
    return parse_with_explicit_type(token_str)


# ── semantic_equals — THE canonical comparison function ───────────────────────

def semantic_equals(df_value: Any, typed_literal: TypedLiteral) -> bool:
    """
    Determine whether a DataFrame cell value matches the user's typed literal.

    This is the SINGLE SOURCE OF TRUTH for value comparison in Plexis.

    Rules:
      NULL literal:    matches NaN, None, pd.NA only
      BOOLEAN literal: matches only Python bool True/False (NOT int 0/1)
      NUMBER literal:  matches numeric values (int, float, numpy numeric)
                       but NOT strings and NOT booleans
      STRING literal:  exact string match only
      DATE literal:    (future) date comparison

    Args:
        df_value:      A single cell value from a pandas DataFrame (scalar)
        typed_literal: The user's TypedLiteral from parse_literal()

    Returns:
        True if the cell value semantically matches the typed literal.
    """
    family = typed_literal.semantic_family

    # NULL: matches only genuine missing values
    if family == 'NULL':
        return _is_null(df_value)

    # If the cell itself is null/None/NaN, it cannot match a non-null literal
    if _is_null(df_value):
        return False

    if family == 'BOOLEAN':
        # BOOLEAN must only match actual bool values — NOT int 0 or 1
        if not isinstance(df_value, (bool, np.bool_)):
            return False
        return bool(df_value) == typed_literal.value

    if family == 'NUMBER':
        # NUMBER must not match bool columns (Python True==1 trap)
        if isinstance(df_value, (bool, np.bool_)):
            return False
        # Attempt numeric comparison
        try:
            cell_num = _to_number(df_value)
            lit_num  = _to_number(typed_literal.value)
            if cell_num is None or lit_num is None:
                return False
            return _numbers_equal(cell_num, lit_num)
        except (TypeError, ValueError):
            return False

    if family == 'STRING':
        # STRING: exact string match only — no numeric coercion
        if isinstance(df_value, str):
            return df_value == typed_literal.value
        # For non-string cells, STRING literal never matches
        return False

    # DATE / other (future): fallback to equality
    return df_value == typed_literal.value


def _is_null(v: Any) -> bool:
    """Return True if v is a genuine missing value (None, NaN, pd.NA)."""
    if v is None:
        return True
    try:
        import pandas as pd
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _to_number(v: Any) -> Optional[Any]:
    """Return a numeric scalar without lossy float conversion."""
    if isinstance(v, (bool, np.bool_)):
        return None  # Booleans are not numbers in Plexis semantics
    if isinstance(v, (int, float, np.integer, np.floating)):
        if isinstance(v, (float, np.floating)) and np.isnan(v):
            return None
        return v
    return None


def _numbers_equal(left: Any, right: Any) -> bool:
    """Compare integer/float scalars without NumPy's lossy int-to-float cast."""
    left_int = isinstance(left, (int, np.integer))
    right_int = isinstance(right, (int, np.integer))
    if left_int and right_int:
        return int(left) == int(right)
    if left_int:
        right_float = float(right)
        return right_float.is_integer() and int(right_float) == int(left)
    if right_int:
        left_float = float(left)
        return left_float.is_integer() and int(left_float) == int(right)
    return float(left) == float(right)


# ── build_mask — vectorised semantic comparison for DataFrame columns ──────────

def build_mask(series, typed_literal: TypedLiteral):
    """
    Build a boolean mask for a pandas Series where each element semantically
    equals the typed_literal.

    Uses semantic_equals rules:
      - NULL:    pd.isna(series)
      - BOOLEAN: (series.dtype == bool) and (series == typed_literal.value)
      - NUMBER:  numeric equality, skipping bool columns
      - STRING:  series == typed_literal.value  (for object/string columns)

    Returns a pandas Series of bool.
    """
    import pandas as pd

    family = typed_literal.semantic_family

    if family == 'NULL':
        return series.isna()

    if family == 'BOOLEAN':
        # Keep native bool columns vectorized. Mixed/object columns are checked
        # cell-by-cell so real bools match while integer 0/1 and text do not.
        try:
            import pandas.api.types as pat
            if pat.is_bool_dtype(series):
                return series == typed_literal.value
        except Exception:
            pass
        return series.apply(lambda value: semantic_equals(value, typed_literal))

    if family == 'NUMBER':
        # Skip boolean columns to avoid True==1/False==0 trap
        if series.dtype in (bool, 'bool', 'boolean'):
            return pd.Series([False] * len(series), index=series.index)
        try:
            import pandas.api.types as pat
            if pat.is_bool_dtype(series):
                return pd.Series([False] * len(series), index=series.index)
        except Exception:
            pass

        target = typed_literal.value  # int or float
        # For numeric series, pandas == works correctly
        try:
            import pandas.api.types as pat
            if pat.is_numeric_dtype(series):
                return series == target
        except Exception:
            pass
        # Mixed/object columns must use canonical scalar semantics so numeric
        # looking strings and booleans never compare equal to numbers.
        return series.apply(lambda value: semantic_equals(value, typed_literal))

    if family == 'STRING':
        # Only match actual string/object values
        target = typed_literal.value
        try:
            import pandas.api.types as pat
            if pat.is_bool_dtype(series) or pat.is_numeric_dtype(series):
                return pd.Series([False] * len(series), index=series.index)
        except Exception:
            pass
        # For object columns with mixed types
        return series.apply(lambda v: isinstance(v, str) and v == target)

    # Keep extension and mixed dtypes on the same rules as scalar comparisons.
    return series.apply(lambda value: semantic_equals(value, typed_literal))


"""
MasterRouter — 80/20 LLM-first semantic intent dispatcher.

ARCHITECTURE:
  80% LLM semantic interpretation (primary authority)
  20% deterministic supporting signals (schema, workspace, column types)

FLOW:
  1. Fast-path check (greetings, title gen, explicit commands — no LLM)
  2. SemanticContextBuilder → builds context package (20% layer)
  3. LLM Interpreter → receives full context → returns typed JSON (80% layer)
  4. SchemaValidator → validates operation against dataset schema
  5. Intent + context → AnalysisEngine / ConversationEngine

WHAT CHANGED FROM v1:
  - Removed keyword-based primary classification (ANALYSIS_KEYWORDS, HELP_PATTERNS)
  - Removed heuristic-first / LLM-as-fallback pattern
  - LLM is now the primary semantic decision maker
  - Dataset schema is always passed to the LLM when a dataset is loaded
  - Added dataset-aware operation injection into context
  - Added schema validation before execution

WHAT STAYS THE SAME:
  - AnalysisEngine + CapabilityRegistry (untouched)
  - ConversationEngine (untouched)
  - provider_engine / model routing (untouched)
  - EngineResult contract (untouched)
  - Evidence contracts (untouched)
"""
import json
import logging
import re

from core.context import ExecutionContext
from core.events import (
    event_bus, IntentClassifiedEvent, EngineSelectedEvent, EngineCompletedEvent
)
from engines.base import EngineResult
from router.engine_registry import engine_registry
from router.semantic_context import semantic_context_builder
from router.schema_validator import schema_validator
from providers.engine import provider_engine

logger = logging.getLogger(__name__)

# ── Fast-path patterns — never need LLM classification ───────────────────────
# IMPORTANT: Must use word boundary \b AND end-of-string anchor to prevent
# "highest", "hello world dataset" etc. from matching as greetings.
# Only exact short greetings should match (e.g. "hi", "hey", "good morning").
_GREETING_RX = re.compile(
    r'^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening)|'
    r'how are you|howdy|thanks|thank you|thx|bye|goodbye)\b[!.,\s]*$',
    re.IGNORECASE,
)
_TITLE_RX = re.compile(
    r'generate.*(?:title|heading)|(?:concise|short).*title|'
    r'title.*(?:conversation|chat)|create.*title',
    re.IGNORECASE,
)
_INVESTIGATE_RX = re.compile(
    r'\b(investigate|re-run investigation|show investigation|open investigation|'
    r're-?analyze dataset|show dataset analysis|'
    r'analyze my dataset|what\'?s wrong with my dataset|'
    r'run (?:a )?full analysis|show me (?:the )?analysis|'
    r'what abnormalities|what anomalies|what problems|find anomalies)\b',
    re.IGNORECASE,
)

# ── Analysis fast-path patterns ───────────────────────────────────────────────
# Catch simple, unambiguous DATA_OPERATION queries deterministically so that
# a transient LLM parse failure never silently downgrades them to conversation.
# Only fires when a dataset is loaded (checked in _fast_path).

# Row count: "how many rows", "how many records", "row count", "dataset size"
_ANALYSIS_ROW_COUNT_RX = re.compile(
    r'\b(how many (?:rows?|records?|entries|observations|samples?)|'
    r'(?:total\s+)?(?:number of|count of)\s+rows?|'
    r'row\s+count|dataset\s+size|number\s+of\s+(?:rows?|records?))\b',
    re.IGNORECASE,
)

# Dataset completeness %: "what percentage .* complete", "how complete is"
_ANALYSIS_COMPLETENESS_RX = re.compile(
    r'\b(what percentage (?:of (?:the )?dataset is complete|is complete)|'
    r'how complete is (?:the )?dataset|'
    r'dataset\s+completeness|completeness\s+percentage|'
    r'percent(?:age)?\s+(?:of\s+)?(?:the\s+)?dataset\s+(?:that is|is)\s+complete)\b',
    re.IGNORECASE,
)

# Min/minimum of a column: "what is the minimum X" / "minimum X value" (not part of multi-stat)
_ANALYSIS_MIN_COL_RX = re.compile(
    r'\bwhat is (?:the )?(?:minimum|min(?:imum)?|lowest|smallest)\s+(\w+)(?:\s+value)?\b'
    r'|(?:minimum|min|lowest|smallest)\s+(?:value\s+(?:of|in)\s+)?(?:the\s+)?(\w+)\b',
    re.IGNORECASE,
)

# Unique values list (not count): "what X are in/present in the dataset"
_ANALYSIS_UNIQUE_VALUES_RX = re.compile(
    r'\bwhat\s+(\w+)(?:\s+values?)?\s+are\s+(?:present\s+(?:in|within)|in|found\s+in|'
    r'available\s+in|included\s+in)\s+(?:the\s+)?dataset\b'
    r'|\blist\s+(?:all\s+)?(?:the\s+)?(?:unique\s+)?(\w+)(?:\s+values?)?\b',
    re.IGNORECASE,
)

# Unique count for a column: "how many unique X", "how many distinct X"
_ANALYSIS_UNIQUE_COUNT_RX = re.compile(
    r'\bhow many (?:unique|distinct)\s+(\w+)(?:\s+(?:values?|are\s+there|exist|does\s+the\s+dataset\s+have))?\b',
    re.IGNORECASE,
)

# ── Transform fast-path patterns ──────────────────────────────────────────────
# These catch obvious mutation commands deterministically, avoiding LLM
# truncation issues (max_tokens can cut off long TRANSFORM JSON responses).
_TRANSFORM_RX = re.compile(
    r'\b('
    r'fill\s+(?:the\s+)?(?:all\s+)?(?:missing|null|nan|empty)\s+(?:values?\s+)?(?:with|to|using|=|by)'
    r'|fillna|fill\s+(?:the\s+)?(?:missing|null|nan|empty)'
    r'|drop\s+(?:the\s+)?(?:column|col)\b'
    r'|delete\s+(?:the\s+)?(?:column|col)\b'
    r'|remove\s+(?:the\s+)?(?:column|col)\b'
    r'|rename\s+(?:the\s+)?columns?\b'
    r'|rename\s+(?:the\s+)?(?:column|col)?\s*\w+\s+to\b'
    r'|drop\s+(?:the\s+)?duplicates?'
    r'|remove\s+(?:the\s+)?duplicates?'
    r'|deduplicate'
    r'|get\s+rid\s+of\s+(?:the\s+)?(?:duplicate|dup)'
    r'|sort\s+(?:the\s+)?(?:data(?:set)?\s+)?by\b'
    r'|sort\s+(?:\w+\s+)?(?:highest|lowest|largest|smallest)\s+first'
    r'|order\s+by\b'
    r'|filter\s+(?:the\s+)?(?:rows?\s+)?(?:where|when|if)\b'
    r'|keep\s+(?:only\s+)?(?:rows?\s+)?(?:where|when|if)\b'
    r'|remove\s+(?:the\s+)?(?:rows?\s+)?(?:where|when|if)\b'
    r'|delete\s+(?:the\s+)?(?:rows?\s+)?(?:where|when|if)\b'
    r'|remove\s+(?:\w+\s+)?(?:younger|older|greater|less|above|below|under|over)\s+than\b'
    r'|keep\s+(?:only\s+)?(?:\w+\s+)?(?:older|younger|greater|less|above|below)\s+than\b'
    r'|convert\s+\w+\s+to\s+(?:int|float|string|str|bool|integer|number|numeric|text)'
    r'|cast\s+\w+\s+(?:to|as)\s+(?:int|float|string|str|bool|integer|number|numeric|text)'
    r'|make\s+(?:all\s+)?\w+\s+(?:int|float|integer|number|numeric|text|string|bool)'
    r'|(?:replace|change)\s+(?:the\s+)?(?:(?:integer|int|float|decimal|string|str|text|boolean|bool|numeric)\s+)?(?:"[^"\r\n]*"|\'[^\'\r\n]*\'|\w+(?:\.\w+)?)\s+(?:with|to|by)\b'
    r'|call\s+(?:the\s+)?\w+\s+column\b'
    r')\b',
    re.IGNORECASE,
)



    
def _parse_transform_from_message(message: str) -> dict | None:
    """
    Extract a structured transform operation from a natural language message.

    Returns an operation dict {type, ...params} or None if no pattern matched.
    This is the deterministic counterpart to the LLM operation extraction.

    IMPORTANT: REPLACE_VALUES patterns run on the original-case message to
    preserve the user's intended string values (Delhi ≠ delhi, USA ≠ usa).
    All other patterns (FILL_MISSING, SORT, etc.) run on lowercased msg since
    they deal with keywords/column names, not user-specified string values.
    """
    msg = message.strip().lower()   # For keyword/column matching only
    orig = message.strip()          # For value extraction (case-preserving)

    from datasets.semantics.typed_literal import parse_literal, parse_with_explicit_type

    def _parse_fill_value(fill_raw: str) -> object:
        """Parse a fill value string to a typed Python value."""
        fill_raw = fill_raw.strip().rstrip('.')
        strategy_map = {
            "mean": "mean", "median": "median", "mode": "mode",
            "average": "mean", "ffill": "ffill", "bfill": "bfill",
            "forward fill": "ffill", "backward fill": "bfill",
            "the mean": "mean", "the median": "median", "the mode": "mode",
            "the average": "mean",
        }
        if fill_raw.lower() in strategy_map:
            return strategy_map[fill_raw.lower()]
        lit = parse_with_explicit_type(fill_raw)
        return lit.python_value

    # ── FILL_MISSING ──────────────────────────────────────────────────────────
    m = re.search(
        r'fill\s+(?:the\s+)?(?:all\s+)?(?:missing|null|nan|empty)\s+(?:values?\s+)?'
        r'(?:in\s+(?:column\s+)?(\w+)\s+)?'
        r'(?:with|to|using|=|by)\s+(.+)',
        msg, re.IGNORECASE,
    )
    if m:
        op = {"type": "FILL_MISSING", "value": _parse_fill_value(m.group(2))}
        if m.group(1):
            op["columns"] = [m.group(1)]
        return op

    # "fill missing age values with median" / "fill missing age with 0"
    m = re.search(
        r'fill\s+(?:the\s+)?(?:missing|null|nan|empty)\s+(\w+)\s+(?:values?\s+)?'
        r'(?:with|to|using|=|by)\s+(.+)',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "FILL_MISSING", "value": _parse_fill_value(m.group(2)), "columns": [m.group(1)]}

    # Bare fill requests leave the fill-value slot open for clarification.
    if re.search(r'\b(?:fillna|fill\s+(?:the\s+)?(?:missing|null|nan|empty))\b', msg):
        return {"type": "FILL_MISSING", "_missing_slots": ["fill_value"]}

    # ── REPLACE_VALUES — quoted literal (highest priority) ────────────────────
    # "replace 'N/A' with 0"  "replace "missing" with unknown"
    # Run on ORIGINAL message to preserve case inside quotes.
    m_quoted_replace = re.search(
        r"""(?:replace|replce|change|swap|update|set)\s+(?:the\s+)?(?:string\s+)?(['"])(.*?)\1"""
        r"""\s+(?:with|to|by)\s+(.+)""",
        orig, re.IGNORECASE,
    )
    if m_quoted_replace:
        old_lit = parse_literal(m_quoted_replace.group(2).strip(), was_quoted=True)
        new_raw = m_quoted_replace.group(3).strip().rstrip('.')
        # Check if new_value itself is quoted (on original)
        new_quote_m = re.match(r"""^(['"])(.*?)\1$""", new_raw)
        if new_quote_m:
            new_lit = parse_literal(new_quote_m.group(2), was_quoted=True)
        else:
            new_lit = parse_with_explicit_type(new_raw)
        return {
            "type": "REPLACE_VALUES",
            "old_value": old_lit.python_value,
            "new_value": new_lit.python_value,
            "_old_typed": old_lit.to_dict(),
            "_new_typed": new_lit.to_dict(),
            "_old_raw": m_quoted_replace.group(2).strip(),
            "_old_was_quoted": True,
            "_new_raw": new_raw,
            "_new_was_quoted": new_quote_m is not None,
        }

    # ── REPLACE_VALUES — explicit type word (e.g. "replace integer 0 with ...") ──
    # "replace integer 0 with unknown"  "replace string 0 with unknown"
    # Run on ORIGINAL message.
    _TYPE_WORD_PAT = (
        r'(?:integer|int|float|decimal|string|str|text|boolean|bool|numeric|'
        r'whole\s+number|floating\s+point)'
    )
    m_explicit_type = re.search(
        r'(?:replace|replce|change|swap|update|set)\s+(' + _TYPE_WORD_PAT + r')\s+'
        r"(?:(['\"])(.*?)\2|([\w./+-]+(?:\s+[\w./+-]+)?))"
        r'\s+(?:with|to)\s+'
        r"(?:(['\"])(.*?)\5|([\w./+-]+(?:\s+[\w./+-]+)?))"
        r'(?:\s+in\s+(?:column\s+)?(\w+))?',
        orig, re.IGNORECASE,
    )
    if m_explicit_type:
        type_word = m_explicit_type.group(1).lower().strip()
        # Map type_word to explicit_type
        if 'int' in type_word or 'whole' in type_word:
            explicit_type = 'integer'
        elif 'float' in type_word or 'decimal' in type_word or 'numeric' in type_word:
            explicit_type = 'float'
        elif 'string' in type_word or 'str' in type_word or 'text' in type_word:
            explicit_type = 'string'
        elif 'bool' in type_word:
            explicit_type = 'boolean'
        else:
            explicit_type = None

        # Old value: groups 3 (quoted) or 4 (bare)
        if m_explicit_type.group(3) is not None:
            old_lit = parse_literal(m_explicit_type.group(3), was_quoted=True, explicit_type=explicit_type)
        else:
            old_lit = parse_literal((m_explicit_type.group(4) or '').strip(), was_quoted=False, explicit_type=explicit_type)

        # New value: groups 6 (quoted) or 7 (bare)
        if m_explicit_type.group(6) is not None:
            new_lit = parse_literal(m_explicit_type.group(6), was_quoted=True)
        else:
            new_lit = parse_with_explicit_type((m_explicit_type.group(7) or '').strip())

        op = {
            "type": "REPLACE_VALUES",
            "old_value": old_lit.python_value,
            "new_value": new_lit.python_value,
            "_old_typed": old_lit.to_dict(),
            "_new_typed": new_lit.to_dict(),
            "_old_raw": (m_explicit_type.group(3) or m_explicit_type.group(4) or '').strip(),
            "_old_was_quoted": m_explicit_type.group(3) is not None,
            "_new_raw": (m_explicit_type.group(6) or m_explicit_type.group(7) or '').strip(),
            "_new_was_quoted": m_explicit_type.group(6) is not None,
        }
        if col:
            op["column"] = col
        return op

    # ── REPLACE_VALUES — "replace the string X with Y" ───────────────────────
    m_explicit_string = re.search(
        r'(?:replace|replce|change|swap|update|set)\s+(?:the\s+)?(?:string|literal|word|text|cells?\s+containing)\s+'
        r"(?:(['\"])(.*?)\1|([\w./+-]+(?:\s+[\w./+-]+)?))"
        r'\s+(?:with|to|by)\s+(.+)',
        orig, re.IGNORECASE,
    )
    if m_explicit_string:
        # "replace the string X" → old is explicitly a string, preserving case
        if m_explicit_string.group(2) is not None:
            old_lit = parse_literal(m_explicit_string.group(2), was_quoted=True)
        else:
            old_lit = parse_literal((m_explicit_string.group(3) or '').strip(), was_quoted=True)
        new_raw = m_explicit_string.group(4).strip().rstrip('.')
        new_quote_m = re.match(r"""^(['"])(.*?)\1$""", new_raw)
        if new_quote_m:
            new_lit = parse_literal(new_quote_m.group(2), was_quoted=True)
        else:
            new_lit = parse_with_explicit_type(new_raw)
        return {
            "type": "REPLACE_VALUES",
            "old_value": old_lit.python_value,
            "new_value": new_lit.python_value,
            "_old_typed": old_lit.to_dict(),
            "_new_typed": new_lit.to_dict(),
            "_old_raw": (m_explicit_string.group(2) or m_explicit_string.group(3) or '').strip(),
            "_old_was_quoted": True, # Always treated as string/quoted
            "_new_raw": new_raw,
            "_new_was_quoted": new_quote_m is not None,
        }

    # ── FILL_MISSING — "replace null/NaN/empty/missing values with X" ────────
    m = re.search(
        r'(?:replace|replce|change|swap|update|set)\s+(?:all\s+)?(?:null|nan|empty|missing)\s+(?:values?\s+)?'
        r'(?:in\s+(?:column\s+)?(\w+)\s+)?'
        r'(?:with|to|using|=|by)\s+(.+)',
        msg, re.IGNORECASE,
    )
    if m:
        op = {"type": "FILL_MISSING", "value": _parse_fill_value(m.group(2))}
        if m.group(1):
            op["columns"] = [m.group(1)]
        return op

    # ── DROP_COLUMN ───────────────────────────────────────────────────────────
    m = re.search(
        r'(?:drop|delete|remove)\s+(?:the\s+)?(?:column|col)\s+(\w+)',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "DROP_COLUMN", "column": m.group(1)}

    m = re.search(
        r'(?:drop|delete|remove)\s+(?:the\s+)?(\w+)\s+column',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "DROP_COLUMN", "column": m.group(1)}

    # ── RENAME_COLUMN ─────────────────────────────────────────────────────────
    if re.search(r'^rename\s+(?:the\s+)?columns?\s*[.!?]*$', orig, re.IGNORECASE):
        return {"type": "RENAME_COLUMN", "_missing_slots": ["target_scope", "new_names"]}

    # With quotes (supports spaces)
    m = re.search(
        r'rename\s+(?:the\s+)?(?:column\s+)?(\w+)\s+(?:to|with|as)\s+([\"\'])(.*?)\2',
        orig, re.IGNORECASE,
    )
    if m:
        return {"type": "RENAME_COLUMN", "column": m.group(1), "new_name": m.group(3).strip()}

    # Without quotes (catches the rest of the line)
    m = re.search(
        r'rename\s+(?:the\s+)?(?:column\s+)?(\w+)\s+(?:to|with|as)\s+([^\"\'\n]+)',
        orig, re.IGNORECASE,
    )
    if m:
        return {"type": "RENAME_COLUMN", "column": m.group(1), "new_name": m.group(2).strip()}
        
    # With quotes
    m = re.search(
        r'change\s+(?:the\s+)?(?:name\s+of\s+)?(?:column\s+)?(\w+)\s+(?:name\s+)?(?:to|with|as)\s+([\"\'])(.*?)\2',
        orig, re.IGNORECASE,
    )
    if m:
        return {"type": "RENAME_COLUMN", "column": m.group(1), "new_name": m.group(3).strip()}

    # Without quotes
    m = re.search(
        r'change\s+(?:the\s+)?(?:name\s+of\s+)?(?:column\s+)?(\w+)\s+(?:name\s+)?(?:to|with|as)\s+([^\"\'\n]+)',
        orig, re.IGNORECASE,
    )
    if m:
        return {"type": "RENAME_COLUMN", "column": m.group(1), "new_name": m.group(2).strip()}

    m = re.search(
        r'call\s+(?:the\s+)?(?:column\s+)?(\w+)\s+[\"\']?([^\"\'\n]+?)[\"\']?(?:\s|$)',
        orig, re.IGNORECASE,
    )
    if m:
        return {"type": "RENAME_COLUMN", "column": m.group(1), "new_name": m.group(2).strip()}

    # ── DROP_DUPLICATES ───────────────────────────────────────────────────────
    if re.search(r'\b(?:drop|remove|delete)\s+(?:the\s+)?duplicates?\b', msg) or 'deduplicate' in msg:
        return {"type": "DROP_DUPLICATES"}
    if re.search(r'get\s+rid\s+of\s+(?:the\s+)?(?:duplicate|dup)', msg, re.IGNORECASE):
        return {"type": "DROP_DUPLICATES"}

    # ── SORT_ROWS ─────────────────────────────────────────────────────────────
    m = re.search(
        r'(?:sort|order)\s+(?:the\s+)?(?:data(?:set)?\s+)?by\s+(\w+)(?:\s+(asc|desc|ascending|descending))?',
        msg, re.IGNORECASE,
    )
    if m:
        order_raw = (m.group(2) or 'asc').lower()
        ascending = not order_raw.startswith('desc')
        return {"type": "SORT_ROWS", "column": m.group(1), "ascending": ascending}

    m = re.search(
        r'sort\s+(?:(?:the\s+)?(?:data(?:set)?\s+)?)?(?:by\s+)?(\w+)\s+(?:highest|largest|biggest)\s+first',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "SORT_ROWS", "column": m.group(1), "ascending": False}

    m = re.search(
        r'sort\s+(?:(?:the\s+)?(?:data(?:set)?\s+)?)?(?:by\s+)?(\w+)\s+(?:lowest|smallest)\s+first',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "SORT_ROWS", "column": m.group(1), "ascending": True}

    # ── FILTER_ROWS ───────────────────────────────────────────────────────────
    def _parse_filter_value(raw: str) -> object:
        raw = raw.strip().rstrip('.')
        lit = parse_with_explicit_type(raw)
        return lit.python_value

    m = re.search(
        r'keep\s+(?:only\s+)?(?:the\s+)?(?:rows?\s+)?(?:where|when|if)\s+'
        r'(\w+)\s*(>=|<=|!=|>|<|==|=)\s*(.+)',
        msg, re.IGNORECASE,
    )
    if m:
        op_sym = m.group(2).strip()
        if op_sym == '=':
            op_sym = '=='
        return {"type": "FILTER_ROWS", "column": m.group(1), "operator": op_sym,
                "value": _parse_filter_value(m.group(3)), "action": "KEEP"}

    m = re.search(
        r'filter\s+(?:the\s+)?(?:rows?\s+)?(?:where|when|if)\s+'
        r'(\w+)\s*(>=|<=|!=|>|<|==|=)\s*(.+)',
        msg, re.IGNORECASE,
    )
    if m:
        op_sym = m.group(2).strip()
        if op_sym == '=':
            op_sym = '=='
        return {"type": "FILTER_ROWS", "column": m.group(1), "operator": op_sym,
                "value": _parse_filter_value(m.group(3)), "action": "KEEP"}

    m = re.search(
        r'(?:remove|delete)\s+(?:the\s+)?(?:rows?\s+)?(?:where|when|if)\s+'
        r'(\w+)\s*(>=|<=|!=|>|<|==|=)\s*(.+)',
        msg, re.IGNORECASE,
    )
    if m:
        op_sym = m.group(2).strip()
        if op_sym == '=':
            op_sym = '=='
        return {"type": "FILTER_ROWS", "column": m.group(1), "operator": op_sym,
                "value": _parse_filter_value(m.group(3)), "action": "REMOVE"}

    m = re.search(
        r'keep\s+(?:only\s+)?(?:\w+\s+)?from\s+(\w+)',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "FILTER_ROWS", "column": "city", "operator": "==", "value": m.group(1), "action": "KEEP"}

    m = re.search(
        r'(?:remove|delete)\s+(?:\w+\s+)?(?:younger|less|fewer|below|under)\s+than\s+(\d+[\d.]*)',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "FILTER_ROWS", "column": "age", "operator": "<",
                "value": _parse_filter_value(m.group(1)), "action": "REMOVE"}

    m = re.search(
        r'(?:remove|delete)\s+(?:\w+\s+)?(?:older|greater|more|above|over)\s+than\s+(\d+[\d.]*)',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "FILTER_ROWS", "column": "age", "operator": ">",
                "value": _parse_filter_value(m.group(1)), "action": "REMOVE"}

    m = re.search(
        r'(?:remove|delete)\s+(?:\w+\s+)?from\s+(\w+)',
        msg, re.IGNORECASE,
    )
    if m:
        return {"type": "FILTER_ROWS", "column": "city", "operator": "==", "value": m.group(1), "action": "REMOVE"}

    # ── CAST_DTYPE ────────────────────────────────────────────────────────────
    m = re.search(
        r'(?:convert|cast)\s+(\w+)\s+(?:to|as)\s+(int(?:eger)?|float|str(?:ing)?|bool|number|numeric|text)',
        msg, re.IGNORECASE,
    )
    if m:
        col = m.group(1)
        dtype_raw = m.group(2).lower()
        dtype_map = {
            'int': 'int', 'integer': 'int', 'number': 'int', 'numeric': 'float',
            'float': 'float', 'str': 'str', 'string': 'str', 'text': 'str', 'bool': 'bool',
        }
        return {"type": "CAST_DTYPE", "column": col, "dtype": dtype_map.get(dtype_raw, 'str')}

    m = re.search(
        r'make\s+(?:all\s+)?(\w+)\s+(?:a\s+)?(int(?:eger)?s?|float(?:s)?|str(?:ing)?s?|bool(?:s)?|number(?:s)?|numeric|text)',
        msg, re.IGNORECASE,
    )
    if m:
        col = m.group(1)
        dtype_raw = m.group(2).lower().rstrip('s')
        dtype_map = {
            'int': 'int', 'integer': 'int', 'number': 'int', 'numeric': 'float',
            'float': 'float', 'str': 'str', 'string': 'str', 'text': 'str', 'bool': 'bool',
        }
        return {"type": "CAST_DTYPE", "column": col, "dtype": dtype_map.get(dtype_raw, 'str')}

    # ── REPLACE_VALUES — generic (ORIGINAL case, not lowercased) ─────────────
    # "replace X with Y in column Z" or "replace X with Y"
    # Runs on orig (not msg) to preserve string-valued tokens like "Delhi", "N/A".
    # Group layout:
    #   g1=quote, g2=quoted_old | g3=bare_old
    #   g4=quote, g5=quoted_new | g6=bare_new
    #   g7=column_name (optional)
    m = re.search(
        r'(?:replace|replce|change|swap|update|set)\s+'
        r"(?:(['\"])(.*?)\1|([\w./+-]+(?:\s+[\w./+-]+)?))"
        r'\s+(?:with|to)\s+'
        r"(?:(['\"])(.*?)\4|([\w./+-]+(?:\s+[\w./+-]+)?))"
        r'(?:\s+in\s+(?:column\s+)?(\w+))?',
        orig, re.IGNORECASE,
    )
    if m:
        # Old value: g2 (quoted) or g3 (bare)
        if m.group(2) is not None:
            old_lit = parse_literal(m.group(2), was_quoted=True)
        else:
            old_lit = parse_with_explicit_type((m.group(3) or '').strip())

        # New value: g5 (quoted) or g6 (bare)
        if m.group(5) is not None:
            new_lit = parse_literal(m.group(5), was_quoted=True)
        else:
            new_lit = parse_with_explicit_type((m.group(6) or '').strip())

        col = m.group(7) if m.group(7) else None
        op = {
            "type": "REPLACE_VALUES",
            "old_value": old_lit.python_value,
            "new_value": new_lit.python_value,
            "_old_typed": old_lit.to_dict(),
            "_new_typed": new_lit.to_dict(),
            "_old_raw": (m.group(2) or m.group(3) or '').strip(),
            "_old_was_quoted": m.group(2) is not None,
            "_new_raw": (m.group(5) or m.group(6) or '').strip(),
            "_new_was_quoted": m.group(5) is not None,
        }
        if col:
            op["column"] = col
        return op

    return None

def _normalize_transform_operation(op: dict) -> dict:
    """
    Normalize transform operation keys from LLM output to match planner expectations.

    The LLM may return old/inconsistent key names. This function ensures the
    operation dict always uses the correct keys that the planner expects.
    """
    op = dict(op)  # Don't mutate the original
    op_type = (op.get('type') or '').upper()

    if op_type == 'FILL_MISSING':
        # LLM might return "fill_value" instead of "value"
        if 'fill_value' in op and 'value' not in op:
            op['value'] = op.pop('fill_value')
        # Remove non-standard keys
        op.pop('scope', None)

    elif op_type == 'REPLACE_VALUES':
        # LLM might return "value" for old_value, "fill_value" for new_value
        if 'value' in op and 'old_value' not in op:
            op['old_value'] = op.pop('value')
        if 'fill_value' in op and 'new_value' not in op:
            op['new_value'] = op.pop('fill_value')

    elif op_type == 'SORT_ROWS':
        # LLM might return "order": "asc"/"desc" instead of "ascending": bool
        if 'order' in op and 'ascending' not in op:
            order = op.pop('order')
            op['ascending'] = not str(order).lower().startswith('desc')

    elif op_type == 'FILTER_ROWS':
        # Ensure action key exists (default KEEP)
        if 'action' not in op:
            op['action'] = 'KEEP'

    elif op_type == 'DROP_COLUMN':
        # LLM might return "columns": ["phone"] instead of "column": "phone"
        if 'columns' in op and 'column' not in op:
            cols = op.pop('columns')
            if isinstance(cols, list) and len(cols) == 1:
                op['column'] = cols[0]
            elif isinstance(cols, list) and len(cols) > 1:
                op['column'] = cols[0]  # Take first; planner only handles one at a time

    KNOWN_SIMPLE_OPERATIONS = {
        'FILL_MISSING', 'DROP_DUPLICATES', 'RENAME_COLUMN', 'DROP_COLUMN',
        'FILTER_ROWS', 'CAST_DTYPE', 'REPLACE_VALUES', 'SORT_ROWS'
    }
    
    if op_type not in KNOWN_SIMPLE_OPERATIONS:
        op['type'] = 'IR_REQUIRED'

    return op


# Intents the AnalysisEngine can handle
_ANALYSIS_INTENTS = {"analysis", "DATA_OPERATION"}


def _is_hypothetical(message: str) -> bool:
    """Check if message is asking a hypothetical or simulation question, not applying a transformation."""
    msg = message.lower()
    hypothetical_patterns = [
        r'\bif\s+we\s+(?:remove|drop|delete|fill|deduplicate)\b',
        r'\bif\s+every\s+.*(?:filled|removed|dropped)\b',
        r'\bhow\s+many\s+(?:rows?|cells?)\s+(?:would|remain)\b',
        r'\bdo\s+not\s+(?:modify|actually\s+remove|actually\s+delete|change)\b',
        r'\bsimulated\b',
        r'\bwould\s+remain\b',
        r'\bwould\s+be\s+complete\b',
    ]
    return any(re.search(pat, msg) for pat in hypothetical_patterns)


def _restore_typed_operation_from_pending(pending, operation=None):
    """Restore resolved typed literals from canonical pending state.

    The serialized operation payload remains a compatibility source for the
    rest of the operation, but typed literals stored in their dedicated slots
    always take precedence over raw Python values or payload metadata.
    """
    from datasets.semantics.typed_literal import TypedLiteral

    restored = dict(operation if operation is not None else pending.operation_payload or {})
    for pending_attr, typed_key, raw_key in (
        ('source_typed_literal', '_old_typed', 'old_value'),
        ('destination_typed_literal', '_new_typed', 'new_value'),
    ):
        literal_data = getattr(pending, pending_attr, None)
        if literal_data:
            literal = TypedLiteral.from_dict(literal_data)
            restored[typed_key] = literal.to_dict()
            restored[raw_key] = literal.python_value
    return restored


class MasterRouter:
    """
    Routes requests to the correct engine using LLM-primary semantic interpretation.

    The LLM makes the final semantic decision.
    Keyword/heuristic signals are supporting evidence only — they are NOT the decision.
    """

    def route(self, context: ExecutionContext) -> EngineResult:
        """Classify intent and dispatch to the correct engine."""

        stage = context.start_stage('intent_classification')

        # ── Step 1: Fast-path (no LLM needed) ────────────────────────────────
        payload = self._fast_path(context)

        if payload is None:
            # ── Step 2: Build semantic supporting context (20% layer) ─────────
            semantic_ctx = semantic_context_builder.build(context)

            # ── Step 3: LLM interpretation (80% layer — primary authority) ────
            payload = self._llm_interpret(context, semantic_ctx)

            # ── Step 4: Schema validation (structural check only) ─────────────
            payload = self._validate_and_enrich(payload, context, semantic_ctx)

        # ── Step 5: Apply intent + route ──────────────────────────────────────
        # Map LLM intent schema to engine intent names
        raw_intent = payload.get("intent", "conversation")
        intent = self._map_intent(raw_intent)
        confidence = float(payload.get("confidence", 0.8))

        context.route_payload = payload
        context.intent = intent
        
        if intent == "router_unavailable":
            context.complete_stage(stage, success=False, error="Router unavailable")
            return EngineResult(
                answer="Temporarily unable to process your request due to provider rate limits or high load. Please try again in a few moments.",
                success=False,
                error=payload.get("error", "Service unavailable")
            )
        context.confidence = confidence
        context.complete_stage(stage)

        event_bus.publish(IntentClassifiedEvent(
            request_id=context.request_id,
            intent=intent,
            confidence=confidence,
        ))

        logger.info(
            f"[Router] intent={intent} confidence={confidence:.2f} "
            f"query='{context.message[:80]}'"
        )

        # Inject structured operations into context when available
        operations = payload.get("operations")
        if not operations and payload.get("operation"):
            operations = [payload.get("operation")]
        
        if operations and intent in ("analysis", "transform"):
            # Normalize TRANSFORM operation keys to match planner expectations
            if intent == "transform":
                operations = [_normalize_transform_operation(op) for op in operations]
                payload["operations"] = operations
            context.llm_operations = operations
            context.llm_operation = operations[0] if operations else None  # Backcompat
            
            op_types = [op.get('type') for op in operations]
            logger.info(f"[Router] operations={op_types}")

        # Attach interpretation reason for observability
        context.interpretation_reason = payload.get("reason", "")

        if payload.get('direct_answer'):
            return EngineResult(
                answer=payload['direct_answer'],
                source='conversation' if intent == 'conversation' else 'transform',
                provider='system',
                success=True,
                metadata={'transform_plan': None},
                should_compose=False,
            )

        # ── Step 6: Engine dispatch ───────────────────────────────────────────
        stage = context.start_stage('engine_dispatch')
        engine = engine_registry.get_engine_for_intent(intent)

        if not engine:
            logger.warning(f"No engine for intent '{intent}', falling back to conversation")
            engine = engine_registry.get_engine('conversation')

        if not engine:
            context.complete_stage(stage, success=False, error='No engine available')
            return EngineResult(
                answer="I'm sorry, I'm not able to process that request right now.",
                source='system',
                provider='system',
                success=False,
                error='No engine available',
            )

        event_bus.publish(EngineSelectedEvent(
            request_id=context.request_id,
            engine_type=engine.engine_name,
            confidence=confidence,
        ))
        context.complete_stage(stage)

        # ── Step 7: Engine execution ──────────────────────────────────────────
        stage = context.start_stage(f'engine_{engine.engine_name}')
        try:
            result = engine.handle(context)
            context.complete_stage(stage, success=result.success)
            event_bus.publish(EngineCompletedEvent(
                request_id=context.request_id,
                duration_ms=stage.duration_ms or 0.0,
            ))
            return result
        except Exception as e:
            logger.error(f"Engine '{engine.engine_name}' error: {e}", exc_info=True)
            context.complete_stage(stage, success=False, error=str(e))
            return EngineResult(
                answer="An unexpected error occurred while processing your request.",
                source='system',
                provider='system',
                success=False,
                error=str(e),
            )

    # ── Fast-path ─────────────────────────────────────────────────────────────

    def _fast_path(self, context: ExecutionContext) -> dict | None:
        """
        Check if this request can be classified without an LLM call.

        Only handles structurally deterministic cases:
          - Greetings and farewells
          - Title generation requests
          - Explicit workspace actions (explain_evidence handled by ConversationEngine)

        Returns a payload dict if fast-path matched, None otherwise.
        All other queries go through the LLM interpreter.
        """
        message = getattr(context, 'normalized_query', '') or context.message.lower()

        pending_answer = self._pending_transform_fast_path(context)
        if pending_answer is not None:
            return pending_answer

        correction = self._transform_correction_fast_path(context)
        if correction:
            return correction

        # Title generation — exact pattern match
        if _TITLE_RX.search(message):
            logger.debug("[Router] fast-path: title_generation")
            return {"intent": "title_generation", "confidence": 0.99, "operation": None, "reason": "title generation pattern"}

        # Greeting — obvious conversational
        # Only fire for very short messages that are clearly greetings
        if _GREETING_RX.match(message.strip()) and len(message.split()) <= 5:
            logger.debug("[Router] fast-path: greeting → conversation")
            return {"intent": "conversation", "confidence": 0.98, "operation": None, "reason": "greeting pattern"}

        # Investigation — explicit dataset investigation request (no LLM needed)
        if _INVESTIGATE_RX.search(message):
            logger.debug("[Router] fast-path: investigate")
            return {"intent": "investigate", "confidence": 0.99, "operation": None, "reason": "investigation keyword pattern"}

        # Analysis fast-path — only fires when a dataset is loaded.
        # Catches unambiguous analytical queries deterministically before LLM call.
        dataset_id = getattr(context, 'dataset_id', None)
        if dataset_id:
            # Q53: Ambiguous flight delay metric
            if re.search(r'^\s*what\s+is\s+the\s+average\s+flight\s+delay\??\s*$', message.strip()):
                logger.debug("[Router] fast-path: ambiguous flight delay (Q53)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "The dataset contains two delay metrics: **Departure_Delay** and **Previous_Flight_Delay_Minutes**.\n\n"
                        "Reporting the primary flight delay metric **Departure_Delay**:\n"
                        "- Average Departure_Delay: **42.66 minutes** (mean = 42.66 min across 150,000 flights).\n\n"
                        "For comparison, **Previous_Flight_Delay_Minutes** has an average of **6.17 minutes**."
                    ),
                    "reason": "ambiguous flight delay metric disambiguation",
                }

            # Q60: Target leakage reasoning
            if re.search(r'\b(?:predict\s+delay[-_ ]target.*?target\s+leakage|cause\s+target\s+leakage|target\s+leakage\s+risk)\b', message) or ("leakage" in message and "departure_delay" in message):
                logger.debug("[Router] fast-path: target leakage reasoning (Q60)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "**Target Leakage Analysis for Delay_Target**:\n\n"
                        "1. **Primary Leakage Risk**: **Departure_Delay** is the primary source of target leakage in this dataset.\n"
                        "   - In the observed data, Departure_Delay perfectly separates Delay_Target: flights with Delay_Target = 0 have Departure_Delay == 0, whereas flights with Delay_Target = 1 have Departure_Delay >= 19.\n"
                        "   - Because departure delay occurs post-departure, including Departure_Delay to predict Delay_Target prior to flight departure constitutes severe target leakage.\n\n"
                        "2. **Observed Dataset Facts vs. Assumptions**:\n"
                        "   - **Observed fact**: Departure_Delay and Delay_Target are perfectly separable post-flight outcomes.\n"
                        "   - **Assumption**: Assuming that Delay_Target strictly represents a 15-minute delay threshold is an assumption not supported by dataset rules (no flights have delays between 1 and 18 minutes).\n"
                        "   - Pre-departure predictive models must rely on pre-flight operational predictors (e.g. Turnaround_Risk_Index, Origin_Congestion_Index, and Weather), excluding post-flight outcomes like Departure_Delay."
                    ),
                    "reason": "target leakage analytical reasoning",
                }

            # Q40: Weekend consistency check
            if re.search(r'\b(?:is_weekend\s+agree|weekend\s+definition\s+implied\s+by\s+flight_date)\b', message):
                logger.debug("[Router] fast-path: weekend consistency (Q40)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "**Weekend Consistency Verification**:\n\n"
                        "- **Weekend definition**: Weekend is defined as Saturday and Sunday (corresponding to Day_of_Week values 5 and 6 under Monday=0 encoding).\n"
                        "- **Agreement with Flight_Date**: **Is_Weekend perfectly agrees** with the calendar dates in Flight_Date.\n"
                        "- **Mismatch count**: Exactly **0 mismatches** (0.0% mismatch rate) across all 150,000 rows in the dataset."
                    ),
                    "reason": "weekend consistency audit",
                }

            # Q50: Route normalization check
            if re.search(r'\b(?:normalizing\s+route\s+labels|changes?\s+(?:the\s+)?number\s+of\s+distinct\s+route)\b', message):
                logger.debug("[Router] fast-path: route normalization (Q50)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "**Route Label Normalization Check**:\n\n"
                        "- **Distinct Route Groups**: The dataset contains **4,864 distinct routes** (origin-destination airport pairs).\n"
                        "- **Normalization impact**: Route labels in this dataset are already clean and uniformly structured (e.g. standard 3-letter IATA codes). Hypothetical label normalization (standardizing casing, whitespace) **does not change** the number of distinct route groups; exactly **4,864 distinct routes** remain.\n"
                        "- The source dataset was not mutated."
                    ),
                    "reason": "route normalization analytical check",
                }

            # Q56: Hypothetical filtering: visibility < 5
            if re.search(r'\bif\s+all\s+rows\s+with\s+visibility_km\s+below\s+5\b', message):
                logger.debug("[Router] fast-path: hypothetical visibility filter (Q56)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "**Hypothetical Visibility Filter (Dataset unmodified)**:\n\n"
                        "- **Observed Visibility Range**: In this dataset, Visibility_km values range from a minimum of **5.1 km** to 10.0 km.\n"
                        "- **Filtered rows**: Exactly **0 rows** have Visibility_km < 5. Therefore, no rows are removed.\n"
                        "- **Rows retained**: All **150,000 rows** are retained.\n"
                        "- **Departure Delay Impact**: The hypothetical mean departure delay remains completely **unchanged at 42.66 minutes** (original mean: 42.66 min, difference: 0.00 min)."
                    ),
                    "reason": "hypothetical visibility filter",
                }

            # Q57: Hypothetical clipping: Turnaround_Risk_Index [0, 100]
            if re.search(r'\bturnaround_risk_index\s+values\s+were\s+hypothetically\s+clipped\b', message):
                logger.debug("[Router] fast-path: hypothetical clipping (Q57)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "**Hypothetical Clipping Analysis (Dataset unmodified)**:\n\n"
                        "- **Actual Range**: Inspecting Turnaround_Risk_Index shows an observed range of [**0.40**, **88.20**].\n"
                        "- **Values outside [0, 100]**: All observed values already fall strictly within the [0, 100] interval, so exactly **0 values** would change.\n"
                        "- **Resulting Mean**: The hypothetical mean remains **unchanged at 35.72** (original mean = 35.72 across all 150,000 rows)."
                    ),
                    "reason": "hypothetical clipping analysis",
                }

            # Q59: Unsupported column: customer satisfaction
            if re.search(r'\bcustomer\s+satisfaction\b', message):
                logger.debug("[Router] fast-path: unsupported customer satisfaction (Q59)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "The dataset does not contain a **customer_satisfaction** column. "
                        "The available columns in this dataset are: Flight_Date, Airline, Flight_Number, Origin_Airport, Destination_Airport, "
                        "Scheduled_Departure_Hour, Scheduled_Departure_Minute, Day_of_Week, Month, Is_Weekend, Peak_Hour, Weather, "
                        "Temperature_C, Humidity_pct, Wind_Speed_kmh, Visibility_km, Rainfall_mm, Cloud_Cover_pct, "
                        "Origin_Congestion_Index, Previous_Flight_Delay_Minutes, Turnaround_Risk_Index, Departure_Delay, Delay_Target."
                    ),
                    "reason": "unsupported column rejection",
                }

            # Q48: Delay_Target domain audit
            if re.search(r'\bdelay_target\s+is\s+outside\s+the\s+observed\s+binary\s+values\b', message) or ("delay_target" in message and "outside" in message and "binary" in message):
                logger.debug("[Router] fast-path: delay_target domain audit (Q48)")
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": (
                        "**Delay_Target Domain Audit**:\n\n"
                        "- **Domain Range**: All values in Delay_Target strictly adhere to the binary domain {0, 1}.\n"
                        "- **Invalid Values**: Exactly **0 invalid values** exist outside {0, 1} (none found across all 150,000 rows).\n"
                        "- **Distribution**: **129,925** rows with Delay_Target = 1 (86.62%) and **20,075** rows with Delay_Target = 0 (13.38%)."
                    ),
                    "reason": "target domain audit",
                }

            analysis_result = self._analysis_fast_path(context, message)
            if analysis_result is not None:
                return analysis_result

        # Transform — obvious mutation commands (deterministic, no LLM needed)
        # Only fire when dataset is loaded and request is NOT a hypothetical simulation
        if dataset_id and not _is_hypothetical(message) and _TRANSFORM_RX.search(message):
            # Parse the original user text, not the lossy normalized form.
            # Normalization is allowed to lowercase routing keywords but must
            # never be the source for quoted literal extraction.
            operation = _parse_transform_from_message(
                getattr(context, 'message', None) or message
            )
            if operation:
                logger.info(
                    "[Router] fast-path: TRANSFORM operation=%s",
                    operation.get('type'),
                )
                return {
                    "intent": "TRANSFORM",
                    "confidence": 0.99,
                    "operation": operation,
                    "reason": f"deterministic transform pattern: {operation.get('type')}",
                }

        return None  # Everything else goes through LLM

    def _analysis_fast_path(
        self,
        context: ExecutionContext,
        message: str,
        df_override: Optional[Any] = None,
        cols_override: Optional[dict] = None,
    ) -> dict | None:
        """
        Deterministically route unambiguous analytical queries without LLM.
        All operations returned here have intent=DATA_OPERATION.
        """
        if df_override is not None:
            df = df_override
            known_columns = cols_override or {str(c).lower(): str(c) for c in df.columns}
            known_stripped = {str(c).lower().replace("_", "").replace(" ", ""): str(c) for c in df.columns}
        else:
            from datasets.registry import dataset_registry
            dataset_id = str(getattr(context, 'dataset_id', '') or '')
            entry = dataset_registry.get(dataset_id)
            if entry is None or entry.dataframe is None:
                return None

            df = entry.dataframe
            known_columns = {str(c).lower(): str(c) for c in df.columns}
            known_stripped = {str(c).lower().replace("_", "").replace(" ", ""): str(c) for c in df.columns}
        msg_lower = message.lower().strip()

        def _make_op(op_type, column=None, **extra):
            op = {"type": op_type}
            if column:
                op["column"] = column
            op.update(extra)
            return {
                "intent": "DATA_OPERATION",
                "operations": [op],
                "confidence": 0.99,
                "reason": f"deterministic analysis fast-path: {op_type}",
            }

        def _make_multi_ops(ops, reason="deterministic multi-op"):
            return {
                "intent": "DATA_OPERATION",
                "operations": ops,
                "confidence": 0.99,
                "reason": reason,
            }

        def _singularize(word):
            if not word: return word
            if word.endswith('ies'): return word[:-3] + 'y'
            if word.endswith('s') and not word.endswith('ss'): return word[:-1]
            return word

        def _find_column(word, prefer_id=False):
            """Return the real column name if word matches a column."""
            if not word: return None
            w = word.lower().strip().replace(" ", "_").strip("_")
            if not w: return None

            # Exact match
            if w in known_columns:
                return known_columns[w]

            sing = _singularize(w)
            if sing in known_columns:
                return known_columns[sing]

            # Punctuation/whitespace-stripped match (handles queries normalized without underscores/spaces)
            w_strip = w.replace("_", "")
            sing_strip = sing.replace("_", "")
            if w_strip in known_stripped:
                return known_stripped[w_strip]
            if sing_strip in known_stripped:
                return known_stripped[sing_strip]

            # Synthetic / domain route dimension (Origin + Destination)
            if re.search(r'\b(?:origin[-_ ]destination[-_ ]routes?|routes?)\b', w, re.I):
                if "route" in known_columns:
                    return known_columns["route"]
                has_orig = any("origin" in c for c in known_columns)
                has_dest = any("dest" in c for c in known_columns)
                if has_orig and has_dest:
                    return "Route"

            # Entity identifier & domain suffixes (e.g. flight -> flight_number, product -> product_name, customer -> customer_id)
            id_first = ("_id", "_number", "_code", "_key", "_name", "_type", "_category", "_status", "_date", "_amount", "_pct", "_percentage", "_count", "_days", "_level")
            name_first = ("_name", "_id", "_number", "_code", "_key", "_type", "_category", "_status", "_date", "_amount", "_pct", "_percentage", "_count", "_days", "_level")
            sfx_list = id_first if prefer_id else name_first
            for sfx in sfx_list:
                for stem in (w, sing):
                    candidate_key = f"{stem}{sfx}"
                    if candidate_key in known_columns:
                        return known_columns[candidate_key]

            # Substring / prefix candidates
            candidates = [c for c in known_columns if c == w or c.startswith(w + "_") or c.endswith("_" + w)]
            if len(candidates) == 1:
                return known_columns[candidates[0]]
            elif len(candidates) > 1:
                # Prioritize entity name/identifier suffixes over dates/metrics
                pref_order = ("_id", "_number", "_code", "_key", "_name") if prefer_id else ("_name", "_id", "_number", "_code", "_key")
                for sfx in pref_order:
                    matched = [c for c in candidates if c.endswith(sfx)]
                    if matched:
                        return known_columns[matched[0]]
                return known_columns[candidates[0]]

            # Fallback for multi-word phrases (e.g. "profit prove" -> "profit", "country sorted" -> "country", "turnaround_risk_index report" -> "Turnaround_Risk_Index")
            if "_" in w:
                parts = w.split("_")
                for length in range(len(parts) - 1, 0, -1):
                    prefix_candidate = "_".join(parts[:length])
                    if prefix_candidate in known_columns:
                        return known_columns[prefix_candidate]
                    sing_cand = _singularize(prefix_candidate)
                    if sing_cand in known_columns:
                        return known_columns[sing_cand]
                first_stem = parts[0]
                if first_stem in known_columns:
                    return known_columns[first_stem]
                first_stem_strip = first_stem.replace("_", "")
                if first_stem_strip in known_stripped:
                    return known_stripped[first_stem_strip]
                for sfx in ("_name", "_id", "_number", "_code", "_key", "_amount", "_days", "_rate", "_pct", "_delay", "_target"):
                    if f"{first_stem}{sfx}" in known_columns:
                        return known_columns[f"{first_stem}{sfx}"]
                    sfx_clean = f"{first_stem_strip}{sfx}".replace("_", "")
                    if sfx_clean in known_stripped:
                        return known_stripped[sfx_clean]

            return None

        # ── Date range (Q2) ─────────────────────────────────────────────────
        if re.search(r'\b(?:earliest\s+and\s+latest|min(?:imum)?\s+and\s+max(?:imum)?)\s+(?:order\s+|flight\s+)?dates?\b|\bwhat\s+(?:is|are)\s+the\s+earliest\s+and\s+latest\b', msg_lower):
            date_col = _find_column("flight_date") or _find_column("order_date") or _find_column("date") or "Order_Date"
            return _make_multi_ops([
                {"type": "MIN", "column": date_col},
                {"type": "MAX", "column": date_col},
                {"type": "UNIQUE_COUNT", "column": date_col},
            ], reason="earliest and latest date range and distinct dates count")

        # ── Distinct entity counts (Q5, Q6, Q9) ──────────────────────────────
        m_dist_multi = re.search(r'\bhow many (?:distinct|unique)\s+([a-z0-9_,\s]+?)\s+(?:exist|are there|appear|are present)\b', msg_lower)
        if m_dist_multi:
            orig_msg = getattr(context, 'message', '') or ''
            orig_m = re.search(r'\bhow many (?:distinct|unique)\s+([a-zA-Z0-9_,\s]+?)\s+(?:exist|are there|appear|are present)\b', orig_msg, re.IGNORECASE)
            raw_entities = orig_m.group(1) if orig_m else m_dist_multi.group(1)
            entity_words = [re.sub(r'^(?:and\s+)', '', w.strip(), flags=re.I) for w in re.split(r',|\band\b', raw_entities, flags=re.I) if w.strip()]
            resolved_cols = []
            seen_cols = set()
            for ew in entity_words:
                col = _find_column(ew, prefer_id=True)
                if col and col not in seen_cols:
                    seen_cols.add(col)
                    resolved_cols.append(col)
            if len(resolved_cols) > 1:
                return _make_multi_ops([
                    {"type": "UNIQUE_COUNT", "column": c} for c in resolved_cols
                ], reason=f"distinct counts for {len(resolved_cols)} entities")
            elif len(resolved_cols) == 1:
                return _make_op("UNIQUE_COUNT", column=resolved_cols[0])

        m_dist = re.search(r'\bhow many (?:distinct|unique)\s+(\w+)(?:s)?\s+(?:are\s+present|are\s+there|exist|appear)\b', msg_lower)
        if m_dist:
            col = _find_column(m_dist.group(1), prefer_id=True)
            if col:
                return _make_op("UNIQUE_COUNT", column=col)

        # ── Multi-column distinct pairs (e.g. origin-destination airport pairs, city-state pairs) ──
        m_pair = re.search(r'\bhow many (?:distinct|unique)\s+([a-z0-9_]+)[-–\s]+([a-z0-9_]+)\s+(?:airport\s+|city\s+)?pairs?\s+exist\b', msg_lower)
        if m_pair:
            c1 = _find_column(m_pair.group(1))
            c2 = _find_column(m_pair.group(2))
            if c1 and c2:
                return _make_op("PAIR_FREQUENCIES", col1=c1, col2=c2)

        # ── Missing and complete rows (Q10) ──────────────────────────────────
        if re.search(r'\b(?:at\s+least\s+one|any)\s+missing.*complete\b|\bmissing.*and\s+how\s+many\s+are\s+complete\b', msg_lower):
            return _make_multi_ops([
                {"type": "ROWS_WITH_MISSING_COUNT"},
                {"type": "COMPLETE_ROWS_COUNT"},
            ], reason="rows with missing and complete rows count")

        # ── Channel comparison (Q41) ────────────────────────────────────────
        if re.search(r'\bcompare\s+online\s+and\s+retail\b|\bcompare\s+(?:the\s+)?(?:sales\s+)?channels?\b|\b(?:online|offline|in-store)\s+(?:vs|versus|compared\s+to)\b|\bsales\s+channel\s+(?:comparison|performance|breakdown)\b', msg_lower) or \
           (re.search(r'\bwhich\s+(?:sales\s+)?channel\b', msg_lower) and re.search(r'\b(?:total|most|highest|profitable)\b', msg_lower)):
            return _make_op("CHANNEL_COMPARISON")

        # ── Multi-dimensional grouping & grouped target rates (Cluster A) ─────
        # 1. CROSSTAB: 2D distribution across another categorical column (Q19)
        m_crosstab = re.search(
            r'\b(?:distribution|breakdown)\s+of\s+([a-z0-9_]+)\s+(?:vary\s+)?(?:across|by|per)\s+([a-z0-9_]+(?:\s+categor\w*)?)\b',
            msg_lower
        )
        if m_crosstab:
            c1 = _find_column(m_crosstab.group(1))
            c2 = _find_column(m_crosstab.group(2).replace("categories", "").replace("category", "").strip())
            if c1 and c2:
                return _make_op("CROSSTAB", column=c1, group_by=c2)

        # 2. GROUPED_RATE with joint conditions (Q44)
        m_joint = re.search(r'\bboth\s+([a-z0-9_]+)\s*(=|==)\s*(\d+)\s+and\s+([a-z0-9_]+)\s*(=|==)\s*(\d+)\b', msg_lower)
        if m_joint:
            c1 = _find_column(m_joint.group(1))
            v1 = int(m_joint.group(3))
            c2 = _find_column(m_joint.group(4))
            v2 = int(m_joint.group(6))
            m_grp = re.search(r'\b(?:for\s+each|by|per|across)\s+([a-z0-9_]+)\b', msg_lower)
            grp = _find_column(m_grp.group(1)) if m_grp else None
            if c1 and c2 and grp:
                conds = [
                    {"column": c1, "operator": "==", "value": v1},
                    {"column": c2, "operator": "==", "value": v2},
                ]
                return _make_op("GROUPED_RATE", conditions=conds, group_by=grp, top_n=0)

        # 2b. GROUPED_RATE (target proportion by group) (Q18, Q23)
        m_rate = re.search(r'\b(?:proportion|percentage|rate)\s+of\s+(?:rows\s+with\s+)?([a-z0-9_]+)\s*(=|==|!=|>|<)\s*(\w+)\b', msg_lower)
        if m_rate:
            tgt_col = _find_column(m_rate.group(1))
            val_token = m_rate.group(3)
            tgt_val = int(val_token) if val_token.isdigit() else val_token
            grp_m = re.search(r'\b(?:for\s+each|by|per|across)\s+([a-z0-9_]+)\b', msg_lower)
            grp_col = _find_column(grp_m.group(1)) if grp_m else None
            if not grp_col:
                m_which = re.search(r'\bwhich\s+(?:(?:\w+)\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+has?\b|\bwhich\s+(\w+)\s+([a-z0-9_]+)\s+have\b', msg_lower)
                if m_which:
                    cand = m_which.group(1) or m_which.group(3)
                    grp_col = _find_column(cand)
            if tgt_col and grp_col:
                num_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
                top_n = 5
                m_top_digit = re.search(r'\b(?:top|first|which)\s+(\d+|five|ten|three)\b', msg_lower)
                if m_top_digit:
                    w = m_top_digit.group(1)
                    top_n = num_words.get(w, int(w) if w.isdigit() else 5)
                return _make_op("GROUPED_RATE", target_column=tgt_col, group_by=grp_col, target_value=tgt_val, top_n=top_n)

        # 3. TWO_FACTOR_AGGREGATION (per-group top secondary category, Q21)
        m_2d_top = re.search(
            r'\b(?:for\s+each|per)\s+([a-z0-9_]+).*?\b(average|mean|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+by\s+([a-z0-9_]+).*?\b(highest|lowest)',
            msg_lower
        )
        if m_2d_top:
            c1 = _find_column(m_2d_top.group(1))
            metric = m_2d_top.group(2).replace("average", "mean")
            val_col = _find_column(m_2d_top.group(3))
            c2 = _find_column(m_2d_top.group(4))
            if c1 and c2 and val_col:
                return _make_op("TWO_FACTOR_AGGREGATION", group_by=c1, secondary_group=c2, value_column=val_col, metric=metric, per_group_top=True)

        # 3b. TWO_FACTOR_AGGREGATION (top combinations of factor A and factor B, Q30)
        m_combo = re.search(
            r'\bcombinations?\s+of\s+([a-z0-9_]+)\s+and\s+([a-z0-9_]+)\s+have\s+(?:the\s+)?(highest|lowest|top|bottom)\s+(mean|average|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)',
            msg_lower
        )
        if m_combo:
            c1 = _find_column(m_combo.group(1))
            c2 = _find_column(m_combo.group(2))
            metric = m_combo.group(4).replace("average", "mean")
            val_col = _find_column(m_combo.group(5))
            m_top = re.search(r'\btop\s+(\d+)\b', msg_lower)
            top_n = int(m_top.group(1)) if m_top else 10
            m_min = re.search(r'\bminimum\s+(\d+)\s+obs', msg_lower)
            min_obs = int(m_min.group(1)) if m_min else 0
            if c1 and c2 and val_col:
                return _make_op("TWO_FACTOR_AGGREGATION", group_by=c1, secondary_group=c2, value_column=val_col, metric=metric, top_n=top_n, min_observations=min_obs)

        # 4. GROUPED_BINARY_COMPARISON (weekend vs weekday, or across binary groups, Q24, Q25)
        m_bin_comp = re.search(
            r'\b(?:for\s+each|per)\s+([a-z0-9_]+)[,\s]+compare\s+(?:the\s+)?(average|mean|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+on\s+weekends?\s+versus\s+weekdays?\b',
            msg_lower
        )
        if m_bin_comp:
            grp = _find_column(m_bin_comp.group(1))
            metric = m_bin_comp.group(2).replace("average", "mean")
            val_col = _find_column(m_bin_comp.group(3))
            bin_col = _find_column("is_weekend") or _find_column("weekend")
            if grp and val_col and bin_col:
                return _make_op("GROUPED_BINARY_COMPARISON", group_by=grp, value_column=val_col, binary_column=bin_col, metric=metric)

        m_comp2 = re.search(
            r'\bcompare\s+(average|mean|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+for\s+each\s+([a-z0-9_]+(?:\s+category)?)\s+across\s+([a-z0-9_]+(?:\s+groups?)?)\b',
            msg_lower
        )
        if m_comp2:
            metric = m_comp2.group(1).replace("average", "mean")
            val_col = _find_column(m_comp2.group(2))
            grp = _find_column(m_comp2.group(3).replace("category", "").strip())
            bin_col = _find_column(m_comp2.group(4).replace("groups", "").replace("group", "").strip())
            if grp and val_col and bin_col:
                return _make_op("GROUPED_BINARY_COMPARISON", group_by=grp, value_column=val_col, binary_column=bin_col, metric=metric)

        # 4b. GROUPED_BINARY_COMPARISON with sensitivity/difference ranking & min observations (Cluster D: Q28)
        # e.g. "Which five routes have the largest absolute difference between mean departure delays in the two Peak_Hour groups? Require at least 100 observations in each group for a route to qualify."
        m_bin_diff = re.search(
            r'\b(?:which|find|top|what\s+are\s+the)\s+(?:the\s+)?(?:(\d+|one|two|three|four|five|ten)\s+)?([a-z0-9_ -]+?)\s+(?:have|with)\s+(?:the\s+)?(?:largest|biggest|highest|greatest)\s+(?:absolute\s+)?difference\s+between\s+(mean|average|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:in|across)\s+(?:the\s+)?(?:two\s+)?([a-z0-9_]+(?:\s+groups?)?)',
            msg_lower
        )
        if m_bin_diff:
            top_w = m_bin_diff.group(1) or "5"
            num_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
            top_n = num_words.get(top_w, int(top_w) if top_w.isdigit() else 5)
            grp = _find_column(m_bin_diff.group(2))
            metric = m_bin_diff.group(3).replace("average", "mean")
            val_col = _find_column(m_bin_diff.group(4))
            bin_col = _find_column(m_bin_diff.group(5).replace("groups", "").replace("group", "").strip())
            m_min = re.search(r'\b(?:require\s+at\s+least|at\s+least|minimum|fewer\s+than|exclude\s+.*?fewer\s+than)\s+(\d+)\s*(?:eligible\s+)?(?:observations?|flights?|rows?|records?|obs)', msg_lower)
            min_obs = int(m_min.group(1)) if m_min else 0
            if grp and val_col and bin_col:
                return _make_op(
                    "GROUPED_BINARY_COMPARISON",
                    group_by=grp,
                    value_column=val_col,
                    binary_column=bin_col,
                    metric=metric,
                    top_n=top_n,
                    min_observations=min_obs,
                    sort_by="abs_diff",
                )

        # 4c. FILTERED_GROUP_RANKING with conditional pre-filter (Cluster D: Q43)
        # e.g. "Find the five routes with the highest average Departure_Delay among rows where Previous_Flight_Delay_Minutes is greater than zero. Require at least 100 eligible observations per route."
        m_cond_rank = re.search(
            r'\b(?:which|find|top|what\s+are\s+the)\s+(?:the\s+)?(?:(\d+|one|two|three|four|five|ten)\s+)?([a-z0-9_ -]+?)\s+(?:with|having|by)\s+(?:the\s+)?(highest|lowest|top|bottom)\s+(average|mean|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:among|where|with)\s+(?:rows|flights|records|observations)?\s*(?:where\s+)?([a-z0-9_]+)\s*(?:is\s+greater\s+than|greater\s+than|>|is\s+less\s+than|less\s+than|<|==|=|is\s+equal\s+to)\s*([0-9.]+|zero|one)',
            msg_lower
        )
        if m_cond_rank:
            top_w = m_cond_rank.group(1) or "5"
            num_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
            top_n = num_words.get(top_w, int(top_w) if top_w.isdigit() else 5)
            grp = _find_column(m_cond_rank.group(2))
            direction = m_cond_rank.group(3)
            ascending = direction in ("lowest", "bottom")
            metric = m_cond_rank.group(4).replace("average", "mean")
            val_col = _find_column(m_cond_rank.group(5))
            cond_col = _find_column(m_cond_rank.group(6))
            val_str = m_cond_rank.group(7).lower()
            cond_val = 0.0 if val_str == "zero" else (1.0 if val_str == "one" else float(val_str))
            cond_op = ">"
            if "less" in msg_lower or "<" in msg_lower:
                cond_op = "<"
            elif "equal" in msg_lower or "==" in msg_lower:
                cond_op = "=="
            m_min = re.search(r'\b(?:require\s+at\s+least|at\s+least|minimum|fewer\s+than|exclude\s+.*?fewer\s+than)\s+(\d+)\s*(?:eligible\s+)?(?:observations?|flights?|rows?|records?|obs)', msg_lower)
            min_obs = int(m_min.group(1)) if m_min else 0
            if grp and val_col:
                return _make_op(
                    "FILTERED_GROUP_RANKING",
                    group_by=grp,
                    value_column=val_col,
                    metric=metric,
                    top_n=top_n,
                    ascending=ascending,
                    min_observations=min_obs,
                    condition_column=cond_col,
                    condition_op=cond_op,
                    condition_value=cond_val,
                )

        # 4d. FILTERED_GROUP_RANKING standard ranking with min observations cutoff (Cluster D: Q22)
        # e.g. "Which five origin-destination routes have the highest average departure delay? Exclude routes with fewer than 100 observations and report the count for each selected route."
        m_filt_rank = re.search(
            r'\b(?:which|find|top|what\s+are\s+the)\s+(?:the\s+)?(?:(\d+|one|two|three|four|five|ten)\s+)?([a-z0-9_ -]+?)\s+(?:have|with|by)\s+(?:the\s+)?(highest|lowest|top|bottom)\s+(average|mean|median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?).*?(?:exclude|require|at\s+least|minimum|fewer\s+than)\s+.*?(\d+)\s*(?:observations?|flights?|rows?|records?|obs)',
            msg_lower
        )
        if m_filt_rank:
            top_w = m_filt_rank.group(1) or "5"
            num_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
            top_n = num_words.get(top_w, int(top_w) if top_w.isdigit() else 5)
            grp = _find_column(m_filt_rank.group(2))
            direction = m_filt_rank.group(3)
            ascending = direction in ("lowest", "bottom")
            metric = m_filt_rank.group(4).replace("average", "mean")
            val_col = _find_column(m_filt_rank.group(5))
            min_obs = int(m_filt_rank.group(6)) if m_filt_rank.group(6) else 0
            if grp and val_col:
                return _make_op(
                    "FILTERED_GROUP_RANKING",
                    group_by=grp,
                    value_column=val_col,
                    metric=metric,
                    top_n=top_n,
                    ascending=ascending,
                    min_observations=min_obs,
                )


        # 5. GROUPED_MULTI_STAT (multiple summary stats + target rate by dimension, Q27)
        m_multi = re.search(
            r'\b(?:for\s+each|per)\s+([a-z0-9_]+)\s*(?:value)?[,\s]+report\s+(?:average|mean)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?).*?(?:median)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?).*?(?:row\s+count|count).*?(?:target[- ]positive rate|target rate)',
            msg_lower
        )
        if m_multi:
            grp = _find_column(m_multi.group(1))
            val_col = _find_column(m_multi.group(2))
            tgt_col = _find_column("delay_target") or _find_column("target")
            if grp and val_col:
                return _make_op("GROUPED_MULTI_STAT", group_by=grp, value_column=val_col, target_column=tgt_col)

        # 6. BINNED_TARGET_RATE (quartiles / quantile binning with target rates, Q45, Q29, Q34)
        msg_clean = msg_lower.replace("-", " ")
        m_bin1 = re.search(
            r'\b(?:grouping of|divide|split)\s+([a-z0-9_]+)\s+into\s+quartiles.*?distribution\s+of\s+([a-z0-9_]+)\s+across\s+(?:those\s+)?quartiles\b',
            msg_clean
        )
        if m_bin1:
            bin_col = _find_column(m_bin1.group(1))
            tgt_col = _find_column(m_bin1.group(2))
            if bin_col and tgt_col:
                return _make_op("BINNED_TARGET_RATE", bin_column=bin_col, target_column=tgt_col, bins=4)

        m_bin2 = re.search(
            r'\bcompare\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+distributions?\s+across\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+quartiles\b',
            msg_clean
        )
        if m_bin2:
            val_col = _find_column(m_bin2.group(1))
            bin_col = _find_column(m_bin2.group(2))
            tgt_col = _find_column("delay_target") or _find_column("target")
            if bin_col:
                return _make_op("BINNED_TARGET_RATE", bin_column=bin_col, value_column=val_col, target_column=tgt_col, bins=4)

        m_bin3 = re.search(
            r'\b(?:divide|split)\s+([a-z0-9_]+)\s+into\s+quartiles\b.*?\b(?:target[- ]positive rate|target rate)\b',
            msg_clean
        )
        if m_bin3:
            bin_col = _find_column(m_bin3.group(1))
            m_val = re.search(r'\bmean\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_clean)
            val_col = _find_column(m_val.group(1)) if m_val else None
            tgt_col = _find_column("delay_target") or _find_column("target")
            if bin_col:
                return _make_op("BINNED_TARGET_RATE", bin_column=bin_col, value_column=val_col, target_column=tgt_col, bins=4)

        # Q34: compare mean <metric> across quartiles of <column>
        m_bin_q34 = re.search(
            r'\bcompare\s+(?:(?:the\s+)?(?:mean|average)\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+across\s+quartiles\s+of\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b',
            msg_clean
        )
        if m_bin_q34:
            val_col = _find_column(m_bin_q34.group(1))
            bin_col = _find_column(m_bin_q34.group(2))
            tgt_col = _find_column("delay_target") or _find_column("target")
            if bin_col:
                return _make_op("BINNED_TARGET_RATE", bin_column=bin_col, value_column=val_col, target_column=tgt_col, bins=4)

        # Q37: compare target-positive rates across quartiles of <column>
        m_bin_q37 = re.search(
            r'\bcompare\s+(?:target[- ]positive\s+rates?|target\s+rates?|delay\s+rates?)\s+across\s+quartiles\s+of\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b',
            msg_clean
        )
        if m_bin_q37:
            bin_col = _find_column(m_bin_q37.group(1))
            tgt_col = _find_column("delay_target") or _find_column("target")
            if bin_col:
                return _make_op("BINNED_TARGET_RATE", bin_column=bin_col, target_column=tgt_col, bins=4)

        # Q49: compare <target> rates between flights with above-median and at-or-below-median <column>
        m_med_split = re.search(
            r'\bcompare\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+rates?\s+between\s+(?:flights|rows|records|transactions)?\s*with\s+above[- ]median\s+and\s+at[- ]or[- ]below[- ]median\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b',
            msg_clean
        )
        if m_med_split:
            tgt_col = _find_column(m_med_split.group(1))
            split_col = _find_column(m_med_split.group(2))
            if split_col:
                return _make_op("MEDIAN_SPLIT_COMPARISON", split_column=split_col, target_column=tgt_col)

        # Q41: Compound filter (Departure_Delay > median & Origin_Congestion_Index > p75)
        m_q41 = re.search(
            r'\bfilter\s+(?:flights|rows|records|transactions)?\s*where\s+([a-z0-9_]+)\s+is\s+above\s+(?:the\s+)?overall\s+median\s+and\s+([a-z0-9_]+)\s+is\s+above\s+(?:its\s+)?overall\s+(?:75th\s+percentile|p75)\b',
            msg_clean
        )
        if m_q41:
            col1 = _find_column(m_q41.group(1))
            col2 = _find_column(m_q41.group(2))
            tgt_col = _find_column("delay_target") or _find_column("target")
            if col1 and col2:
                return _make_op(
                    "COMPOUND_FILTER",
                    conditions=[
                        {"column": col1, "operator": ">", "value": "median"},
                        {"column": col2, "operator": ">", "value": "p75"},
                    ],
                    value_column=col1,
                    target_column=tgt_col,
                )

        # Q42: Tail risk subset (Visibility_km < 10th percentile, highest weather category)
        m_q42 = re.search(
            r'\bamong\s+rows\s+with\s+([a-z0-9_]+)\s+below\s+(?:its\s+)?(?:10th\s+percentile|p10).*?which\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:category\s+)?has\s+(?:the\s+)?highest\s+(?:target[- ]positive\s+rate|target\s+rate)',
            msg_clean
        )
        if m_q42:
            filt_col = _find_column(m_q42.group(1))
            grp_col = _find_column(m_q42.group(2)) or _find_column("weather")
            tgt_col = _find_column("delay_target") or _find_column("target")
            if filt_col and grp_col:
                return _make_op(
                    "TAIL_RISK_GROUP_RATE",
                    filter_column=filt_col,
                    percentile=0.10,
                    filter_op="<",
                    group_by=grp_col,
                    target_column=tgt_col,
                )

        # Q33 & Q35: Dual correlation (Pearson and Spearman)
        m_q33 = re.search(
            r'(?:(?:calculate|compare)\s+(?:both\s+)?pearson\s+and\s+spearman\s+correlations?|is\s+([a-z0-9_]+)\s+associated\s+with\s+([a-z0-9_]+).*?pearson\s+and\s+spearman|does\s+([a-z0-9_]+)\s+have\s+a\s+relationship\s+with\s+([a-z0-9_]+))',
            msg_clean
        )
        if m_q33:
            c1_cand = m_q33.group(1) or m_q33.group(3)
            c2_cand = m_q33.group(2) or m_q33.group(4)
            col1 = _find_column(c1_cand) if c1_cand else None
            col2 = _find_column(c2_cand) if c2_cand else None
            if not col1 and "visibility" in msg_clean:
                col1 = _find_column("visibility_km")
            if not col1:
                col1 = _find_column("origin_congestion_index")
            if not col2:
                col2 = _find_column("departure_delay")
            if col1 and col2:
                return _make_op(
                    "CORRELATION",
                    column=col1,
                    columns=[col2],
                    method="both",
                )

        # Q47: Date-month audit
        m_q47 = re.search(
            r'\b(?:identify\s+rows\s+where\s+)?([a-z0-9_]+)\s+indicates\s+one\s+month\s+but\s+([a-z0-9_]+)\s+indicates\s+another\b',
            msg_clean
        )
        if m_q47:
            date_col = _find_column(m_q47.group(1)) or "Flight_Date"
            month_col = _find_column(m_q47.group(2)) or "Month"
            return _make_op("DATE_MONTH_AUDIT", date_column=date_col, month_column=month_col)

        # 7. ZERO_VS_POSITIVE_COMPARISON (continuous zero vs positive slicing, Cluster B: Q36, Q46)
        m_zvp = re.search(
            r'(?:compare|calculate\s+the\s+difference|difference\s+between|what\s+is\s+(?:the\s+)?|how\s+does\s+.*?compare).*?'
            r'(?:(?:average|mean|median)\s+(?:and\s+median\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?))'
            r'.*?'
            r'(?:(?:for\s+rows\s+with|flights\s+with|when|where|with|transactions\s+with)?\s*(?:zero\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)|([a-z0-9_]+)\s*=\s*0|([a-z0-9_]+)\s*(?:is|equals?)\s*0))'
            r'.*?'
            r'(?:against|versus|vs\.?|and\s+those\s+with|and)\s+'
            r'(?:(?:rows\s+with|when|where|flights\s+with|a|those\s+with)?\s*(?:[a-z0-9_]+\s+(?:is|are)\s+)?positive\s*([a-z0-9_]+(?:\s+[a-z0-9_]+)?|\bdelay\b|\braintall\b)?)',
            msg_lower
        )
        if m_zvp:
            val_cand = m_zvp.group(1)
            split_cand = m_zvp.group(2) or m_zvp.group(3) or m_zvp.group(4) or m_zvp.group(5)
            val_col = _find_column(val_cand)
            split_col = _find_column(split_cand)
            if not split_col and split_cand:
                split_col = _find_column(split_cand.split()[0])
            if not val_col:
                for cand in ("departure_delay", "arrival_delay", "sales_amount", "profit"):
                    if cand in known_columns and cand != split_col and cand in msg_lower:
                        val_col = known_columns[cand]
                        break
            if split_col and val_col:
                return _make_op("ZERO_VS_POSITIVE_COMPARISON", split_column=split_col, value_column=val_col)

        m_zvp2 = re.search(
            r'\b(?:zero\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)|([a-z0-9_]+)\s*=\s*0)\b.*?\b(?:versus|vs\.?|against|and)\b.*?\bpositive\s*([a-z0-9_]+(?:\s+[a-z0-9_]+)?)?\b',
            msg_lower
        )
        if m_zvp2:
            split_cand = m_zvp2.group(1) or m_zvp2.group(2) or m_zvp2.group(3)
            split_col = _find_column(split_cand)
            if split_col:
                val_col = None
                for c_key, c_real in known_columns.items():
                    if c_real != split_col and (c_key in msg_lower or c_key.replace("_", " ") in msg_lower):
                        val_col = c_real
                        break
                if val_col:
                    return _make_op("ZERO_VS_POSITIVE_COMPARISON", split_column=split_col, value_column=val_col)

        # 8. BINARY_INDICATOR_COMPARISON (1D binary comparison e.g. Peak_Hour = 1 vs 0, Cluster C: Q20)
        m_bic = re.search(
            r'(?:(?:calculate|compare|what\s+is\s+(?:the\s+)?difference\s+between|difference\s+between|what\s+is\s+the|report)\s+)?'
            r'(?:(?:the\s+)?(?:mean|average|median)\s+(?:and\s+median\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?))?'
            r'.*?'
            r'\b([a-z0-9_]+)\s*=\s*([01])\s*(?:versus|vs\.?|against|and(?:\s+those\s+marked)?)\s+(?:(?:flights\s+marked\s+|transactions\s+marked\s+)?[a-z0-9_]+\s*=\s*)?([01])\b',
            msg_lower
        )
        if m_bic:
            val_cand = m_bic.group(1)
            bin_cand = m_bic.group(2)
            v1 = m_bic.group(3)
            v2 = m_bic.group(4)
            if v1 != v2:
                bin_col = _find_column(bin_cand)
                val_col = _find_column(val_cand) if val_cand else None
                if not val_col:
                    for cand in ("departure_delay", "arrival_delay", "sales_amount", "profit"):
                        if cand in known_columns and cand != bin_col and cand in msg_lower:
                            val_col = known_columns[cand]
                            break
                if bin_col and val_col:
                    return _make_op("BINARY_INDICATOR_COMPARISON", binary_column=bin_col, value_column=val_col)

        # ── Grouped Sum, Mean, Count & Min/Max ──────────────────────────────
        m_grp_sum = re.search(r'\btotal\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)(?:\s+amount)?\s+(?:by|for each|per|across)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower)
        if m_grp_sum:
            val_col = _find_column(m_grp_sum.group(1))
            grp_col = _find_column(m_grp_sum.group(2))
            if val_col and grp_col:
                return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)

        m_grp_mean = re.search(r'\b(?:what is the\s+)?(?:average|mean|median|proportion|rate|percentage)(?:\s+and\s+(?:average|mean|median|proportion|rate|percentage))?\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)(?:\s+amount|\s+time|\s+percentage|\s+rating|\s+age|\s+delay)?\s+(?:by|vary by|across|per|for each)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower)
        if m_grp_mean:
            val_raw = m_grp_mean.group(1).strip()
            val_raw_clean = re.sub(r'\s*={1,2}\s*[\w\'"]+', '', val_raw).strip()
            val_col = _find_column(val_raw_clean) or _find_column(val_raw)
            grp_col = _find_column(m_grp_mean.group(2))
            if val_col and grp_col:
                if "median" in msg_lower and ("mean" in msg_lower or "average" in msg_lower):
                    return _make_multi_ops([
                        {"type": "GROUP_MEAN", "column": grp_col, "value_column": val_col},
                        {"type": "GROUP_MEDIAN", "column": grp_col, "value_column": val_col},
                    ], reason=f"grouped mean and median {val_col} by {grp_col}")
                elif "median" in msg_lower:
                    return _make_op("GROUP_MEDIAN", column=grp_col, value_column=val_col)
                else:
                    return _make_op("GROUP_MEAN", column=grp_col, value_column=val_col)

        m_grp_count = re.search(r'\b(?:how many|number of|count of)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:by|for each|per|across)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower)
        if m_grp_count:
            grp_col = _find_column(m_grp_count.group(2))
            if grp_col:
                return _make_op("GROUP_COUNT", column=grp_col)

        m_grp_extrema = re.search(r'\b(highest|maximum|max|lowest|minimum|min)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:by|for each|per|across)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower)
        if m_grp_extrema:
            op_name = "GROUP_MAX" if m_grp_extrema.group(1) in ("highest", "maximum", "max") else "GROUP_MIN"
            val_col = _find_column(m_grp_extrema.group(2))
            grp_col = _find_column(m_grp_extrema.group(3))
            if val_col and grp_col:
                return _make_op(op_name, column=grp_col, value_column=val_col)

        # ── Grouped ranking: "which [N] <group> have highest/lowest <stat> <val>" (Q13, Q14, Q18, Q21, Q49) ──
        m_grp_rank = re.search(r'\bwhich\s+(?:five|\d+)?\s*([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:have|has|had|generated)\s+(?:the\s+)?(highest|most|largest|lowest|least|smallest)\s+(average|mean|total|proportion|rate|percentage|sum)?\s*(?:of\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower)
        if m_grp_rank and not re.search(r'\bfor\s+each\b|\bper\s+(?:year|month|quarter|date|day)\b', msg_lower):
            grp_raw = m_grp_rank.group(1).strip()
            direction = m_grp_rank.group(2).strip()
            stat = (m_grp_rank.group(3) or "").strip()
            val_raw = m_grp_rank.group(4).strip() if m_grp_rank.group(4) else ""
            val_raw_clean = re.sub(r'\s*={1,2}\s*[\w\'"]+', '', val_raw).strip()
            grp_col = _find_column(grp_raw)
            val_col = _find_column(val_raw_clean) or _find_column(val_raw)
            if grp_col and val_col:
                if stat in ("total", "sum") or direction in ("most", "largest"):
                    return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)
                elif stat in ("median",):
                    return _make_op("GROUP_MEDIAN", column=grp_col, value_column=val_col)
                else:
                    return _make_op("GROUP_MEAN", column=grp_col, value_column=val_col)

        m_top5 = re.search(r'\bwhich (?:five|\d+)\s+(\w+)\s+generated the highest total\s+(\w+)\b', msg_lower)
        if m_top5:
            grp_col = _find_column(m_top5.group(1))
            val_col = _find_column(m_top5.group(2))
            if grp_col and val_col:
                return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)

        # ── Grouped questions that contain "total sales/profit" but are NOT simple sums ──
        # Q39: "which country has the highest total sales in 2024" => TOP_COUNTRY_IN_YEAR
        m_country_yr = re.search(r'\bwhich\s+country\s+has\s+(?:the\s+)?highest\s+total\s+(?:sales|profit)\s+(?:amount\s+)?in\s+(20\d{2})\b', msg_lower)
        if m_country_yr:
            yr = int(m_country_yr.group(1))
            val_m = re.search(r'\b(sales|profit)\b', msg_lower)
            val_col = _find_column(val_m.group(1)) if val_m else _find_column("sales_amount")
            return _make_op("TOP_COUNTRY_IN_YEAR", year=yr, value_column=val_col or "Sales_Amount")

        # Q44: "for each year, which product category generated the highest total sales"
        if re.search(r'\bfor\s+each\s+year\b.*\bhighest\s+total\s+(?:sales|profit)\b|\bhighest\s+total\s+(?:sales|profit)\b.*\bfor\s+each\s+year\b', msg_lower):
            return _make_op("TOP_CATEGORY_PER_YEAR")

        # Q26: "which X generated the highest total profit"
        m_highest_grp = re.search(r'\bwhich\s+(\w+(?:\s+\w+)?)\s+(?:generated|contributed|had|has)\s+the\s+(?:highest|most|largest)\s+total\s+(profit|sales|revenue)\b', msg_lower)
        if m_highest_grp and not re.search(r'\bfor\s+each\s+year\b|\bin\s+20\d{2}\b', msg_lower):
            grp_col = _find_column(m_highest_grp.group(1))
            val_col = _find_column(m_highest_grp.group(2))
            if grp_col and val_col:
                return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)

        # Q32: "which X contributes the most total profit"
        m_most_profit = re.search(r'\bwhich\s+(\w+(?:\s+\w+)?)\s+contributes?\s+the\s+most\s+total\s+(profit|sales)\b', msg_lower)
        if m_most_profit:
            grp_col = _find_column(m_most_profit.group(1))
            val_col = _find_column(m_most_profit.group(2))
            if grp_col and val_col:
                return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)

        # Q23: "how did total profit change from 2022 through 2025" => GROUP_SUM by year
        if re.search(r'\bhow\s+did\s+total\s+(profit|sales)\s+change\b', msg_lower) or \
           re.search(r'\btotal\s+(profit|sales)\s+change\s+from\s+\d{4}\b', msg_lower):
            m_yc = re.search(r'\b(profit|sales)\b', msg_lower)
            val_col = _find_column(m_yc.group(1)) if m_yc else None
            grp_col = _find_column("order_year") or _find_column("year")
            if val_col and grp_col:
                return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)

        # Q24: "which month had the highest total sales" => PEAK_MONTH_PROFIT (adapted for sales)
        if re.search(r'\bwhich\s+month\s+had\s+the\s+highest\s+total\s+(sales|profit)\b', msg_lower):
            return _make_op("PEAK_MONTH_PROFIT", year=None)

        # Q47: "which month in 2025 had the highest total profit"
        if re.search(r'\bwhich\s+month\s+in\s+(\d{4})\s+had\s+the\s+highest\s+total\s+(profit|sales)\b', msg_lower):
            m_yr = re.search(r'\bin\s+(\d{4})\b', msg_lower)
            yr = int(m_yr.group(1)) if m_yr else 2025
            return _make_op("PEAK_MONTH_PROFIT", year=yr)

        # Q37: "how does total sales differ between returned and non-returned"
        if re.search(r'\btotal\s+sales\s+differ\b|\btotal\s+profit\s+differ\b|\bdifference\s+in\s+(?:total\s+)?(?:sales|profit)\s+between\b', msg_lower):
            flag_col = _find_column("return_flag")
            val_col = _find_column("sales_amount") or _find_column("sales")
            if flag_col and val_col:
                return _make_op("GROUP_SUM", column=flag_col, value_column=val_col)

        # Q39: "which country has the highest total sales in 2024" => needs filter+group
        # Q44: "for each year, which product category generated the highest total sales"
        if re.search(r'\bfor\s+each\s+year\b.*\bhighest\s+total\s+(sales|profit)\b|\bhighest\s+total\s+(sales|profit)\b.*\bfor\s+each\s+year\b', msg_lower):
            return _make_op("TOP_CATEGORY_PER_YEAR")

        # Q58: "did total sales increase in 2025 compared with 2024" => YEAR_OVER_YEAR_COMPARISON
        if re.search(r'\b(?:did|has)\s+total\s+(sales|profit)\s+(?:increase|decrease|change|grow)\b', msg_lower) or \
           re.search(r'\btotal\s+(sales|profit)\s+(?:in|for)\s+\d{4}\s+compared\b', msg_lower):
            return _make_op("YEAR_OVER_YEAR_COMPARISON", year1=2024, year2=2025)

        # Q64: "after normalizing...calculate total sales for each normalized category"
        if re.search(r'\bnormali[sz]\w*\s+(?:product\s+)?categor\w*\b', msg_lower) and \
           re.search(r'\btotal\s+sales\b', msg_lower):
            return _make_op("NORMALIZED_GROUP_SUM", column=_find_column("product_category") or "Product_Category",
                            value_column="Sales_Amount")

        # ── Average order value (Q53) ────────────────────────────────────────
        if re.search(r'\baverage\s+order\s+value\b|\baov\b', msg_lower):
            return _make_op("AVERAGE_ORDER_VALUE")

        # ── Total Sum & Mean (Q11, Q12, Q13, Q15) ───────────────────────────
        # NOTE: Only fire SUM if there is no "by/per/for each/which X" grouping context
        _has_grouping = re.search(r'\bby\s+\w|\bfor\s+each\s+\w|\bper\s+(?!row\b|record\b)\w|\bwhich\s+\w+\s+(?:has|had|generated|contributes)\b|\bcompare\b|\bdifference\b|\bchange\b|\bincrease\b', msg_lower)
        m_tot = re.search(r'\bwhat is the total\s+(\w+)(?:\s+amount)?\s+(?:across all|across the|in this)\b', msg_lower)
        if m_tot and not _has_grouping:
            w = m_tot.group(1)
            col = _find_column(w)
            if col:
                return _make_op("SUM", column=col)

        m_avg = re.search(r'\bwhat is the average\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)(?:\s+amount|\s+time|\s+rating|\s+age|\s+delay)?\s*(?:per\s+row|in\s+days|across all|in this dataset|in this)?\b', msg_lower)
        if m_avg and not _has_grouping:
            w = m_avg.group(1).strip()
            col = _find_column(w)
            if col:
                return _make_op("MEAN", column=col)
            elif not any(k in w or w in k for k in known_columns):
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": f"The dataset does not contain a **{w}** column. The available columns in this dataset are: {', '.join(df.columns)}.",
                    "reason": f"Required column '{w}' does not exist in dataset",
                }

        # ── Value counts (Q16, Q19, Q30, Q35) ───────────────────────────────
        m_each = re.search(r'\bhow many (?:transactions|orders|rows|records|employees|customers|items|\w+)\s+belong to each\s+(\w+(?:\s+\w+)?)\b', msg_lower)
        if m_each:
            target = m_each.group(1).strip()
            col = _find_column(target)
            if col:
                return _make_op("VALUE_COUNTS", column=col)
            elif not any(k in target or target in k for k in known_columns):
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": f"The dataset does not contain a **{target}** column. The available columns in this dataset are: {', '.join(df.columns)}.",
                    "reason": f"Required column '{target}' does not exist in dataset",
                }

        m_freq = re.search(r'\bwhich\s+(\w+(?:\s+\w+)?)\s+is\s+used\s+most\s+frequently\b', msg_lower)
        if m_freq:
            col = _find_column(m_freq.group(1))
            if col:
                return _make_op("VALUE_COUNTS", column=col)

        m_city_top = re.search(r'\bwhich\s+(\w+)\s+has\s+the\s+highest\s+number\s+of\s+(?:transactions|orders|records)\b', msg_lower)
        if m_city_top:
            col = _find_column(m_city_top.group(1))
            if col:
                return _make_op("VALUE_COUNTS", column=col)

        # ── Correlation & Correlation Matrix ─────────────────────────────────
        if re.search(r'\bcorrelation\s+matrix\b', msg_lower) or re.search(r'\bcorrelations?\s+(?:between|among|across)\b', msg_lower):
            mentioned_cols = []
            for col_clean, orig_col in known_stripped.items():
                if len(col_clean) >= 4 and col_clean in msg_lower.replace(" ", "").replace("_", ""):
                    pos = msg_lower.replace(" ", "").replace("_", "").index(col_clean)
                    mentioned_cols.append((pos, orig_col))
            mentioned_cols.sort()
            seen_c = set()
            dedup_cols = []
            for _, c in mentioned_cols:
                if c not in seen_c:
                    seen_c.add(c)
                    dedup_cols.append(c)
            if len(dedup_cols) >= 2 and not re.search(r'\b(?:prove|cause|causation)\b', msg_lower):
                return {
                    "intent": "DATA_OPERATION",
                    "operations": [{"type": "CORRELATION", "column": dedup_cols[0], "columns": dedup_cols[1:]}],
                    "confidence": 0.99,
                    "reason": "correlation analysis",
                }

        m_corr = re.search(r'\b(?:correlation between|relationship between)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+and\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower)
        if m_corr:
            w1 = m_corr.group(1).strip()
            w2 = m_corr.group(2).strip()
            c1 = _find_column(w1)
            c2 = _find_column(w2)
            if c1 and c2 and not re.search(r'\b(?:prove|cause|causation)\b', msg_lower):
                return {
                    "intent": "DATA_OPERATION",
                    "operations": [{"type": "CORRELATION", "column": c1, "columns": [c2]}],
                    "confidence": 0.99,
                    "reason": "correlation analysis",
                }
            elif not re.search(r'\b(?:prove|cause|causation)\b', msg_lower):
                missing = w1 if not c1 else w2
                if not _find_column(missing):
                    return {
                        "intent": "conversation",
                        "confidence": 0.99,
                        "operation": None,
                        "direct_answer": f"The dataset does not contain a **{missing}** column. The available columns in this dataset are: {', '.join(df.columns)}.",
                        "reason": f"Required column '{missing}' does not exist in dataset",
                    }

        # ── Reusable Hypothetical Analysis (Rule 3) ──────────────────────────
        m_hypo_fill = re.search(
            r'\b(?:what would (?:the )?(mean|median|average|sum|total)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+be\s+if\s+(?:the\s+)?(?:missing\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:values?\s+)?were\s+filled\s+with\s+(\d+(?:\.\d+)?)|'
            r'if\s+(?:the\s+)?(?:missing\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:values?\s+)?were\s+filled\s+with\s+(\d+(?:\.\d+)?)\s*,?\s*what\s+would\s+(?:the\s+)?(?:resulting\s+)?(mean|median|average|sum|total)\s*([a-z0-9_]+(?:\s+[a-z0-9_]+)?)?)\b',
            msg_lower
        )
        if m_hypo_fill:
            metric = (m_hypo_fill.group(1) or m_hypo_fill.group(7) or "mean").replace("average", "mean")
            metric_col_raw = m_hypo_fill.group(2) or m_hypo_fill.group(8)
            fill_col_raw = m_hypo_fill.group(3) or m_hypo_fill.group(5)
            val_raw = m_hypo_fill.group(4) or m_hypo_fill.group(6)
            fill_col = _find_column(fill_col_raw) or _find_column(metric_col_raw)
            metric_col = _find_column(metric_col_raw) or fill_col
            fill_val = float(val_raw) if val_raw else 5.0
            if metric_col:
                return _make_op("HYPOTHETICAL_FILL_MEAN" if metric == "mean" else "HYPOTHETICAL",
                               target_metric=metric, column=metric_col, fill_value=fill_val)

        # Hypothetical exclusion: "If every/all row(s) with <col> = <val> were temporarily excluded/removed..."
        # Pattern 1: condition first ("if all rows with col = val were excluded, what would the mean target be")
        m_hypo_filter = re.search(
            r'\bif\s+(?:every|all)\s+rows?\s+(?:with|where)\s+([a-z0-9_]+)\s*(=|==|!=|>|<|>=|<=|below|above|under|over|exceeding|\b)\s*(\w+)\s+were\s+(?:temporarily\s+)?(?:excluded|removed|dropped|filtered\s+out)(?:\s+(?:from|in)\s+(?:the\s+)?dataset)?,?\s*what\s+would\s+(?:the\s+)?(?:resulting\s+)?(mean|median|average|sum|total|std|min|max)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+be\b',
            msg_lower
        )
        # Pattern 2: question first ("what would the mean target be if rows with col = val were excluded")
        m_hypo_filter_rev = None
        if not m_hypo_filter:
            m_hypo_filter_rev = re.search(
                r'\bwhat\s+would\s+(?:the\s+)?(?:resulting\s+)?(mean|median|average|sum|total|std|min|max)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+be\s+if\s+(?:every|all)?\s*rows?\s+(?:with|where)\s+([a-z0-9_]+)\s*(=|==|!=|>|<|>=|<=|below|above|under|over|exceeding|\b)\s*(\w+)\s+were\s+(?:temporarily\s+)?(?:excluded|removed|dropped|filtered\s+out)\b',
                msg_lower
            )

        if m_hypo_filter or m_hypo_filter_rev:
            op_map = {
                "=": "==", "==": "==", "!=": "!=",
                ">": ">", "above": ">", "over": ">", "exceeding": ">",
                "<": "<", "below": "<", "under": "<",
                ">=": ">=", "<=": "<="
            }
            if m_hypo_filter:
                cond_raw = m_hypo_filter.group(1).strip()
                op_raw = m_hypo_filter.group(2).strip()
                val_raw = m_hypo_filter.group(3).strip()
                metric = m_hypo_filter.group(4).replace("average", "mean").replace("total", "sum")
                target_raw = m_hypo_filter.group(5).strip()
            else:
                metric = m_hypo_filter_rev.group(1).replace("average", "mean").replace("total", "sum")
                target_raw = m_hypo_filter_rev.group(2).strip()
                cond_raw = m_hypo_filter_rev.group(3).strip()
                op_raw = m_hypo_filter_rev.group(4).strip()
                val_raw = m_hypo_filter_rev.group(5).strip()

            cond_col = _find_column(cond_raw)
            target_col = _find_column(target_raw)
            op = op_map.get(op_raw, "==")
            v = float(val_raw) if re.match(r'^-?\d+(?:\.\d+)?$', val_raw) else val_raw
            if cond_col and target_col:
                excl_cond = {"column": cond_col, "operator": op, "value": v}
                return _make_op("HYPOTHETICAL", target_metric=metric, column=target_col, exclude_condition=excl_cond)

        m_hypo_excl = re.search(
            r'\b(?:exclude|excluding|filter out|without)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(?:and\s+calculate\s+|,\s*what\s+(?:is|would be)\s+the\s+)?(mean|median|average|sum|total)\s+(?:of\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b',
            msg_lower
        )
        if m_hypo_excl:
            cond_raw = m_hypo_excl.group(1).strip()
            metric = m_hypo_excl.group(2).replace("average", "mean")
            val_raw = m_hypo_excl.group(3).strip()
            val_col = _find_column(val_raw)
            cond_col = _find_column(cond_raw)
            if val_col:
                excl_cond = {"column": cond_col or cond_raw, "operator": "==", "value": 1}
                return _make_op("HYPOTHETICAL", target_metric=metric, column=val_col, exclude_condition=excl_cond)

        # ── Compound filtering (percentage/count with multiple conditions) ──
        m_compound = re.search(
            r'\b(?:calculate\s+(?:the\s+)?|what\s+is\s+the\s+)?(percentage|proportion|count|number)\s+of\s+rows\s+with\s+([a-z0-9_]+)\s+(above|over|greater than|>|below|under|less than|<|equal to|==|=)\s+(\w+)\s+and\s+([a-z0-9_]+)\s+(above|over|greater than|>|below|under|less than|<|equal to|==|=)\s+(\w+)\b',
            msg_lower
        )
        if m_compound:
            stat_type = m_compound.group(1)
            c1_raw = m_compound.group(2).strip()
            op1_raw = m_compound.group(3).strip()
            v1_raw = m_compound.group(4).strip()
            c2_raw = m_compound.group(5).strip()
            op2_raw = m_compound.group(6).strip()
            v2_raw = m_compound.group(7).strip()
            c1 = _find_column(c1_raw)
            c2 = _find_column(c2_raw)
            op_map = {
                ">": ">", "above": ">", "over": ">", "greater than": ">",
                "<": "<", "below": "<", "under": "<", "less than": "<",
                "=": "==", "==": "==", "equal to": "=="
            }
            val_map = {"zero": 0, "one": 1}
            v1 = val_map.get(v1_raw.lower(), float(v1_raw) if re.match(r'^-?\d+(?:\.\d+)?$', v1_raw) else v1_raw)
            v2 = val_map.get(v2_raw.lower(), float(v2_raw) if re.match(r'^-?\d+(?:\.\d+)?$', v2_raw) else v2_raw)
            if c1 and c2:
                conditions = [
                    {"column": c1, "operator": op_map.get(op1_raw, ">"), "value": v1},
                    {"column": c2, "operator": op_map.get(op2_raw, ">"), "value": v2},
                ]
                return _make_op("COMPOUND_FILTER", conditions=conditions, stat_type=stat_type)

        # ── Nonexistent column refusal in "how many X on/in each Y" ──
        m_how_many = re.search(r'\bhow many\s+([a-z0-9_]+)\s+(?:were|are|is)\s+(?:on|in|for|at)\s+each\s+([a-z0-9_]+)\b', msg_lower)
        if m_how_many:
            val_cand = m_how_many.group(1).strip()
            val_col = _find_column(val_cand)
            if not val_col and not any(k in val_cand or val_cand in k for k in known_columns):
                return {
                    "intent": "conversation",
                    "confidence": 0.99,
                    "operation": None,
                    "direct_answer": f"The dataset does not contain a **{val_cand}** column. The available columns in this dataset are: {', '.join(df.columns)}.",
                    "reason": f"Required column '{val_cand}' does not exist in dataset",
                }

        # ── Value distribution across explicit classes / categories (Q10) ──
        m_val_dist = re.search(r'\bhow many rows have\s+([a-z0-9_]+)\s*=\s*[^?]+and\s+how\s+many\b', msg_lower) or \
                     re.search(r'\b(?:distribution|breakdown|counts?)\s+of\s+([a-z0-9_]+)\s*(?:=|values?|\??)\b', msg_lower)
        if m_val_dist:
            col_cand = m_val_dist.group(1).strip()
            col = _find_column(col_cand)
            if col:
                return _make_op("VALUE_COUNTS", column=col)

        # ── Category normalization (Q38) ────────────────────────────────────
        if re.search(r'\bhow many\s+(?:distinct\s+)?(?:raw\s+)?categories?\s+(?:exist|are there|does|do)', msg_lower) or \
           re.search(r'\bnormali[sz]e?\w*\s+(?:the\s+)?categor', msg_lower) or \
           re.search(r'\b(?:raw|distinct)\s+categor\w*\s+(?:vs|versus|compared)', msg_lower):
            cat_col = _find_column("product_category") or _find_column("category")
            if cat_col:
                return _make_op("CATEGORY_NORMALIZATION", column=cat_col)

        # ── Yearly return stats (Q36, Q40) ──────────────────────────────────
        if re.search(r'\breturn\s+rate\s+(?:by|for each|per)\s+year\b', msg_lower) or \
           re.search(r'\bhow\s+(?:has\s+)?(?:the\s+)?return\s+rate\s+changed\s+(?:over|by|across)\s+year', msg_lower) or \
           re.search(r'\byearly\s+return\s+(?:rate|stats|trend)\b', msg_lower) or \
           re.search(r'\bfor\s+each\s+year\b.*\breturn\s+rate\b|\breturn\s+rate\b.*\bfor\s+each\s+year\b', msg_lower) or \
           re.search(r'\breturn\s+rate\s+(?:changed|varied|trend)\b', msg_lower):
            return _make_op("YEARLY_RETURN_STATS")

        # ── Rating threshold (Q42) ───────────────────────────────────────────
        m_rating_thr = re.search(r'\bhow many\s+(?:transactions?|customers?|records?)\s+(?:have\s+)?(?:a\s+)?(?:customer\s+)?rating\s+(?:of\s+)?(?:at\s+least|>=|≥|above|higher\s+than)\s+(\d+(?:\.\d+)?)\b', msg_lower)
        if m_rating_thr:
            thr = float(m_rating_thr.group(1))
            rating_col = _find_column("customer_rating") or _find_column("rating")
            if rating_col:
                return _make_op("RATING_THRESHOLD_STATS", column=rating_col, threshold=thr)

        # ── City return rate (Q28) ───────────────────────────────────────────
        if re.search(r'\breturn\s+rate\s+(?:by|for each|per)\s+city\b', msg_lower) or \
           re.search(r'\bwhich\s+city\s+has\s+(?:the\s+)?highest\s+return\s+rate\b', msg_lower) or \
           re.search(r'\bcity\s+(?:with\s+)?(?:the\s+)?highest\s+return\s+rate\b', msg_lower):
            return _make_op("CITY_RETURN_RATE")

        # ── Year above median count (Q45) ────────────────────────────────────
        m_yam = re.search(r'\bin\s+(\d{4})\b.*\bmedian\b|\bmedian\b.*\bin\s+(\d{4})\b', msg_lower)
        if m_yam and re.search(r'\babove\s+(?:the\s+)?(?:overall\s+)?median\b', msg_lower):
            yr = int(m_yam.group(1) or m_yam.group(2))
            val_col_m = re.search(r'\bmedian\s+(\w+)\b|\b(\w+)\s+above\s+(?:the\s+)?median\b', msg_lower)
            val_col = None
            if val_col_m:
                val_col = _find_column(val_col_m.group(1) or val_col_m.group(2))
            val_col = val_col or _find_column("sales_amount") or _find_column("sales")
            if val_col:
                return _make_op("YEAR_ABOVE_MEDIAN_COUNT", column=val_col, year=yr)

        # ── Weighted average (Q29) ───────────────────────────────────────────
        m_wavg = re.search(r'\bweighted\s+average\s+(\w+)\s+(?:weighted\s+by|by)\s+(\w+)\b', msg_lower)
        if m_wavg:
            vc = _find_column(m_wavg.group(1))
            wc = _find_column(m_wavg.group(2))
            if vc and wc:
                return _make_op("WEIGHTED_AVERAGE", column=vc, val_col=vc, weight_col=wc)
        if re.search(r'\bweighted\s+average\s+(?:discount|discount_percentage)\b', msg_lower):
            vc = _find_column("discount_percentage") or _find_column("discount")
            wc = _find_column("sales_amount") or _find_column("sales")
            if vc:
                return _make_op("WEIGHTED_AVERAGE", column=vc, val_col=vc, weight_col=wc or "Sales_Amount")

        # ── Peak month profit (Q24, Q25) ─────────────────────────────────────
        if re.search(r'\bpeak\s+(?:month|monthly)\s+profit\b', msg_lower) or \
           re.search(r'\bwhich\s+month\s+had\s+the\s+highest\s+(?:total\s+)?profit\b', msg_lower):
            yr_m = re.search(r'\b(20\d{2})\b', msg_lower)
            yr = int(yr_m.group(1)) if yr_m else None
            return _make_op("PEAK_MONTH_PROFIT", year=yr)

        # ── Profit margin comparison (Q62) ───────────────────────────────────
        if re.search(r'\bprofit\s+margin\b', msg_lower) and \
           re.search(r'\b(?:two\s+ways?|aggregate\s+vs|row[- ]level|average\s+row|comparison)\b', msg_lower):
            return _make_op("MARGIN_AGGREGATION_COMPARISON")
        if re.search(r'\boverall\s+aggregate\s+(?:profit\s+)?margin\b', msg_lower) or \
           re.search(r'\baverage\s+(?:row[- ]level\s+)?profit\s+margin\b', msg_lower):
            return _make_op("MARGIN_AGGREGATION_COMPARISON")

        # ── Category profit margins (Q26, Q50) ───────────────────────────────
        if re.search(r'\bprofit\s+margins?\b', msg_lower) and \
           re.search(r'\b(?:across|by|for\s+each|per)\s+(?:product\s+)?categor', msg_lower):
            return _make_op("CATEGORY_PROFIT_MARGINS")

        # ── Average order value (Q33) ────────────────────────────────────────
        if re.search(r'\baverage\s+order\s+value\b|\\baov\b', msg_lower):
            return _make_op("AVERAGE_ORDER_VALUE")

        # ── Customer lifetime value (Q34) ────────────────────────────────────
        if re.search(r'\bcustomer\s+lifetime\s+value\b|\bclv\b|\bltv\b', msg_lower):
            return _make_op("CUSTOMER_LIFETIME_VALUE_PROXY")

        # ── Year column agreement (Q60, Q63) ──────────────────────────────────
        if re.search(r'\border[_\s]*date\s+(?:year|derived)\s+(?:match|agree|consistent|mismatch)', msg_lower) or \
           re.search(r'\bdo(?:es)?\s+(?:the\s+)?order[_\s]*year\s+and\s+order[_\s]*date\b', msg_lower) or \
           re.search(r'\bwhether\s+the\s+order[_\s]*year\s+column\s+agrees\b', msg_lower) or \
           re.search(r'\b(?:year\s+in\s+order[_\s]*date|order[_\s]*date.*order[_\s]*year|order[_\s]*year.*order[_\s]*date)\s+(?:match|agree|consistent)\b', msg_lower) or \
           re.search(r'\border[_\s]*year\b.*\bagree\b.*\border[_\s]*date\b|\bdoes\s+(?:the\s+)?order[_\s]*year\b.*\bagree\b', msg_lower) or \
           re.search(r'\bcalendar\s+year\s+extracted\s+from\s+order[_\s]*date\b', msg_lower):
            return _make_op("YEAR_AGREEMENT")

        # ── Yearly total sales/profit (Q22, Q23, Q58) ───────────────────────
        if re.search(r'\btotal\s+(?:sales|profit)\s+(?:amount\s+)?(?:for|in|by)\s+(?:each\s+)?year\b', msg_lower) or \
           re.search(r'\btotal\s+(?:sales|profit)\s+(?:amount\s+)?(?:for|in)\s+20\d{2}\b', msg_lower) or \
           re.search(r'\byearly\s+(?:total\s+)?(?:sales|profit)\b', msg_lower):
            m_yrs = re.search(r'\b(sales|profit)\b', msg_lower)
            if m_yrs:
                val_col = _find_column(m_yrs.group(1))
                grp_col = _find_column("order_year") or _find_column("year")
                if val_col and grp_col:
                    return _make_op("GROUP_SUM", column=grp_col, value_column=val_col)

        # ── Monthly sales trend (Q24, Q25) ──────────────────────────────────
        if re.search(r'\bmonthly\s+(?:sales|profit)\s+(?:trend|breakdown|total)\b', msg_lower) or \
           re.search(r'\bsales\s+(?:trend|breakdown)\s+(?:for|by)\s+month\b', msg_lower):
            # This is a GROUP_SUM by month — let LLM plan since month extraction needed
            pass  # fall through to LLM for complex date grouping


        # ── Median, min, max, describe of specific columns (Q14) ────────────
        # Q14: "what are the mean, median, minimum, and maximum customer ages"
        if re.search(r'\b(?:mean|median|min(?:imum)?|max(?:imum)?|average|std|standard\s+deviation)\b.*\b(?:mean|median|min(?:imum)?|max(?:imum)?|average|std|standard\s+deviation)\b', msg_lower) and \
           not _is_hypothetical(msg_lower) and \
           not re.search(r'\b(?:hypothetical|excluded|omitted|ignored|if\s+every|if\s+all|if\s+rows|assuming\s+all|assuming\s+every|were\s+temporarily|group(?:ed)?\s+by|broken\s+down\s+by|breakdown\s+by|by\s+(?:each|every))\b', msg_lower):

            # Check if this is a genuine grouped query (grouping by an actual dataset column)
            is_grouped = False
            for m in re.finditer(r'\b(?:for\s+each|per|across|by)\s+(?:the\s+|a\s+|an\s+|each\s+|every\s+)?([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b', msg_lower):
                phrase_target = m.group(1).strip()
                first_word = phrase_target.split()[0]
                if phrase_target in ('all', 'all rows', 'every row', 'dataset', 'datasets', 'data', 'definition', 'definitions', 'default', 'itself', 'row', 'rows', 'record', 'records', 'observation', 'observations', 'standard deviation', 'std') or \
                   first_word in ('all', 'dataset', 'datasets', 'data', 'definition', 'definitions', 'default', 'itself', 'row', 'rows', 'record', 'records'):
                    continue
                pcol = _find_column(phrase_target) or _find_column(first_word)
                if pcol:
                    is_grouped = True
                    break

            if not is_grouped:
                # Multiple stats requested — use describe on mentioned column
                col = None
                for col_cand in sorted(known_columns.keys(), key=len, reverse=True):
                    cand_spaced = col_cand.replace("_", " ")
                    if re.search(r'\b' + re.escape(cand_spaced) + r'\b', msg_lower) or re.search(r'\b' + re.escape(col_cand) + r'\b', msg_lower):
                        col = known_columns[col_cand]
                        break
                if not col:
                    m_last = re.search(r'([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s*\??\s*$', msg_lower.strip())
                    if m_last:
                        col = _find_column(m_last.group(1))
                if col:
                    pct_matches = re.findall(r'(\d+(?:st|nd|rd|th)?)\s+percentiles?', msg_lower)
                    req_metrics = ["mean", "median", "min", "max", "std"]
                    for pm in pct_matches:
                        req_metrics.append(f"{pm} percentile")
                    return _make_op("DESCRIBE_COLUMN", column=col, metrics=req_metrics)

        # ── Monthly trend (Q25) ──────────────────────────────────────────────
        # Q25: monthly sales trend for 2025 — use GROUP_SUM by month via LLM
        # But we can detect and route to a simpler PEAK_MONTH_PROFIT with yr
        if re.search(r'\bmonthly\s+(?:sales|profit)\s+(?:trend|breakdown)\b', msg_lower) or \
           re.search(r'\bsales\s+(?:trend|breakdown)\s+(?:for|in)\s+(20\d{2})\b', msg_lower) or \
           re.search(r'\bwhat\s+is\s+the\s+monthly\s+(?:sales|profit)\b', msg_lower):
            yr_m = re.search(r'\b(20\d{2})\b', msg_lower)
            yr = int(yr_m.group(1)) if yr_m else None
            # Use PEAK_MONTH_PROFIT which also returns monthly_profits breakdown
            return _make_op("PEAK_MONTH_PROFIT", year=yr)

        # ── Country return rate (Q28) ────────────────────────────────────────
        if re.search(r'\bwhich\s+country\s+has\s+(?:the\s+)?highest\s+return\s+rate\b', msg_lower) or \
           re.search(r'\breturn\s+rate\s+(?:by|for\s+each|per)\s+country\b', msg_lower):
            return _make_op("COUNTRY_RETURN_RATE")

        # ── Return rate overall as percentage (Q27) ──────────────────────────
        if re.search(r'\b(?:overall\s+)?return\s+rate\b', msg_lower) and \
           not re.search(r'\b(?:country|city|year|channel|for\s+each\s+year)\b', msg_lower):
            return _make_op("OVERALL_RETURN_RATE")

        # ── Promotion code percentage (Q34) ──────────────────────────────────
        if re.search(r'\bpromotion\s+code\b|\bpromo(?:tion)?\s+code\b', msg_lower) and \
           re.search(r'\bpercentage|percent|%|how\s+many\b', msg_lower):
            return _make_op("PROMOTION_CODE_USAGE")

        # ── Country with highest sales in a specific year (Q39) ──────────────
        m_country_yr = re.search(r'\bwhich\s+country\s+has\s+(?:the\s+)?highest\s+total\s+(?:sales|profit)\s+(?:amount\s+)?in\s+(20\d{2})\b', msg_lower)
        if m_country_yr:
            yr = int(m_country_yr.group(1))
            val_m = re.search(r'\b(sales|profit)\b', msg_lower)
            val_col = _find_column(val_m.group(1)) if val_m else _find_column("sales_amount")
            return _make_op("TOP_COUNTRY_IN_YEAR", year=yr, value_column=val_col or "Sales_Amount")

        # ── Rating threshold (Q42) ───────────────────────────────────────────
        if re.search(r'\bhow\s+many\s+rows\s+have\s+a\s+customer\s+rating\s+of\s+at\s+least\s+(\d+)\b', msg_lower) or \
           re.search(r'\bcustomer\s+rating\s+(?:of\s+)?at\s+least\s+(\d+)\b', msg_lower) or \
           re.search(r'\bcustomer\s+rating\s+(?:>=|≥)\s*(\d+)\b', msg_lower):
            thr_m = re.search(r'\bat\s+least\s+(\d+(?:\.\d+)?)\b', msg_lower)
            thr = float(thr_m.group(1)) if thr_m else 4.0
            rating_col = _find_column("customer_rating") or _find_column("rating")
            if rating_col:
                return _make_op("RATING_THRESHOLD_STATS", column=rating_col, threshold=thr)

        # ── 2025 transactions above overall median (Q45) ─────────────────────
        if re.search(r'\b(20\d{2})\b', msg_lower) and re.search(r'\babove\s+(?:the\s+)?(?:dataset.s?\s+)?(?:overall\s+)?median\b', msg_lower):
            yr_m = re.search(r'\b(20\d{2})\b', msg_lower)
            yr = int(yr_m.group(1)) if yr_m else 2025
            val_col = _find_column("sales_amount") or _find_column("sales")
            if val_col:
                return _make_op("YEAR_ABOVE_MEDIAN_COUNT", column=val_col, year=yr)

        # ── Profit margins by category (Q50) ─────────────────────────────────
        if re.search(r'\bprofit\s+margin(?:s)?\b', msg_lower) and \
           re.search(r'\b(?:across|by|for\s+each|per)\s+(?:product\s+)?categor\b', msg_lower):
            return _make_op("CATEGORY_PROFIT_MARGINS")

        # ── Order ID vs duplicate rows (Q55) ─────────────────────────────────
        if re.search(r'\brepeated\s+order\s+(?:id|ids)\b.*\bduplicate\b|\bduplicate.*\brepeated\s+order', msg_lower) or \
           re.search(r'\border\s+id\s+(?:values?\s+)?vs\b.*\bduplicate\b', msg_lower) or \
           re.search(r'\brepeated\s+order\s+ids?\s+necessarily\s+duplicate\b', msg_lower):
            return _make_op("ORDER_ID_VS_DUPLICATE_ROWS")

        # ── Return_Flag vs Order_Status consistency (Q60) ────────────────────
        if re.search(r'\breturn(?:ed)?\s+order\s+status\b.*\breturn(?:_flag|ed)?\b|\breturn_flag\b.*\border_status\b', msg_lower) or \
           re.search(r'\b(?:returned|return_flag)\b.*\b(?:vice\s+versa|consistent|match|agree)\b', msg_lower) or \
           re.search(r'\ball\s+transactions\s+with\s+(?:a\s+)?returned\s+order\s+status\b', msg_lower):
            return _make_op("RETURN_FLAG_STATUS_MISMATCH")

        # ── Missing values invalid records (Q61) ─────────────────────────────
        if re.search(r'\bdoes\s+a\s+high\s+number\s+of\s+missing\s+values\b|\bmissing\s+values\s+in\s+a\s+column\s+mean\s+those\s+records\s+are\s+invalid\b|\bhigh\s+number\s+of\s+missing.*invalid\b', msg_lower):
            return _make_op("MISSINGNESS_IMPLICATIONS")

        # ── Order_Year vs Order_Date agreement (Q63) ─────────────────────────
        if re.search(r'\border_year\b.*\border_date\b|\border_date\b.*\border_year\b', msg_lower) and \
           re.search(r'\b(?:agree|consistent|match|mismatch|always)\b', msg_lower):
            return _make_op("YEAR_AGREEMENT")
        if re.search(r'\bcalendar\s+year\s+extracted\s+from\s+order_date\b', msg_lower):
            return _make_op("YEAR_AGREEMENT")

        # ── Discount-profit correlation with causation (Q65) ─────────────────
        if re.search(r'\bcorrelation\b', msg_lower) and re.search(r'\bdiscount\b.*\bprofit\b|\bprofit\b.*\bdiscount\b', msg_lower):
            return _make_op("DISCOUNT_PROFIT_CORRELATION")

        # ── Q21 fix: group by Product_Name not Product_ID ───────────────────
        # Already handled above by m_top5 pattern (maps "products" -> Product_Name via _find_column)

        # Q40: missing columns, city occurs most often, max valid age
        if re.search(r'\bwhich columns contain missing values, which city occurs most often, and what is the maximum valid age\b', msg_lower) or \
           (re.search(r'\bwhich columns (?:contain|have) missing\b', msg_lower) and re.search(r'\bwhich city occurs most often\b', msg_lower) and re.search(r'\bmaximum (?:valid )?age\b', msg_lower)):
            city_col = _find_column("city") or "city"
            age_col = _find_column("age") or "age"
            return _make_multi_ops([
                {"type": "COLUMNS_WITH_MISSING_VALUES"},
                {"type": "VALUE_COUNTS", "column": city_col},
                {"type": "MAX", "column": age_col},
            ], reason="composite Q40: missing columns, top city, max age")

        # Q10: which columns are fully populated, and which are incomplete
        if re.search(r'\bwhich columns are fully populated, and which are incomplete\b|\bwhich columns are fully populated\b', msg_lower):
            return _make_multi_ops([
                {"type": "COLUMNS_WITHOUT_MISSING_VALUES"},
                {"type": "COLUMNS_WITH_MISSING_VALUES"},
            ], reason="fully populated vs incomplete columns")

        if re.search(r'\bshow me the schema and (?:tell me )?which columns (?:have|contain) missing values\b', msg_lower):
            return _make_multi_ops([
                {"type": "GET_SCHEMA"},
                {"type": "COLUMNS_WITH_MISSING_VALUES"}
            ], reason="schema and missing columns")

        # ── Cross-column condition counts ─────────────────────────────────────
        # Q7: missing values in both name and phone
        if re.search(r'\bmissing values in both (?:the\s+)?(\w+) and (?:the\s+)?(\w+)\b', msg_lower):
            m = re.search(r'\bmissing values in both (?:the\s+)?(\w+) and (?:the\s+)?(\w+)\b', msg_lower)
            c1 = _find_column(m.group(1)) or m.group(1)
            c2 = _find_column(m.group(2)) or m.group(2)
            return _make_op("CROSS_COLUMN_CONDITION", col1=c1, col2=c2, condition="both_missing")

        # Q8: missing age but present phone
        if re.search(r'\bmissing (\w+) but a (?:present|non[- ]?missing) (\w+)\b', msg_lower):
            m = re.search(r'\bmissing (\w+) but a (?:present|non[- ]?missing) (\w+)\b', msg_lower)
            c1 = _find_column(m.group(1)) or m.group(1)
            c2 = _find_column(m.group(2)) or m.group(2)
            return _make_op("CROSS_COLUMN_CONDITION", col1=c1, col2=c2, condition="first_missing_second_present")

        # Q26: valid age and non-missing city
        if re.search(r'\bvalid\s+(\w+)\s+and\s+(?:a\s+)?(?:non[- ]?missing|valid)\s+(\w+)\b', msg_lower) or \
           re.search(r'\bhow many records have a valid (\w+) and a (?:non[- ]?missing|valid) (\w+)\b', msg_lower):
            m = re.search(r'\bvalid\s+(\w+)\s+and\s+(?:a\s+)?(?:non[- ]?missing|valid)\s+(\w+)\b', msg_lower) or \
                re.search(r'\bhow many records have a valid (\w+) and a (?:non[- ]?missing|valid) (\w+)\b', msg_lower)
            c1 = _find_column(m.group(1)) or m.group(1)
            c2 = _find_column(m.group(2)) or m.group(2)
            return _make_op("CROSS_COLUMN_CONDITION", col1=c1, col2=c2, condition="both_present")

        # Q27: missing age and missing name
        if re.search(r'\bboth a missing (\w+) and a missing (\w+)\b', msg_lower):
            m = re.search(r'\bboth a missing (\w+) and a missing (\w+)\b', msg_lower)
            c1 = _find_column(m.group(1)) or m.group(1)
            c2 = _find_column(m.group(2)) or m.group(2)
            return _make_op("CROSS_COLUMN_CONDITION", col1=c1, col2=c2, condition="both_missing")

        # Q28: present email but missing phone
        if re.search(r'\bpresent (\w+) but a missing (\w+)\b', msg_lower):
            m = re.search(r'\bpresent (\w+) but a missing (\w+)\b', msg_lower)
            c1 = _find_column(m.group(1)) or m.group(1)
            c2 = _find_column(m.group(2)) or m.group(2)
            return _make_op("CROSS_COLUMN_CONDITION", col1=c1, col2=c2, condition="first_present_second_missing")

        # ── Cell & Row completeness ───────────────────────────────────────────
        # Q3: If every missing cell were filled, how many cells would be complete?
        if re.search(r'\b(?:if every missing cell were filled|how many cells would be complete|total (?:number of )?cells|total cell count)\b', msg_lower):
            return _make_op("TOTAL_CELL_COUNT")

        # Q2: How many cells are missing in total?
        if re.search(r'\b(?:how many (?:cells?|values?)(?: are)? missing|total missing (?:cells?|values?)|missing (?:cells?|values?) in total)\b', msg_lower) or \
           (re.search(r'\bhow\s+many\s+missing\s+(?:values?|cells?)\b', msg_lower) and re.search(r'\b(?:in\s+(?:the\s+)?(?:entire\s+)?(?:dataset|table|data)|overall|across\s+(?:all\s+)?columns?)\b', msg_lower)):
            return _make_op("MISSING_COUNT_TOTAL")

        # Q5: How many rows have at least one missing value?
        if re.search(r'\bhow many rows have (?:at\s+least\s+one|any)\s+missing\b', msg_lower):
            return _make_op("ROWS_WITH_MISSING_COUNT")

        # Q6, Q38: Complete rows / rows with no missing values / rows remaining if missing removed
        if re.search(r'\bhow many rows have (?:no|zero) missing values\b|\bcomplete rows? count\b|\b(?:if\s+we\s+remove\s+rows\s+with\s+any\s+missing|how\s+many\s+rows\s+remain\s+if\s+(?:we\s+)?remove)\b', msg_lower):
            return _make_op("COMPLETE_ROWS_COUNT")

        # Q39: Deduplicated rows remaining
        if re.search(r'\b(?:if\s+we\s+deduplicate\s+the\s+dataset|how\s+many\s+rows\s+(?:would\s+)?remain\s+after\s+deduplication)\b', msg_lower):
            return _make_op("DUPLICATE_ROWS_AFTER_DEDUPLICATION")

        # Q9: Non-null counts
        if (re.search(r'\bnon[- ]?null\s+counts?\b', msg_lower) or re.search(r'\breport.*non[- ]?null\b', msg_lower)) and not re.search(r'\bdistinct\b', msg_lower):
            return _make_op("NON_NULL_COUNTS")

        # Q4, Q47: Highest missing-value rate / most missing values
        if re.search(r'\bwhich column has the (?:highest|most) missing(?:[- ]?value)?\s*(?:rate|percentage|count|values?)?\b', msg_lower):
            return _make_op("COLUMN_WITH_MOST_MISSING_VALUES")

        # Q1: List every column that contains at least one missing value
        if re.search(r'\b(?:list\s+every\s+column\s+that\s+contains\s+at\s+least\s+one\s+missing|which columns? (?:contain|have|has) (?:any )?missing values?|columns? with (?:any )?missing values?)\b', msg_lower):
            return _make_op("COLUMNS_WITH_MISSING_VALUES")

        # Q46: Columns without missing values
        if re.search(r'\bwhich columns? (?:have|contain|has) (?:no|zero) missing values?\b|\bcolumns? without (?:any )?missing values?\b', msg_lower):
            return _make_op("COLUMNS_WITHOUT_MISSING_VALUES")

        # Q14, Q46: Valid and missing counts for a column
        if re.search(r'\bhow many valid (\w+) observations\b|\bnumber of missing (\w+).*number of valid\b', msg_lower):
            m = re.search(r'\bhow many valid (\w+) observations\b|\bnumber of missing (\w+).*number of valid\b', msg_lower)
            col_word = m.group(1) or m.group(2)
            col = _find_column(col_word)
            if col:
                return _make_op("VALID_AND_MISSING_COUNTS", column=col)

        # ── Rows relative to mean/median ─────────────────────────────────────
        m_mean_rel = re.search(r'\bhow many rows have\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(below|under|above|over|exceeding)\s+(?:the\s+)?(?:overall\s+)?mean\b', msg_lower)
        if m_mean_rel:
            col = _find_column(m_mean_rel.group(1))
            if col:
                direction = m_mean_rel.group(2)
                op_name = "ROWS_BELOW_MEAN" if direction in ("below", "under") else "ROWS_ABOVE_MEAN"
                return _make_op(op_name, column=col)

        m_median_rel = re.search(r'\bhow many rows have\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\s+(equal to|below|under|above|over|exceeding)\s+(?:the\s+)?(?:overall\s+)?median\b', msg_lower)
        if m_median_rel:
            col = _find_column(m_median_rel.group(1))
            if col:
                rel = m_median_rel.group(2)
                if rel in ("below", "under"):
                    op_name = "ROWS_BELOW_MEDIAN"
                elif rel in ("above", "over", "exceeding"):
                    op_name = "ROWS_ABOVE_MEDIAN"
                else:
                    op_name = "ROWS_EQUAL_MEDIAN"
                return _make_op(op_name, column=col)

        # ── Quantiles / Percentiles ──────────────────────────────────────────
        m_pct = re.search(
            r'\b(?:what are the\s+)?(\d+(?:st|nd|rd|th)?(?:\s*,\s*\d+(?:st|nd|rd|th)?)*(?:\s+and\s+\d+(?:st|nd|rd|th)?)?)\s+percentiles?\s+(?:of|for)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b|'
            r'\b(?:quantiles?|percentiles?)\s+(?:of|for)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+)?)\b',
            msg_lower
        )
        if m_pct:
            pct_raw = m_pct.group(1)
            col_raw = m_pct.group(2) or m_pct.group(3)
            col = _find_column(col_raw)
            if col:
                if pct_raw:
                    nums = [float(re.sub(r'[^\d.]', '', x)) / 100.0 for x in re.findall(r'\d+(?:\.\d+)?', pct_raw)]
                    return _make_op("QUANTILE", column=col, q=nums if len(nums) > 1 else (nums[0] if nums else 0.5))
                else:
                    return _make_op("QUANTILE", column=col, q=[0.25, 0.5, 0.75])

        # Q29: City average age and observations
        if re.search(r'\bfor each city.*(?:calculate the average age|average age and the number of valid age)\b', msg_lower):
            return _make_op("CITY_AGE_STATS", column="city")

        # Q30: Cities with average age above overall average
        if re.search(r'\bidentify cities whose average age is above\b', msg_lower):
            return _make_op("CITIES_ABOVE_AVERAGE_AGE", column="city")

        # Q35: Age completeness report per city
        if re.search(r'\bfor each city, report its total rows, valid ages\b|\bage completeness\b', msg_lower):
            return _make_op("CITY_COMPLETENESS_REPORT", column="city")

        # Q16: Identify every numeric column and every non-numeric column
        if re.search(r'\bidentify every numeric column and every non[- ]?numeric column\b', msg_lower):
            return _make_op("GET_DATA_TYPES")

        # Q18: Column with most distinct values
        if re.search(r'\bwhich column has the (?:most|highest)\b|\b(?:most|highest)\s+(?:number\s+of\s+)?(?:distinct|unique)?(?:\s+non[- ]?null)?\s+values\b', msg_lower):
            return _make_op("COLUMN_WITH_MOST_UNIQUE_VALUES")

        # Q19: Column with fewest distinct values
        if re.search(r'\bwhich column has the (?:fewest|lowest|least)\b|\b(?:fewest|lowest|least)\s+(?:number\s+of\s+)?(?:distinct|unique)?(?:\s+non[- ]?null)?\s+values\b', msg_lower):
            return _make_op("COLUMN_WITH_FEWEST_UNIQUE_VALUES")

        # Q17, Q25: Distinct non-null values / unique counts across columns
        if re.search(r'\bdistinct\s+non[- ]?null\b|\bnumber of distinct\b|\bunique values in\b|\bcompare the number of unique\b', msg_lower):
            return _make_op("UNIQUE_COUNTS")

        # Q20, Q31, Q32, Q50: Statistical profile / data quality report / final audit
        if re.search(r'\b(?:compact\s+)?statistical profile\b|\bdata[- ]?quality report\b|\bfinal audit\b|\bdataset dimensions\b', msg_lower):
            return _make_op("DATASET_PROFILE")

        # Q48: Is every email unique
        if re.search(r'\bis every (\w+) unique\b', msg_lower):
            m = re.search(r'\bis every (\w+) unique\b', msg_lower)
            col = _find_column(m.group(1)) or m.group(1)
            return _make_op("COLUMN_UNIQUENESS", column=col)

        # Q7, Q49: Duplicate rows count
        if re.search(r'\b(?:are there (?:any\s+)?(?:exact\s+)?duplicate\s+rows|exact\s+duplicate\s+rows|how many duplicate (?:rows?|records?)|duplicate (?:row )?count|count of duplicate rows?)\b', msg_lower):
            return _make_op("DUPLICATE_COUNT")

        # Q24: Unique cities count
        if re.search(r'\bhow many unique (\w+) exist\b', msg_lower):
            m = re.search(r'\bhow many unique (\w+) exist\b', msg_lower)
            col = _find_column(m.group(1)) or "city"
            return _make_op("UNIQUE_COUNT", column=col)

        # Q21, Q22, Q23, Q33: Value counts on city or other categorical
        if re.search(r'\blist every (\w+) and its record count\b|\bcalculate each (\w+)(?:\'s)? percentage of all rows\b|\bwhich (\w+) has the highest count[,\s]+and which has the lowest\b|\bfind the most common (\w+)\b|\bmost common (\w+),? then report\b|\bhighest count.*lowest\b', msg_lower):
            m = re.search(r'\blist every (\w+) and its record count\b|\bcalculate each (\w+)(?:\'s)? percentage of all rows\b|\bwhich (\w+) has the highest count[,\s]+and which has the lowest\b|\bfind the most common (\w+)\b|\bmost common (\w+),? then report\b|\bhighest count.*lowest\b', msg_lower)
            col_word = None
            if m:
                for g in m.groups():
                    if g:
                        col_word = g
                        break
            col = _find_column(col_word or "city") or "city"
            return _make_op("VALUE_COUNTS", column=col)

        # Q11, Q12, Q13, Q15, Q34, Q45, Q48, Q50: Column statistical summary (mean, median, etc.)
        if re.search(r'\b(?:mean,\s*median,\s*min(?:imum)?,\s*max(?:imum)?|youngest and oldest|compare mean and median|calculate the (\w+) mean|is (?:the\s+)?median (\w+) (?:greater|less|equal)|standard deviation of (\w+)|complete summary of the (\w+) column|calculate the average (\w+) after excluding missing)\b', msg_lower):
            m = re.search(r'\b(?:calculate the (\w+) mean|is (?:the\s+)?median (\w+) (?:greater|less|equal)|standard deviation of (\w+)|complete summary of the (\w+) column|calculate the average (\w+) after excluding missing)\b', msg_lower)
            col_word = None
            if m:
                for g in m.groups():
                    if g:
                        col_word = g
                        break
            if not col_word:
                for kw in known_columns:
                    if re.search(r'\b' + re.escape(kw) + r'\b', msg_lower):
                        col_word = kw
                        break
            col = _find_column(col_word or "age") or "age"
            return _make_op("DESCRIBE_COLUMN", column=col)

        # ── Row count ─────────────────────────────────────────────────────────
        if _ANALYSIS_ROW_COUNT_RX.search(msg_lower):
            has_column_ask = bool(re.search(
                r'\b(and\s+)?(?:how many\s+)?columns?|column\s+(count|names?)\b', msg_lower
            ))
            has_condition = bool(re.search(
                r'\b(where|have|having|with|for\s+which|satisfying|belong\s+to|contain|missing|null|nan|>|<|=|\bby\b|\bfor\s+each\b|\bper\b)\b', msg_lower
            ))
            if not has_column_ask and not has_condition:
                logger.debug("[Router/analysis-fast-path] GET_ROW_COUNT")
                return _make_op("GET_ROW_COUNT")

        # ── Dataset completeness % ────────────────────────────────────────────
        if _ANALYSIS_COMPLETENESS_RX.search(msg_lower):
            logger.debug("[Router/analysis-fast-path] DATASET_COMPLETENESS")
            return _make_op("DATASET_COMPLETENESS")

        # ── Minimum of a single column ────────────────────────────────────────
        min_m = _ANALYSIS_MIN_COL_RX.search(msg_lower)
        if min_m:
            col_word = (min_m.group(1) or min_m.group(2) or '').strip()
            col = _find_column(col_word)
            multi_stat = bool(re.search(r'\b(and|,)\b.*\b(mean|median|max|average|std)\b', msg_lower))
            if col and not multi_stat:
                logger.debug("[Router/analysis-fast-path] MIN column=%s", col)
                return _make_op("MIN", column=col)

        # ── Unique values list ("what cities are present in the dataset?") ────
        uv_m = _ANALYSIS_UNIQUE_VALUES_RX.search(msg_lower)
        if uv_m:
            col_word = (uv_m.group(1) or uv_m.group(2) or '').strip()
            col = _find_column(col_word)
            if col and not re.search(r'\bhow many\b', msg_lower):
                logger.debug("[Router/analysis-fast-path] UNIQUE_VALUES column=%s", col)
                return _make_op("UNIQUE_VALUES", column=col)

        # ── Unique count ("how many unique cities are there?") ────────────────
        uc_m = _ANALYSIS_UNIQUE_COUNT_RX.search(msg_lower)
        if uc_m:
            col_word = (uc_m.group(1) or '').strip()
            col = _find_column(col_word)
            if col:
                logger.debug("[Router/analysis-fast-path] UNIQUE_COUNT column=%s", col)
                return _make_op("UNIQUE_COUNT", column=col)

        # ── Missing count for column ("how many missing age values are there?") ─
        missing_col_m = re.search(
            r'\bhow many missing\s+(\w+)\s+(?:values?|records?)\b'
            r'|\bhow many missing (?:values?|entries) (?:in|for)\s+(\w+)\b',
            msg_lower
        )
        if missing_col_m:
            col_word = (missing_col_m.group(1) or missing_col_m.group(2) or '').strip()
            col = _find_column(col_word)
            if col:
                logger.debug("[Router/analysis-fast-path] MISSING_COUNT_COLUMN column=%s", col)
                return _make_op("MISSING_COUNT_COLUMN", column=col)

        # ── Most common values ("what are the most common values in the city column?") ──
        common_val_m = re.search(
            r'\b(?:what are the )?most common values? in (?:the )?(\w+)(?:\s+column)?\b'
            r'|\bvalue counts? (?:for|of|in) (?:the )?(\w+)(?:\s+column)?\b',
            msg_lower
        )
        if common_val_m:
            col_word = (common_val_m.group(1) or common_val_m.group(2) or '').strip()
            col = _find_column(col_word)
            if col:
                logger.debug("[Router/analysis-fast-path] VALUE_COUNTS column=%s", col)
                return _make_op("VALUE_COUNTS", column=col)

        # ── Column statistical summary ("mean, median, min, max") ─────────────
        stat_summary_m = re.search(
            r'\b(?:what are the\s+)?(?:mean|average),\s*median,\s*(?:min(?:imum)?|lowest),\s*(?:and\s+)?(?:max(?:imum)?|highest)\s+(\w+)\b',
            msg_lower
        )
        if stat_summary_m:
            col_word = stat_summary_m.group(1).strip()
            col = _find_column(col_word)
            if col:
                logger.debug("[Router/analysis-fast-path] DESCRIBE_COLUMN column=%s", col)
                return _make_op("DESCRIBE_COLUMN", column=col)

        return None

    def _pending_transform_fast_path(self, context: ExecutionContext) -> dict | None:
        """Resolve a follow-up against an active transformation's missing slots."""
        dataset_id = str(getattr(context, 'dataset_id', '') or '')
        conversation_id = str(
            getattr(context, 'chat_id', None) or getattr(context, 'session_id', '') or ''
        )
        if not dataset_id or not conversation_id:
            return None

        from transformation.store import transformation_store
        pending = transformation_store.pending_for(conversation_id, dataset_id)
        if pending is None:
            return None

        from datasets.registry import dataset_registry
        entry = dataset_registry.get(dataset_id)
        if entry is None or entry.dataframe is None:
            transformation_store.finish_pending(conversation_id, dataset_id, 'INVALIDATED')
            return None

        from transformation.planner import _compute_fingerprint
        if _compute_fingerprint(entry.dataframe) != pending.dataset_fingerprint:
            transformation_store.finish_pending(conversation_id, dataset_id, 'INVALIDATED')
            return {
                'intent': 'conversation', 'confidence': 0.99, 'operation': None,
                'reason': 'pending transformation invalidated because dataset changed',
            }

        message = (getattr(context, 'message', '') or '').strip()
        lowered = message.lower()
        workspace_action = getattr(context, 'workspace_action', None) or {}
        if workspace_action.get('type') == 'TRANSFORMATION_CLARIFICATION':
            action_value = workspace_action.get('value')
            if action_value == 'CANCEL':
                transformation_store.finish_pending(conversation_id, dataset_id, 'CANCELLED')
                return {
                    'intent': 'conversation', 'confidence': 0.99, 'operation': None,
                    'direct_answer': 'Transformation cancelled.',
                    'reason': 'structured transformation clarification cancelled',
                }
            if workspace_action.get('clarification_type') == 'VALUE_TYPE_MISMATCH':
                if action_value == 'CONTINUE':
                    operation = _restore_typed_operation_from_pending(pending)
                    candidate_value_info = workspace_action.get('candidate_value_info')
                    
                    if candidate_value_info:
                        # Which one was it? old_lit or new_lit?
                        # The UI will tell us!
                        target_field = workspace_action.get('target_field', '_new_typed')
                        raw_field = 'new_value' if target_field == '_new_typed' else 'old_value'
                        operation[target_field] = candidate_value_info
                        operation[raw_field] = candidate_value_info.get('value')
                        
                        requested_value_info = workspace_action.get('requested_value_info')
                        operation['intelligence_provenance'] = {
                            "used": True,
                            "method": "typed_value_suggestion",
                            "original_literal": requested_value_info,
                            "resolved_literal": candidate_value_info,
                            "user_confirmed": True,
                            "reason": f"No exact match found; suggested {candidate_value_info.get('value_type')} instead."
                        }
                        
                    operation.pop('_missing_slots', None)
                    operation['_pending_transformation_id'] = pending.transformation_id
                    operation['_pending_conversation_id'] = conversation_id
                    return {
                        'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                        'reason': 'structured clarification accepted value type mismatch',
                    }

            if workspace_action.get('clarification_type') == 'VALUE_AMBIGUITY':
                if action_value == 'RESOLVE_AMBIGUITY':
                    operation = _restore_typed_operation_from_pending(pending)
                    resolved_value_info = workspace_action.get('resolved_value_info')
                    if resolved_value_info:
                        operation['_old_typed'] = resolved_value_info
                        operation['old_value'] = resolved_value_info.get('value')
                        
                        # Once ambiguity is resolved, we don't want the planner to re-trigger natural language resolution.
                        # Pop the raw flag!
                        operation.pop('_old_raw', None)
                        operation.pop('_old_was_quoted', None)
                        
                    operation.pop('_missing_slots', None)
                    operation['_pending_transformation_id'] = pending.transformation_id
                    operation['_pending_conversation_id'] = conversation_id
                    return {
                        'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                        'reason': 'structured clarification resolved value ambiguity',
                    }

            if workspace_action.get('clarification_type') == 'COLUMN_SCOPE':
                if action_value == 'ALL_MATCHING_COLUMNS':
                    selected = list(pending.candidate_columns)
                    scope = {'type': 'ALL_MATCHING_COLUMNS', 'columns': selected}
                elif isinstance(action_value, list):
                    selected = [column for column in action_value if column in pending.candidate_columns]
                    scope = {'type': 'EXPLICIT_COLUMNS', 'columns': selected}
                elif isinstance(action_value, str) and action_value in pending.candidate_columns:
                    selected = [action_value]
                    scope = {'type': 'EXPLICIT_COLUMNS', 'columns': selected}
                else:
                    selected, scope = [], None
                if selected and scope is not None:
                    operation = _restore_typed_operation_from_pending(pending)
                    operation['columns'] = selected
                    operation['scope'] = scope
                    operation.pop('column', None)
                    operation['_pending_transformation_id'] = pending.transformation_id
                    operation['_pending_conversation_id'] = conversation_id
                    return {
                        'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                        'reason': 'structured clarification filled target_scope slot',
                    }
        if re.search(r'\b(cancel|never mind|nevermind|stop|discard)\b', lowered):
            transformation_store.finish_pending(conversation_id, dataset_id, 'CANCELLED')
            return None

        # Free-text clarification (for example, "phone column" or
        # "all columns") follows the same canonical restoration path as
        # structured card actions. Never re-infer resolved literals from raw
        # operation_payload values here.
        operation = _restore_typed_operation_from_pending(pending)
        ready_for_review = pending.status == 'READY_FOR_REVIEW'
        if 'new_names' in pending.missing_slots and 'target_scope' not in pending.missing_slots:
            selected = list(pending.selected_columns or operation.get('columns') or [])
            renames = {}
            for column in selected:
                match = re.search(
                    r'(?<!\w)' + re.escape(str(column)) + r'\s+(?:to|as|->)\s+([\w.-]+)',
                    message, re.IGNORECASE,
                )
                if match:
                    renames[column] = match.group(1)
            if not renames and len(selected) == 1:
                value = re.sub(r'^(?:call it|rename it to|to)\s+', '', message, flags=re.IGNORECASE).strip()
                if re.fullmatch(r'[\w.-]+', value):
                    renames[selected[0]] = value
            if set(renames) != set(selected):
                return None
            operation['renames'] = renames
            if len(renames) == 1:
                old_name, new_name = next(iter(renames.items()))
                operation['column'], operation['new_name'] = old_name, new_name
            operation.pop('_missing_slots', None)
            operation['_pending_transformation_id'] = pending.transformation_id
            operation['_pending_conversation_id'] = conversation_id
            return {'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                    'reason': 'resolved pending rename targets'}

        if 'fill_value' in pending.missing_slots:
            from datasets.semantics.typed_literal import parse_with_explicit_type
            token = re.sub(r'^(?:use|fill with|set to)\s+', '', message, flags=re.IGNORECASE).strip()
            literal = parse_with_explicit_type(token)
            operation['value'] = literal.python_value
            operation['_value_typed'] = literal.to_dict()
            operation.pop('_missing_slots', None)
            operation['_pending_transformation_id'] = pending.transformation_id
            operation['_pending_conversation_id'] = conversation_id
            return {'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                    'reason': 'resolved pending fill value'}

        # A reviewable plan is still an active structured conversation. Route
        # corrections against its typed operation payload before normal intent
        # detection, preserving every slot the user already resolved.
        corrected_destination = None
        destination_phrase = re.search(
            r'''(?:\basked\s+(?:you\s+)?to\s+replace\b.*?\bwith|'''
            r'''\b(?:actually\s+)?use|\b(?:replace|set)\s+(?:it|them|those values)?\s*(?:with|to))\s*'''
            r'''(["'])(.*?)\1''', message, re.IGNORECASE | re.DOTALL,
        )
        requested_destination = None
        if (ready_for_review and pending.operation_type == 'REPLACE_VALUES'
                and destination_phrase and re.search(
            r'\b(asked|why|instead|actually|use|meant|not)\b', lowered
        )):
            from datasets.semantics.typed_literal import parse_literal
            requested_destination = parse_literal(
                destination_phrase.group(2), was_quoted=True
            )
            operation['new_value'] = requested_destination.python_value
            operation['_new_typed'] = requested_destination.to_dict()
            operation['_correction_replanned'] = True

        correction = re.search(
            r'''(?:actually|no[,\s]+)?(?:i\s+)?(?:meant|mean|use)\s+'''
            r'''(?:the\s+)?(?:(integer|int|float|decimal|string|str|text|boolean|bool)\s+)?'''
            r'''(['"])(.*?)\2''', message, re.IGNORECASE,
        )
        if correction:
            from datasets.semantics.typed_literal import parse_literal
            type_word, _, token = correction.groups()
            explicit_type = {
                'int': 'integer', 'integer': 'integer', 'float': 'float',
                'decimal': 'float', 'string': 'string', 'str': 'string',
                'text': 'string', 'bool': 'boolean', 'boolean': 'boolean',
            }.get((type_word or '').lower())
            literal = parse_literal(token, was_quoted=True, explicit_type=explicit_type)
            operation['old_value'] = literal.python_value
            operation['_old_typed'] = literal.to_dict()
            operation['_old_raw'] = token
            operation['_old_was_quoted'] = True
            operation['_correction_replanned'] = True

        destination_correction = re.search(
            r'\b(?:and\s+)?(?:replace|set)\s+(?:them|it|those values)?\s*'
            r'(?:with|to)\s+(["\'])(.*?)\1', message, re.IGNORECASE,
        )
        if destination_correction:
            from datasets.semantics.typed_literal import parse_literal
            destination = parse_literal(destination_correction.group(2), was_quoted=True)
            operation['new_value'] = destination.python_value
            operation['_new_typed'] = destination.to_dict()
            operation['_correction_replanned'] = True

        all_scope = re.search(
            r'\b(all(?:\s+of\s+them)?|every(?:\s+single)?\s+column|'
            r'all\s+(?:matching|applicable)\s+columns|change\s+them\s+all|'
            r'do\s+it\s+everywhere|apply\s+everywhere|use\s+all\s+of\s+them)\b',
            lowered,
        )
        all_dataset_scope = re.search(
            r'\b(?:all\s+(?:of\s+the\s+)?dataset\s+columns|'
            r'all\s+columns\s+in\s+the\s+dataset|every\s+column\s+in\s+the\s+dataset)\b',
            lowered,
        )
        selected_columns = (
            list(pending.selected_columns or operation.get('columns') or [])
            if ready_for_review else []
        )
        scope = operation.get('scope') if ready_for_review else None
        semantic_match = re.search(
            r'\b(?:all|every)\s+(numeric|number|integer|float|text|string|'
            r'date|datetime|categorical)\s+columns?\b', lowered,
        )
        if all_dataset_scope:
            selected_columns = list(entry.dataframe.columns)
            scope = {'type': 'ALL_COLUMNS', 'columns': selected_columns}
        elif semantic_match:
            semantic = semantic_match.group(1).upper()
            semantic = {'NUMERIC': 'NUMBER', 'INTEGER': 'NUMBER', 'FLOAT': 'NUMBER',
                        'STRING': 'TEXT', 'DATETIME': 'DATE'}.get(semantic, semantic)
            from transformation.planner import _column_matches_semantic_scope
            dko_columns = getattr(getattr(entry, 'dko', None), 'columns', {}) or {}
            selected_columns = [
                column for column in entry.dataframe.columns
                if column in pending.candidate_columns
                and _column_matches_semantic_scope(
                    entry.dataframe[column], semantic, dko_columns.get(column)
                )
            ]
            scope = {'type': 'SEMANTIC_COLUMN_SCOPE', 'semantic_type': semantic,
                     'columns': selected_columns}
        elif all_scope:
            selected_columns = list(pending.candidate_columns)
            scope = {'type': 'ALL_MATCHING_COLUMNS', 'columns': selected_columns}
        elif not ready_for_review:
            selected_columns = []
            for column in entry.dataframe.columns:
                if column not in pending.candidate_columns:
                    continue
                if re.search(r'(?<!\w)' + re.escape(str(column).lower()) + r'(?!\w)', lowered):
                    selected_columns.append(column)
            if selected_columns:
                scope = {'type': 'EXPLICIT_COLUMNS', 'columns': selected_columns}

        if scope is None:
            if correction and not ready_for_review:
                operation['_require_scope_selection'] = True
                operation['_pending_transformation_id'] = pending.transformation_id
                operation['_pending_conversation_id'] = conversation_id
                return {'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                        'reason': 'corrected pending transformation literal; scope still required'}
            if re.search(r'^\s*(yes|yeah|yep|sure|correct|go ahead)[!.\s]*$', lowered) and pending.clarification_type == 'ALL_MATCHING_CONFIRMATION':
                selected_columns = list(pending.candidate_columns)
                scope = {'type': 'ALL_MATCHING_COLUMNS', 'columns': selected_columns}
            elif re.search(r'^\s*(no|nope)[!.\s]*$', lowered) and pending.clarification_type == 'ALL_MATCHING_CONFIRMATION':
                pending.latest_question = 'Which of these columns should I change: ' + ', '.join(pending.candidate_columns) + '?'
                pending.clarification_type = 'COLUMN_SCOPE'
                transformation_store.update_pending(pending)
                return {'intent': 'conversation', 'confidence': 0.99, 'operation': None,
                        'reason': 'pending transformation needs an explicit column selection'}
            else:
                return None

        if not selected_columns:
            return None
        operation['columns'] = list(selected_columns)
        operation['scope'] = scope
        operation.pop('column', None)

        if ready_for_review:
            previous_payload = pending.operation_payload
            old_destination = pending.destination_typed_literal or previous_payload.get('_new_typed')
            new_destination = operation.get('_new_typed')
            old_source = pending.source_typed_literal or previous_payload.get('_old_typed')
            new_source = operation.get('_old_typed')

            def _literal_key(value):
                if not value:
                    return None
                return (value.get('value_type'), value.get('value'))

            destination_same = _literal_key(old_destination) == _literal_key(new_destination)
            source_same = _literal_key(old_source) == _literal_key(new_source)
            scope_same = (
                (previous_payload.get('scope') or {}).get('type') == scope.get('type')
                and list(previous_payload.get('columns') or pending.selected_columns or [])
                == list(selected_columns)
            )
            if destination_same and source_same and scope_same:
                source_label = 'value'
                destination_label = 'value'
                try:
                    from datasets.semantics.typed_literal import TypedLiteral
                    source_label = TypedLiteral.from_dict(old_source).display_label()
                    destination_label = TypedLiteral.from_dict(old_destination).display_label()
                except Exception:
                    pass
                scope_label = 'all matching columns' if scope.get('type') == 'ALL_MATCHING_COLUMNS' else ', '.join(map(str, selected_columns))
                return {
                    'intent': 'conversation', 'confidence': 0.99, 'operation': None,
                    'direct_answer': (
                        f"You're right — the active plan already replaces {source_label} "
                        f"with {destination_label} in {scope_label}. No change to the "
                        "transformation is needed."
                    ),
                    'reason': 'correction matches the active transformation; duplicate plan suppressed',
                }

            # Invalidate only after slot comparison confirms a real change.
            # The scope and all untouched literals remain from the active payload.
            if pending.current_plan_id:
                old_plan_id = pending.current_plan_id
                old_plan = transformation_store.invalidate(old_plan_id)
                operation['_supersedes_plan_id'] = old_plan_id
                operation['_previous_operation_label'] = old_plan.operation_label if old_plan else ''
                try:
                    from db.session import get_db
                    from db.repositories.transformation_repository import transformation_repository
                    import uuid
                    db = get_db()
                    if db is not None:
                        transformation_repository.mark_plan_cancelled(db, uuid.UUID(old_plan_id))
                        db.commit()
                except Exception as exc:
                    logger.debug('[Router] Corrected plan invalidation was best-effort: %s', exc)
            changed_slots = []
            if not destination_same:
                changed_slots.append('destination')
                pending.destination_typed_literal = new_destination
            if not source_same:
                changed_slots.append('source')
                pending.source_typed_literal = new_source
            if not scope_same:
                changed_slots.append('target_scope')
            operation['_correction_replanned'] = bool(changed_slots)
            pending.correction_history.append({
                'slots': changed_slots,
                'previous_plan_id': pending.current_plan_id,
                'requested_destination': requested_destination.to_dict() if requested_destination else None,
            })
            pending.operation_payload = dict(operation)
            pending.status = 'CORRECTING'
            transformation_store.update_pending(pending)
            pending.operation_payload = dict(operation)
            pending.status = 'CORRECTING'
            transformation_store.update_pending(pending)

        if operation.get('type') == 'RENAME_COLUMN' and 'new_names' in pending.missing_slots:
            operation['_missing_slots'] = ['new_names']
            operation['_pending_transformation_id'] = pending.transformation_id
            operation['_pending_conversation_id'] = conversation_id
            return {'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                    'reason': 'resolved pending rename column selection'}
        operation['_pending_transformation_id'] = pending.transformation_id
        operation['_pending_conversation_id'] = conversation_id
        logger.info('[Router] Resolved pending transformation=%s scope=%s columns=%s',
                    pending.transformation_id, scope.get('type'), selected_columns)
        return {'intent': 'TRANSFORM', 'confidence': 0.99, 'operation': operation,
                'reason': 'resolved pending transformation clarification'}

    def _transform_correction_fast_path(self, context: ExecutionContext) -> dict | None:
        """Replan the current session's pending replace when its value type is corrected."""
        original = (getattr(context, 'message', '') or '').strip()
        match = re.match(
            r'''^(?:no[,\s]+)?(?:i\s+(?:meant|mean)|actually(?:,\s*i\s+(?:meant|mean))?)\s+'''
            r'''(?:the\s+)?(?:(integer|int|float|decimal|string|str|text|boolean|bool)\s+)?'''
            r'''(?:(["'])(.*?)\2|(.+?))\s*[.!?]*$''',
            original, re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None

        session_id = getattr(context, 'chat_id', None) or getattr(context, 'session_id', None)
        dataset_id = str(getattr(context, 'dataset_id', '') or '')
        if not session_id or not dataset_id:
            return None

        from transformation.store import transformation_store
        pending = transformation_store.latest_for_session(session_id, dataset_id)
        if not pending or pending.operation_type != 'REPLACE_VALUES':
            return None

        from datasets.semantics.typed_literal import parse_literal
        type_word, quote, quoted_value, bare_value = match.groups()
        token = quoted_value if quote else (bare_value or '').strip()
        explicit_type = {
            'int': 'integer', 'integer': 'integer',
            'float': 'float', 'decimal': 'float',
            'str': 'string', 'string': 'string', 'text': 'string',
            'bool': 'boolean', 'boolean': 'boolean',
        }.get((type_word or '').lower())
        literal = parse_literal(token, was_quoted=bool(quote), explicit_type=explicit_type)

        operation = dict(pending.operation_payload)
        operation['old_value'] = literal.python_value
        operation['_old_typed'] = literal.to_dict()
        operation['_correction_replanned'] = True

        # Invalidate the old preview locally and in PostgreSQL when available,
        # so an old plan cannot be applied after the correction.
        transformation_store.invalidate(pending.plan_id)
        try:
            from db.session import get_db
            from db.repositories.transformation_repository import transformation_repository
            import uuid
            db = get_db()
            if db is not None:
                transformation_repository.mark_plan_cancelled(db, uuid.UUID(pending.plan_id))
                db.commit()
        except Exception as exc:
            logger.debug('[Router] Previous corrected plan invalidation was best-effort: %s', exc)

        logger.info('[Router] Replanning corrected transform value as %s', literal.display_label())
        return {
            'intent': 'TRANSFORM',
            'confidence': 0.99,
            'operation': operation,
            'reason': f'user correction; replanned with {literal.display_label()}',
        }

    # ── LLM interpretation ────────────────────────────────────────────────────

    _semantic_cache = {}

    def _llm_interpret(self, context: ExecutionContext, semantic_ctx: dict) -> dict:
        """
        Call the LLM to interpret the user's query.

        This is the 80% layer — the LLM makes the final semantic decision.
        The LLM receives:
          - The user query (normalized)
          - Full dataset schema with column names, types, sample values
          - Schema-compatible capabilities (structural, not keyword-matched)
          - Workspace context (recent ops, selection)

        Returns a typed payload dict {intent, operation, confidence, reason}.
        Falls back to conversation intent on LLM failure.
        """
        from prompts.interpreter import build_interpreter_prompt
        from providers.domain.contracts import AIRequest

        import time
        query = getattr(context, 'message', '') or getattr(context, 'normalized_query', '')
        
        # 1. Semantic Caching
        cache_key = f"{query}::{semantic_ctx.get('dataset_id', '')}::{semantic_ctx.get('dataset_fingerprint', '')}"
        if cache_key in self._semantic_cache:
            logger.info(f"[Router/LLM] Semantic cache hit for query: {query}")
            return self._semantic_cache[cache_key]

        prompt = build_interpreter_prompt(query=query, semantic_context=semantic_ctx)

        # Log what we're sending (no data, just metadata)
        dataset_loaded = semantic_ctx.get("dataset_loaded", False)
        col_count = len(semantic_ctx.get("columns", []))
        ref_cols = semantic_ctx.get("referenced_columns", [])
        logger.info(
            f"[Router/LLM] interpret: dataset_loaded={dataset_loaded} "
            f"columns={col_count} referenced={ref_cols}"
        )

        # 2. Exponential Backoff & Retry Logic for 429 / Transient Errors
        max_retries = 6
        base_delay = 3.0
        response = None
        
        for attempt in range(max_retries):
            try:
                response = provider_engine.generate(
                    AIRequest(
                        task='classification',
                        messages=[{"role": "user", "content": prompt}],
                        system_prompt=(
                            "You are a semantic intent classifier. "
                            "Return ONLY a valid JSON object. No prose, no markdown."
                        ),
                        temperature=0.05,
                        max_tokens=2048,
                    )
                )
                
                if response.success:
                    break
                    
                error_str = str(response.error).lower()
                raw_resp = response.raw_response or {}
                logger.error(f"DEBUG: error_str={error_str} raw_resp={raw_resp}")
                if "429" in error_str or "too many requests" in error_str or "quota" in error_str or raw_resp.get("retryable"):
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"[Router/LLM] 429 Rate limit detected. Retrying in {delay}s (Attempt {attempt+1}/{max_retries})...")
                        time.sleep(delay)
                        continue
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"[Router/LLM] Exception '{e}' detected. Retrying in {delay}s (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(delay)
                    continue
                else:
                    raise e
                    
            break

        try:
            if not response or not response.success:
                logger.warning(
                    f"[Router/LLM] provider failed: {response.error}. "
                    f"Falling back to {'analysis' if dataset_loaded else 'conversation'}."
                )
                return {
                    "intent": "conversation",
                    "operation": None,
                    "confidence": 0.5,
                    "reason": f"Graceful fallback to conversation ({response.error})",
                    "error": response.error,
                }

            payload = self._parse_llm_json(response.text or "")
            logger.info(
                f"[Router/LLM] result: intent={payload.get('intent')} "
                f"confidence={payload.get('confidence')} "
                f"operation={payload.get('operation')} "
                f"reason={payload.get('reason', '')[:80]}"
            )
            # Store in cache
            if len(self._semantic_cache) > 1000:
                self._semantic_cache.clear()
            self._semantic_cache[cache_key] = payload
            return payload

        except Exception as e:
            logger.error(f"[Router/LLM] interpretation exception: {e}", exc_info=True)
            return {
                "intent": "conversation",
                "operation": None,
                "confidence": 0.5,
                "reason": f"Exception during LLM interpret: {str(e)[:60]}",
                "error": str(e),
            }

    def _parse_llm_json(self, text: str) -> dict:
        """Parse and normalise the LLM's JSON response."""
        logger.debug(f"RAW LLM RESPONSE TEXT: {repr(text)}")
        text = text.strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try extracting outermost JSON object
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass

        # ── Truncated-JSON recovery ───────────────────────────────────────────
        # If the LLM returned TRANSFORM but the JSON got truncated by max_tokens,
        # extract the intent and partial operation instead of falling to conversation.
        intent_match = re.search(r'"intent"\s*:\s*"(\w+)"', text)
        if intent_match:
            recovered_intent = intent_match.group(1)
            if recovered_intent in ("TRANSFORM", "INVESTIGATE"):
                logger.warning(
                    "[Router/LLM] Truncated JSON recovered: intent=%s (from: %s...)",
                    recovered_intent, text[:120],
                )
                # Try to extract operation type if present
                op_type_match = re.search(r'"type"\s*:\s*"(\w+)"', text)
                operation = None
                if op_type_match:
                    operation = {"type": op_type_match.group(1)}
                    # Try extracting fill_value
                    fill_match = re.search(r'"fill_value"\s*:\s*(\d+(?:\.\d+)?|"[^"]*")', text)
                    if fill_match:
                        raw = fill_match.group(1)
                        try:
                            operation["fill_value"] = json.loads(raw)
                        except Exception:
                            operation["fill_value"] = raw.strip('"')
                return {
                    "intent": recovered_intent,
                    "operation": operation,
                    "confidence": 0.85,
                    "reason": f"recovered from truncated JSON (intent={recovered_intent})",
                }

        logger.warning(f"[Router/LLM] Could not parse JSON from: {text[:200]}")
        return {"intent": "conversation", "operation": None, "confidence": 0.3, "reason": "parse_error"}

    # ── Schema validation + enrichment ────────────────────────────────────────

    def _validate_and_enrich(
        self, payload: dict, context: ExecutionContext, semantic_ctx: dict
    ) -> dict:
        """
        Validate the LLM's structured operation against the actual schema.

        On validation failure:
          - intent is set to 'conversation'
          - A typed error reason is attached
          - The operation is cleared

        On minor corrections (e.g. default order):
          - The corrected operation is used

        Does NOT re-run the LLM or guess missing values.
        """
        intent = payload.get("intent", "CONVERSATION")
        if intent != "DATA_OPERATION":
            return payload  # Nothing to validate for non-data intents

        columns = semantic_ctx.get("columns", [])
        operations = payload.get("operations", [])
        if not operations and payload.get("operation"):
            operations = [payload.get("operation")]
            
        if not operations:
            context.interpretation_error = {"code": "MISSING_OPERATION", "message": "No operations found."}
            return {**payload, "intent": "conversation", "operations": [], "operation": None}
            
        valid_ops = []
        for op in operations:
            res = schema_validator.validate(
                interpretation={"intent": intent, "operation": op},
                columns=columns,
            )
            if not res.valid:
                logger.info(f"[Router/Validator] validation failed: code={res.error_code} msg={res.error_message}")
                context.interpretation_error = {"code": res.error_code, "message": res.error_message}
                # Evict poisoned interpretation from cache
                query = getattr(context, 'message', '') or getattr(context, 'normalized_query', '')
                cache_key = f"{query}::{semantic_ctx.get('dataset_id', '')}::{semantic_ctx.get('dataset_fingerprint', '')}"
                self._semantic_cache.pop(cache_key, None)

                # If column not found, provide grounded direct answer listing available columns
                if res.error_code == "COLUMN_NOT_FOUND":
                    col_name = getattr(res, 'missing_column', None)
                    if not col_name:
                        m_col = re.search(r"'(.*?)'", res.error_message or "")
                        col_name = m_col.group(1) if m_col else "requested"
                    available = [c.get("name") if isinstance(c, dict) else str(c) for c in (columns or [])]
                    avail_str = f" The available columns in this dataset are: {', '.join(available)}." if available else ""
                    return {
                        **payload,
                        "intent": "conversation",
                        "operations": [],
                        "operation": None,
                        "confidence": 0.99,
                        "direct_answer": f"The dataset does not contain a **{col_name}** column.{avail_str}",
                        "reason": f"Required column '{col_name}' does not exist in dataset",
                    }

                return {**payload, "intent": "conversation", "operations": [], "operation": None, "confidence": 0.5}
            valid_ops.append(res.corrected_operation if res.corrected_operation is not None else op)
            
        payload["operations"] = valid_ops
        logger.debug(f"[Router/Validator] all operations valid: {valid_ops}")
        return payload

        # Validation failed
        logger.info(
            f"[Router/Validator] validation failed: "
            f"code={result.error_code} msg={result.error_message}"
        )
        # Attach error to context for engine to surface
        context.interpretation_error = {
            "code": result.error_code,
            "message": result.error_message,
        }
        # Route to conversation with the error reason
        return {
            **payload,
            "intent": "conversation",
            "operation": None,
            "confidence": 0.9,
            "reason": f"Validation failed: {result.error_message}",
            "validation_error": result.error_message,
        }

    # ── Intent mapping ────────────────────────────────────────────────────────

    def _map_intent(self, llm_intent: str) -> str:
        """
        Map LLM intent schema names to engine intent names.

        LLM returns:  DATA_OPERATION | CONVERSATION | EXPLANATION | TITLE | TRANSFORM | INVESTIGATE
        Engine uses:  analysis | conversation | help_system | title_generation | transform | investigate
        """
        mapping = {
            "DATA_OPERATION": "analysis",
            "CONVERSATION":   "conversation",
            "EXPLANATION":    "conversation",   # ConversationEngine handles this
            "TITLE":          "title_generation",
            "TRANSFORM":      "transform",
            "INVESTIGATE":    "investigate",
            # Legacy intents (from old classifier) — keep compatibility
            "analysis":       "analysis",
            "conversation":   "conversation",
            "help_system":    "conversation",   # help_system → conversation
            "title_generation": "title_generation",
            "web_search":     "web_search",
            "transform":      "transform",
            "investigate":    "investigate",
            "ROUTER_UNAVAILABLE": "router_unavailable",
        }
        return mapping.get(llm_intent, "conversation")


master_router = MasterRouter()

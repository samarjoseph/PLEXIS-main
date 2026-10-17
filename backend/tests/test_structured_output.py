"""
Structured Output and JSON Reliability Tests (Part 10.D).

Verifies:
- Valid JSON parsing and field normalization.
- Extraction of JSON enclosed in Markdown code blocks and explanatory prose.
- Schema validation against supported intents and operations.
- Prevention of arbitrary SQL/Python injection or unsupported operations.
- Proper handling of string literals ('none', 'null') versus genuine None/null.
- Truncated JSON recovery in Router.
"""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from router.master_router import MasterRouter
from router.schema_validator import SchemaValidator, ValidationResult


class TestStructuredOutput:
    """Verifies that unstructured or malformed LLM outputs are deterministically normalized or rejected."""

    def setup_method(self):
        self.router = MasterRouter()
        self.validator = SchemaValidator()

    def test_clean_json_parsing(self):
        """Clean JSON should parse directly into dict."""
        raw = '{"intent": "DATA_OPERATION", "operation": {"type": "GET_ROW_COUNT"}, "confidence": 0.99}'
        parsed = self.router._parse_llm_json(raw)
        assert parsed["intent"] == "DATA_OPERATION"
        assert parsed["operation"]["type"] == "GET_ROW_COUNT"

    def test_markdown_code_fences_stripped(self):
        """JSON surrounded by markdown ```json code fences must be extracted cleanly."""
        raw = """```json
{
  "intent": "DATA_OPERATION",
  "operation": {
    "type": "MIN",
    "column": "age"
  },
  "confidence": 0.95,
  "reason": "Calculates minimum age"
}
```"""
        parsed = self.router._parse_llm_json(raw)
        assert parsed["intent"] == "DATA_OPERATION"
        assert parsed["operation"]["type"] == "MIN"
        assert parsed["operation"]["column"] == "age"

    def test_surrounding_prose_stripped(self):
        """JSON embedded inside conversational prose is cleanly isolated."""
        raw = """Here is the structured operation you requested:
{"intent": "DATA_OPERATION", "operation": {"type": "UNIQUE_COUNT", "column": "city"}, "confidence": 0.9}
Hope this helps!"""
        parsed = self.router._parse_llm_json(raw)
        assert parsed["intent"] == "DATA_OPERATION"
        assert parsed["operation"]["column"] == "city"

    def test_truncated_json_recovery(self):
        """Router recovers intent and partial operation if JSON was truncated by max_tokens."""
        raw = '{"intent": "TRANSFORM", "operation": {"type": "DROP_DUPLICATES", "col'
        parsed = self.router._parse_llm_json(raw)
        assert parsed["intent"] == "TRANSFORM"
        assert parsed["operation"]["type"] == "DROP_DUPLICATES"

    def test_invalid_json_fallback(self):
        """Completely unparseable text returns fallback dict with raw text."""
        raw = "Sorry, I am an AI and cannot process this request."
        parsed = self.router._parse_llm_json(raw)
        assert parsed.get("intent") in ("conversation", "CONVERSATION") or "error" in parsed

    def test_schema_validator_rejects_unsupported_operation(self):
        """Operations not in the supported allowlist must fail schema validation."""
        columns = [{"name": "age", "type": "numeric"}]
        interpretation = {
            "intent": "DATA_OPERATION",
            "operation": {"type": "EXECUTE_ARBITRARY_SQL", "query": "DROP TABLE users"},
        }
        res = self.validator.validate(interpretation, columns)
        assert res.valid is False
        assert res.error_code == "UNSUPPORTED_OPERATION"

    def test_schema_validator_rejects_hallucinated_column(self):
        """Referencing non-existent columns must fail schema validation."""
        columns = [{"name": "age", "type": "numeric"}, {"name": "city", "type": "string"}]
        interpretation = {
            "intent": "DATA_OPERATION",
            "operation": {"type": "MEAN", "column": "non_existent_column_123"},
        }
        res = self.validator.validate(interpretation, columns)
        assert res.valid is False
        assert "not found" in res.error_message.lower() or res.error_code == "COLUMN_NOT_FOUND"

    def test_schema_validator_operation_aliases(self):
        """Common LLM singular/plural aliases must be normalized to canonical operations."""
        columns = [{"name": "city", "type": "string"}]
        interpretation = {
            "intent": "DATA_OPERATION",
            "operation": {"type": "MOST_UNIQUE_VALUES", "column": "city"},
        }
        res = self.validator.validate(interpretation, columns)
        # Should be mapped to canonical COLUMN_WITH_MOST_UNIQUE_VALUES
        assert res.valid is True or (res.corrected_operation and res.corrected_operation.get("type") == "COLUMN_WITH_MOST_UNIQUE_VALUES")

    def test_typed_literals_none_vs_null(self):
        """Distinguish string literals like 'none'/'null' from actual None."""
        raw_none_str = '{"intent": "TRANSFORM", "operation": {"type": "FILL_NA", "fill_value": "none"}}'
        parsed_str = self.router._parse_llm_json(raw_none_str)
        assert parsed_str["operation"]["fill_value"] == "none"

        raw_null = '{"intent": "TRANSFORM", "operation": {"type": "FILL_NA", "fill_value": null}}'
        parsed_null = self.router._parse_llm_json(raw_null)
        assert parsed_null["operation"]["fill_value"] is None

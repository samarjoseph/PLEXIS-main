"""
Unit test for text sanitizer.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.text_sanitizer import strip_thinking_and_internal_reasoning


def test_strip_thinking_tags():
    raw = "<think>The user wants to cap delay to 60.\nLet's plan it.</think>I can help you cap the delay."
    assert strip_thinking_and_internal_reasoning(raw) == "I can help you cap the delay."


def test_strip_natural_chain_of_thought():
    raw = """Here's a thinking process:
1.  **Analyze User Input:**
    *   User says: "i meant change only the maximum records 119 to 60"
    *   Context: The system note says "CURRENT INTENT: conversation", "DATASET LOADED: india_flight_delay_model_input.csv", and the last assistant message offered options:
        1. Cap values at 60 (values > 60 become 60)
        2. Change only the maximum record(s) (119) to 60
    *   The user is clearly selecting option 2 from the previous clarification.
2.  **Determine Action:**
    *   We should explain that option 2 will change only the maximum records from 119 to 60.

To change only the maximum record(s) (119) to 60 in Departure_Delay, select Option 2 in the transformation plan."""

    res = strip_thinking_and_internal_reasoning(raw)
    assert "thinking process" not in res.lower()
    assert "system note" not in res.lower()
    assert "Analyze User Input" not in res
    assert "To change only the maximum record(s)" in res


def test_strip_prompt_leakage_lines():
    raw = """CURRENT INTENT: conversation
DATASET LOADED: india_flight_delay_model_input.csv
SYSTEM NOTE: You are Plexis.

Here is the answer to your question about the delay statistics."""

    res = strip_thinking_and_internal_reasoning(raw)
    assert "CURRENT INTENT" not in res
    assert "DATASET LOADED" not in res
    assert "SYSTEM NOTE" not in res
    assert res == "Here is the answer to your question about the delay statistics."

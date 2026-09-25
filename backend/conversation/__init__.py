"""
Conversation Package — Plexis Conversation Engine

This package owns all conversational intelligence logic.
It is responsible ONLY for how Plexis communicates.

Modules:
    identity        — WHO Plexis is (character, values, anti-patterns)
    reasoning       — HOW Plexis thinks before responding
    analyst_voice   — HOW Plexis communicates analytical results
    context_builder — Assembles the LLM context from execution state
    prompt_builder  — Composes the final system prompt from modular components
"""

from .prompt_builder import build_system_prompt
from .context_builder import build_context_block
from .response_planner import response_planner, ConversationPlan

__all__ = [
    'build_system_prompt',
    'build_context_block',
    'response_planner',
    'ConversationPlan',
]

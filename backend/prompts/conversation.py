"""
Conversation Prompt Module (Legacy Bridge)

This module previously housed the monolithic conversation prompt builder.
The logic has been refactored into the dedicated `conversation/` package:

    conversation/identity.py        — WHO Plexis is
    conversation/reasoning.py       — HOW Plexis thinks
    conversation/analyst_voice.py   — HOW Plexis presents analytical results
    conversation/context_builder.py — What context to pass to the LLM
    conversation/prompt_builder.py  — Assembles the full system prompt

This file is kept for backwards compatibility in case any code imports
build_conversation_prompt from this location. It delegates to the new package.

Note: All imports from the `conversation` package are lazy (inside function body)
to prevent a circular import via prompts/__init__.py.
"""

from typing import Dict, Any, List, Optional


def build_conversation_prompt(
    intent: str,
    message: str,
    conversation_history: List[Dict[str, Any]],
    route_payload: Optional[Dict[str, Any]] = None,
    dataset_context: Optional[Dict[str, Any]] = None,
    facts_payload: Optional[Dict[str, Any]] = None,
) -> tuple:
    """
    Bridge to the new modular conversation architecture.
    Delegates to conversation.prompt_builder and conversation.context_builder.
    """
    # Lazy imports to avoid circular dependency
    from conversation.prompt_builder import build_system_prompt
    from conversation.context_builder import build_context_block

    dataset_filename = dataset_context.get('filename') if dataset_context else None
    has_analytical_facts = bool(facts_payload and set(facts_payload.keys()) - {'type', 'error'})

    system_prompt = build_system_prompt(
        intent=intent,
        has_dataset=bool(dataset_filename),
        has_analytical_facts=has_analytical_facts,
    )

    context_block = build_context_block(
        message=message,
        intent=intent,
        conversation_history=conversation_history,
        dataset_filename=dataset_filename,
        facts=facts_payload,
    )

    return system_prompt, context_block

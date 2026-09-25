"""
Plexis Conversation Engine — System Prompt Builder

This is the master assembler for the Conversation Engine's system prompt.
It pulls from the modular sub-modules (identity, reasoning, analyst_voice)
and composes the final system prompt used for LLM generation.

Responsibilities:
- Assemble the system prompt from modular components.
- Adapt the prompt based on context (is a dataset loaded? is this analytical?).
- Keep the prompt clean, focused, and non-redundant.

This module does NOT handle routing, planning, or execution.
"""

from conversation.identity import PLEXIS_IDENTITY, WARMTH_PRINCIPLES
from conversation.reasoning import REASONING_FRAMEWORK, RESPONSE_BEHAVIOUR
from conversation.analyst_voice import DATA_ANALYST_VOICE
from conversation.response_planner import ConversationPlan
from prompts.formatter import get_formatting_rules


def build_system_prompt(
    intent: str,
    has_dataset: bool = False,
    has_analytical_facts: bool = False,
    plan: ConversationPlan = None,
) -> str:
    """
    Assemble the Conversation Engine system prompt.

    Arguments:
        intent: The classified intent of the current request.
        has_dataset: Whether a dataset is currently loaded.
        has_analytical_facts: Whether this response involves real analytical results.
        plan: Optional ConversationPlan with length/tone guidance.

    Returns:
        A complete, focused system prompt for the conversation LLM call.
    """

    # Core identity is always present
    sections = [
        PLEXIS_IDENTITY,
        WARMTH_PRINCIPLES,
        REASONING_FRAMEWORK,
        RESPONSE_BEHAVIOUR,
    ]

    # Inject analytical voice only when it's relevant
    if has_dataset or has_analytical_facts or intent == 'analysis':
        sections.append(DATA_ANALYST_VOICE)

    # Formatting guidance always included
    sections.append(get_formatting_rules())

    # Inject the Conversation Plan if provided
    if plan:
        sections.append(plan.to_guidance())

    # Closing instruction
    sections.append(
        "Now respond. The context below tells you what the user said and what has happened "
        "in this conversation. Use your reasoning, your identity, and your judgment. "
        "Do not perform routing. Do not explain your reasoning process. Just respond as Plexis."
    )

    return "\n\n".join(sections)

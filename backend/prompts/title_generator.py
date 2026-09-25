"""
Title Generator Prompt Module

Responsible ONLY for generating conversation titles.
Nothing else.
"""

def build_title_prompt(conversation_history: str) -> str:
    """Builds the prompt for conversation title generation."""
    return f"""Generate a short, concise title (max 5 words) for the following conversation.
Return ONLY the title as plain text. Do not include quotes, explanations, or conversational text.

Conversation:
{conversation_history}"""

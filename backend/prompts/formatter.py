"""
Formatter Prompt Module

Responsible for taking raw output and presenting it beautifully.
This prompt logic is injected into other prompts so they know HOW to present what they want to say.
"""

def get_formatting_rules() -> str:
    """Return the global formatting rules for Plexis."""
    return """
FORMATTING RULES:
- Present information beautifully using standard Markdown.
- Use bullet points, spacing, and clear visual hierarchies to ensure readability.
- When formatting code, use proper markdown code blocks with language tags.
- For data, use markdown tables when comparing multiple dimensions.
"""

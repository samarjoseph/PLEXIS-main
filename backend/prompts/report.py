"""
Report Prompt Module

Dedicated to Executive Reports, PDF, Markdown, and HTML generation.
Professional tone. No casual conversation.
"""

from prompts.formatter import get_formatting_rules

def build_report_prompt(topic: str, data: str) -> str:
    """Builds the prompt for report generation."""
    system_prompt = f"""You are an Expert Report Generator.
Your ONLY job is to produce professional, executive-level reports based on the provided data.
Use a strictly professional tone. Do NOT engage in casual conversation.

{get_formatting_rules()}"""

    full_prompt = f"""Topic: {topic}
Data:
{data}

Generate a comprehensive, beautifully formatted report."""
    
    return system_prompt, full_prompt

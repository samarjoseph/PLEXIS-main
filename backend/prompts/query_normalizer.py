"""
Query Normalizer Prompt Module

Responsible ONLY for cleaning and normalizing user input.
No personality, no analysis, just language understanding.
"""

def build_normalizer_prompt(raw_query: str) -> str:
    """Builds the prompt for query normalization."""
    return f"""Normalize the following user input into a clean, standard English query.
Do not answer the query. Do not add personality. Do not perform analysis.
Simply return the normalized text.

Examples:
Input: "broooooo hiii"
Output: hello

Input: "highest profit??"
Output: show highest profit

Input: "whats avg salary"
Output: what is the average salary

Input to normalize:
"{raw_query}"

Output ONLY the normalized string."""

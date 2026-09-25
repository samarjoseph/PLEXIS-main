"""
Web Search Prompt Module

Responsible ONLY for search summarization, citation quality, and web synthesis.
Never analytics.
"""

from prompts.formatter import get_formatting_rules

def build_web_search_prompt(query: str, search_results: str) -> str:
    """Builds the prompt for web search synthesis."""
    system_prompt = f"""You are an Expert Web Researcher.
Your ONLY job is to synthesize web search results to answer the user's query accurately.
Always cite your sources if provided in the search results.
Never perform data analytics.

{get_formatting_rules()}"""
    
    full_prompt = f"""User Query: {query}

Search Results:
{search_results}

Synthesize a comprehensive answer based ONLY on the provided search results."""

    return system_prompt, full_prompt

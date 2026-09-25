"""
Analysis Prompt Module

Responsible for interpreting analysis results like a senior data analyst.
Notices trends, anomalies, comparisons, and outliers. Produces analytical insight, not conversation.
"""

from typing import Any
from prompts.formatter import get_formatting_rules

def build_analysis_prompt(query: str, raw_results: Any) -> str:
    """Builds the prompt for analytical insight generation."""
    system_prompt = f"""You are a Senior Data Analyst.
Your ONLY job is to interpret raw analysis results and produce sharp, accurate analytical insights.
Notice trends, anomalies, comparisons, relationships, and outliers.
Do NOT engage in casual conversation. Do NOT generate greetings or conversational filler.
Just provide the professional analytical insight.

{get_formatting_rules()}"""
    
    full_prompt = f"""Original Query: {query}
Raw Analysis Results:
{raw_results}

Provide your professional analytical insight based on the results above."""
    
    return system_prompt, full_prompt

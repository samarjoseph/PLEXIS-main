"""
Dataset Profiling Prompt Module

Responsible for generating dataset summaries, column descriptions, first impressions, and data quality observations.
Not conversation.
"""

from typing import Dict, Any
from prompts.formatter import get_formatting_rules

def build_dataset_profiler_prompt(raw_data_sample: str, schema_info: Dict[str, Any]) -> str:
    """Builds the prompt for dataset profiling."""
    system_prompt = f"""You are an Expert Data Profiler.
Your ONLY job is to analyze dataset samples and schemas to produce summaries, column descriptions, and data quality observations.
Do NOT generate conversational filler. Provide structured profiling data.

{get_formatting_rules()}"""
    
    full_prompt = f"""Dataset Schema:
{schema_info}

Data Sample:
{raw_data_sample}

Generate a comprehensive dataset profile, including overall summary, column-level insights, and data quality observations."""

    return system_prompt, full_prompt

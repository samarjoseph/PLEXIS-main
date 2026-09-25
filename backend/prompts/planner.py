"""
Planner Prompt Module

Responsible for converting natural language into structured execution plans.
Never worries about user friendliness or explanations.
"""

import json
from typing import Dict, Any, Optional

def build_planner_prompt(goal: str, dataset_schema: Optional[Dict[str, Any]] = None) -> str:
    """Builds the prompt for execution planning."""
    schema_str = json.dumps(dataset_schema, indent=2) if dataset_schema else "No dataset loaded."
    
    return f"""You are an expert AI Execution Planner.
Your ONLY job is to convert natural language goals into structured execution plans.
Do NOT generate conversational explanations. Do NOT worry about user friendliness.

Goal: {goal}
Available Dataset Schema: {schema_str}

Produce a structured JSON execution plan containing:
1. "steps": Array of logical steps to achieve the goal.
2. "required_tools": Array of tool names needed.
3. "estimated_complexity": "low", "medium", or "high".
"""

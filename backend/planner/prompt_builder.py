"""
Planner prompt builder — builds the LLM prompt for the AnalyticalPlanner.

Critical rules:
  - ALWAYS inject the real column names into the prompt
  - ALWAYS inject column types into the prompt
  - NEVER allow the LLM to invent columns
  - If repair_error is provided, include it so the LLM can self-correct
"""
from __future__ import annotations

import json
from typing import Optional


def build_planner_prompt(
    query: str,
    context: dict,
    repair_error: Optional[str] = None,
) -> str:
    """
    Build the prompt sent to the LLM planner.

    Args:
        query:        Raw user query.
        context:      PlannerContext dict with:
                      columns, column_types, dataset_name, profile,
                      chat_history, previous_ops, dataset_fingerprint
        repair_error: If set, include this error so the LLM can fix its output.
    """
    columns: list = context.get("columns") or []
    column_types: dict = context.get("column_types") or {}
    dataset_name: str = context.get("dataset_name") or "the dataset"
    profile: dict = context.get("profile") or {}
    chat_history: list = context.get("chat_history") or []
    previous_ops: list = context.get("previous_ops") or []

    # ── Column block ──────────────────────────────────────────────────────────
    col_lines = []
    for col in columns:
        dtype = column_types.get(col, "unknown")
        col_lines.append(f"  - {col} ({dtype})")
    col_block = "\n".join(col_lines) if col_lines else "  (no columns)"

    # ── Profile block ─────────────────────────────────────────────────────────
    profile_str = ""
    if profile:
        try:
            profile_str = json.dumps(profile, indent=2, default=str)[:800]
        except Exception:
            profile_str = str(profile)[:400]

    # ── Chat history block ────────────────────────────────────────────────────
    history_str = ""
    if chat_history:
        recent = chat_history[-4:]
        lines = []
        for m in recent:
            role = m.get("role", "?")[:10]
            content = str(m.get("content") or "")[:100]
            lines.append(f"  [{role}]: {content}")
        history_str = "\n".join(lines)

    # ── Previous ops block ────────────────────────────────────────────────────
    prev_str = ""
    if previous_ops:
        try:
            prev_str = json.dumps(previous_ops[-2:], indent=2, default=str)[:600]
        except Exception:
            prev_str = ""

    # ── Repair block ─────────────────────────────────────────────────────────
    repair_block = ""
    if repair_error:
        repair_block = f"""
---
PREVIOUS ATTEMPT FAILED WITH THIS ERROR:
{repair_error}

Fix the error in your next response. Return ONLY the corrected JSON.
---"""

    # ── Supported operations list ─────────────────────────────────────────────
    ops_list = (
        "count, nunique, mean, median, mode, min, max, sum, std, variance, range, "
        "top_n, bottom_n, filter, sort, group_by, group_mean, group_sum, group_count, "
        "group_min, group_max, missing_values, duplicates, unique_values, outliers, "
        "histogram, frequency, quantile, correlation, covariance, "
        "locate_row, locate_rows, compare_groups, compare_columns"
    )

    return f"""You are the Plexis Analytical Planner.
Your job: convert a user query into a structured analytical plan.
You DO NOT execute anything. You DO NOT compute numbers. You DO NOT invent column names.
{repair_block}

USER QUERY:
{query}

DATASET: {dataset_name}
Columns (use EXACT names):
{col_block}

{f'Profile:{chr(10)}{profile_str}' if profile_str else ''}
{f'Recent conversation:{chr(10)}{history_str}' if history_str else ''}
{f'Previous operations:{chr(10)}{prev_str}' if prev_str else ''}

RETURN EXACTLY THIS JSON OBJECT (no markdown, no prose):
{{
  "intent": "<descriptive label e.g. highest_age>",
  "operation": "<one of: {ops_list}>",
  "target_column": "<EXACT column name from dataset, or null>",
  "columns": [],
  "parameters": {{}},
  "plan": [
    {{"op": "select_column", "column": "<col>"}},
    {{"op": "drop_nulls"}},
    {{"op": "aggregate", "function": "<max|min|mean|std|sum|count|var>"}},
    {{"op": "locate_rows", "column": "<col>", "value_from": "aggregate_result"}}
  ]
}}

RULES:
1. target_column MUST be an EXACT column name from the list above, or null.
2. operation MUST be from the supported list.
3. Do NOT invent column names.
4. Do NOT include eval(), exec(), import, os.system, subprocess, or any code strings.
5. plan steps MUST only use: select_column, drop_nulls, to_numeric, aggregate, locate_rows, sort, filter, group_by, compare, locate_row, top_n, bottom_n, nunique, mode, frequency, quantile, histogram, correlation, covariance, outliers.
6. Return ONLY the JSON object.
"""

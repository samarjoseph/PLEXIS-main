"""
Interpreter Prompt — the 80% LLM semantic decision layer.

This prompt is the PRIMARY semantic authority for intent classification.
It receives the full structured context from SemanticContextBuilder and
must return a typed JSON interpretation.

ARCHITECTURE CONTRACT:
  - The LLM makes the FINAL semantic decision.
  - Keywords and schema signals are supporting evidence, not the decision.
  - The output must be valid JSON with the specified schema.
  - The output is schema-validated before use.

LLM OUTPUT SCHEMA:
  {
    "intent": "DATA_OPERATION" | "CONVERSATION" | "EXPLANATION" | "TITLE",
    "operation": {
      "type":   string (e.g. "MIN", "MAX", "TOP_N", "FILTER", "FIND_DUPLICATES"),
      "column": string (column name, required for single-column operations),
      "columns": [string] (for multi-column ops like FIND_DUPLICATES),
      "n":      integer (for TOP_N/BOTTOM_N),
      "order":  "asc" | "desc" (for TOP_N/BOTTOM_N),
      "func":   string (for AGGREGATE: "mean"/"median"/"std"/"sum"/"count"),
      "operator": string (for FILTER: ">","<",">=","<=","==","!="),
      "value":  any (for FILTER)
    } | null,
    "confidence": float (0.0–1.0),
    "reason":   string (short explanation of interpretation)
  }

INTENT VALUES:
  DATA_OPERATION — user wants a deterministic calculation on the dataset
  CONVERSATION   — general knowledge, casual chat, conceptual question
  EXPLANATION    — explain a previous result (workspace_action present)
  TITLE          — generate a conversation title

NOTE: The operation field is only populated for DATA_OPERATION intent.
"""
import json


def build_interpreter_prompt(
    query: str,
    semantic_context: dict,
) -> str:
    """
    Build the LLM interpretation prompt.

    Args:
        query: The normalized user query.
        semantic_context: Dict from SemanticContextBuilder.build().

    Returns:
        A prompt string for the LLM classification/interpretation call.
    """
    dataset_loaded = semantic_context.get("dataset_loaded", False)
    dataset_filename = semantic_context.get("dataset_filename") or "unnamed dataset"
    columns = semantic_context.get("columns", [])
    referenced_cols = semantic_context.get("referenced_columns", [])
    compatible_caps = semantic_context.get("compatible_capabilities", [])
    workspace_ctx = semantic_context.get("workspace_context", {})

    # ── Build column schema block ─────────────────────────────────────────────
    if dataset_loaded and columns:
        col_lines = []
        for col in columns[:30]:  # Limit to 30 columns in prompt
            name = col.get("name", "")
            ctype = col.get("type", "unknown")
            samples = col.get("samples", [])
            sample_str = f" (e.g. {', '.join(str(s) for s in samples[:2])})" if samples else ""
            col_lines.append(f"  - {name} [{ctype}]{sample_str}")
        col_block = "DATASET SCHEMA:\n" + "\n".join(col_lines)
        ref_block = (
            f"\nCOLUMNS REFERENCED IN QUERY: {', '.join(referenced_cols)}"
            if referenced_cols else ""
        )
    else:
        col_block = "NO DATASET LOADED."
        ref_block = ""

    # ── Build capabilities block ──────────────────────────────────────────────
    if dataset_loaded and compatible_caps:
        cap_lines = [
            f"  - {c['type']}: {c['description']}"
            for c in compatible_caps[:15]  # Cap at 15
        ]
        cap_block = "AVAILABLE ANALYTICAL CAPABILITIES:\n" + "\n".join(cap_lines)
    else:
        cap_block = ""

    # ── Build workspace context block ─────────────────────────────────────────
    ws_lines = []
    active_action = workspace_ctx.get("active_action")
    if active_action:
        ws_lines.append(f"  Active action: {active_action.get('type')} — {active_action.get('description', '')[:80]}")
    recent_ops = workspace_ctx.get("recent_operations", [])
    if recent_ops:
        ops_str = ", ".join(
            f"{op.get('type')}({op.get('column', '')})" for op in recent_ops
        )
        ws_lines.append(f"  Recent operations: {ops_str}")
    selected_rows = workspace_ctx.get("selected_rows", [])
    if selected_rows:
        ws_lines.append(f"  Selected rows: {selected_rows[:10]} ({workspace_ctx.get('selected_row_count', 0)} total)")
    ws_block = ("WORKSPACE CONTEXT:\n" + "\n".join(ws_lines)) if ws_lines else ""

    # ── Build the full prompt ─────────────────────────────────────────────────
    sections = [
        s for s in [col_block, ref_block, cap_block, ws_block] if s
    ]
    context_block = "\n\n".join(sections) if sections else "(no additional context)"

    # ── Interpretation rules ──────────────────────────────────────────────────
    dataset_rule = (
        "\nROUTING RULES FOR DATASET QUESTIONS:\n"
        "  - If dataset IS loaded and the user asks about the data (min/max/average/count/\n"
        "    top/bottom/missing/duplicates/filter/sort/correlation/outliers etc.) for any\n"
        "    of the listed columns → intent MUST be DATA_OPERATION.\n"
        "  - 'help_system' and CONVERSATION are NEVER correct for dataset data questions.\n"
        "  - If dataset IS loaded and a column is referenced → prefer DATA_OPERATION.\n"
        "  - Distinguish conceptual questions ('what is standard deviation?') from\n"
        "    dataset-specific questions ('what is the standard deviation of age?').\n"
        "    The first may be CONVERSATION; the second is DATA_OPERATION + STD.\n"
    ) if dataset_loaded else (
        "\nROUTING RULES (NO DATASET):\n"
        "  - No dataset is loaded. Do not invent data results.\n"
        "  - If the user asks about data that would require a dataset, use CONVERSATION\n"
        "    and suggest they upload a dataset.\n"
    )

    operation_schema = """
OPERATION SCHEMA (use when intent=DATA_OPERATION):
  For MIN/MAX:
    {"type": "MIN", "column": "column_name"}
    {"type": "MAX", "column": "column_name"}
  For aggregate (mean/median/std/sum/count):
    {"type": "AGGREGATE", "column": "column_name", "func": "mean"}
  For TOP_N/BOTTOM_N:
    {"type": "TOP_N", "column": "column_name", "n": 10, "order": "desc"}
    {"type": "BOTTOM_N", "column": "column_name", "n": 5, "order": "asc"}
  For FILTER:
    {"type": "FILTER", "column": "column_name", "operator": ">", "value": 50}
  For FIND_DUPLICATES:
    {"type": "FIND_DUPLICATES", "columns": ["email"]}
  For FIND_MISSING:
    {"type": "FIND_MISSING", "columns": ["email", "phone"]}
  For FIND_OUTLIERS:
    {"type": "FIND_OUTLIERS", "column": "column_name", "method": "iqr"}
  For CORRELATION:
    {"type": "CORRELATION", "column_a": "col1", "column_b": "col2"}
  For COUNT:
    {"type": "COUNT", "column": "column_name"}
"""

    examples = """
EXAMPLES:
  Q: "what is the lowest age?"  (dataset with age [numeric])
  → {"intent": "DATA_OPERATION", "operation": {"type": "MIN", "column": "age"}, "confidence": 0.97, "reason": "Lowest = minimum; age column is numeric"}

  Q: "what is the highest revenue?"  (dataset with revenue [numeric])
  → {"intent": "DATA_OPERATION", "operation": {"type": "MAX", "column": "revenue"}, "confidence": 0.96, "reason": "Highest = maximum; revenue column is numeric"}

  Q: "what is the average age?"  (dataset loaded)
  → {"intent": "DATA_OPERATION", "operation": {"type": "AGGREGATE", "column": "age", "func": "mean"}, "confidence": 0.97, "reason": "Average = mean aggregate on age"}

  Q: "what is standard deviation?"  (general knowledge, no specific column)
  → {"intent": "CONVERSATION", "operation": null, "confidence": 0.88, "reason": "Conceptual question about the statistical concept, no specific dataset column requested"}

  Q: "what is the standard deviation of age in this dataset?"  (dataset loaded, age column exists)
  → {"intent": "DATA_OPERATION", "operation": {"type": "AGGREGATE", "column": "age", "func": "std"}, "confidence": 0.97, "reason": "Explicitly requests std of the age column in the loaded dataset"}

  Q: "show me the top 10 cities"  (dataset with city [text])
  → {"intent": "DATA_OPERATION", "operation": {"type": "TOP_N", "column": "city", "n": 10, "order": "desc"}, "confidence": 0.90, "reason": "Top N rows for city column"}

  Q: "find duplicate emails"  (dataset with email column)
  → {"intent": "DATA_OPERATION", "operation": {"type": "FIND_DUPLICATES", "columns": ["email"]}, "confidence": 0.95, "reason": "Find duplicate values in email column"}

  Q: "hello, how are you?"
  → {"intent": "CONVERSATION", "operation": null, "confidence": 0.99, "reason": "Greeting"}

  Q: "what can you do?"
  → {"intent": "CONVERSATION", "operation": null, "confidence": 0.95, "reason": "General capability question"}
"""

    prompt = f"""You are the Plexis semantic intent interpreter.

Your job: interpret the user's query and return a JSON interpretation.

USER QUERY: "{query}"

CONTEXT:
{context_block}
{dataset_rule}
{operation_schema}
{examples}
RETURN ONLY a single valid JSON object — no prose, no markdown fences.
Required keys: intent, operation, confidence, reason.
intent must be exactly one of: DATA_OPERATION, CONVERSATION, EXPLANATION, TITLE
"""

    return prompt.strip()

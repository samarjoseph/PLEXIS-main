"""
Router Prompt Module

Responsible ONLY for intent classification.
Never cares about personality, emojis, or formatting.

IMPORTANT: When a dataset is loaded, the routing decision MUST account for
dataset availability and schema. Analytical questions about loaded data are
NEVER routed to help_system.
"""


def build_router_prompt(
    query: str,
    valid_intents: str = "conversation, analysis, web_search, help_system, title_generation",
    dataset_loaded: bool = False,
    dataset_filename: str = "",
    dataset_columns: list = None,
) -> str:
    """Builds the prompt used by the master router for LLM classification."""

    # Dataset context block — only included when a dataset is active
    dataset_block = ""
    if dataset_loaded:
        col_str = ", ".join(dataset_columns[:20]) if dataset_columns else "unknown"
        dataset_block = (
            f"\n\nDATASET CONTEXT (CRITICAL):\n"
            f"  A dataset is currently loaded: {dataset_filename or 'unnamed dataset'}\n"
            f"  Columns available: {col_str}\n\n"
            f"ROUTING RULE — WHEN DATASET IS LOADED:\n"
            f"  If the query asks about the data (e.g. lowest/highest/average/count/missing/\n"
            f"  duplicate/filter/top N/bottom N/correlation/distribution) for any of the\n"
            f"  available columns, the intent is ALWAYS 'analysis' — NEVER 'help_system'.\n"
            f"  'help_system' is ONLY for questions about how Plexis works, its features,\n"
            f"  or capabilities — NOT for data questions when a dataset is loaded.\n"
        )

    return (
        f"Classify this query into an intent routing payload: '{query}'"
        f"{dataset_block}\n"
        f"Possible intents: {valid_intents}\n\n"
        f"Intent definitions:\n"
        f"  analysis      — query is about the loaded dataset data (aggregates, filters, stats)\n"
        f"  conversation  — casual chat, knowledge questions, general explanations\n"
        f"  web_search    — needs live/current internet data\n"
        f"  help_system   — asking about Plexis features or how to use the tool (NOT data questions)\n"
        f"  title_generation — generating a title for a conversation\n\n"
        f"You are a routing agent. Return ONLY a JSON object with keys: "
        f"intent, confidence, execution_type, requires_dataset, requires_llm, "
        f"requires_planner, requires_context, requires_memory, estimated_cost, "
        f"estimated_latency, reasoning."
    )

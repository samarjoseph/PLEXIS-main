"""
Plexis Conversation Context Builder

This module constructs the context payload passed to the LLM.
It assembles relevant information from execution context, dataset state,
conversation history, and facts — providing only what the Conversation Engine
actually needs.

No routing logic. No planning logic. Only communication context.
"""

import json
from typing import Dict, Any, List, Optional


def build_context_block(
    message: str,
    intent: str,
    conversation_history: List[Dict[str, Any]],
    dataset_filename: Optional[str] = None,
    facts: Optional[Dict[str, Any]] = None,
    route_payload: Optional[Dict[str, Any]] = None,
    workspace_summary: Optional[str] = None,
    evidence_description: Optional[str] = None,
    schema_context: Optional[Dict] = None,
) -> str:
    """
    Assembles a clean, structured context string for the LLM.
    Only injects what is relevant. Avoids polluting the prompt with
    internal routing metadata the conversation engine doesn't need.

    workspace_summary: Natural language workspace state (from WorkspaceInterpreter).
                       LLMs receive language, never raw JSON workspace state.
    evidence_description: Short description of deterministically-found evidence.
                          LLMs explain what the system proved, not the other way around.
    """
    parts = []

    # --- Conversation State ---
    parts.append(f"CURRENT INTENT: {intent}")

    # --- Dataset context: only mention it if relevant ---
    if schema_context:
        parts.append(f"DATASET CONTEXT (Deterministic Schema):\n{json.dumps(schema_context, indent=2)}")
        parts.append(
            "CRITICAL SCHEMA GROUNDING RULES:\n"
            "- The list of columns above is the COMPLETE and EXCLUSIVE schema of the active dataset.\n"
            "- If the user asks to calculate, analyze, or query a column or field that does NOT exist in the schema list above (e.g. asking for a nonexistent column, score, or ticket price):\n"
            "  1. Explicitly state that the column or field does not exist and is not present in this dataset schema.\n"
            "  2. Clearly list the actual relevant columns available in the dataset.\n"
            "  3. Do NOT substitute, invent, or hallucinate values for missing fields.\n"
            "- If asked whether an arbitrary identifier (e.g. customerID, flight_id, order_id) can legitimately be used as a numeric predictor, explain that it is an arbitrary text/string identifier (not a measured numeric variable) and cannot legitimately be used as a numeric predictor."
        )
        
    if dataset_filename:
        parts.append(f"DATASET LOADED: {dataset_filename}")
        parts.append(
            "Note: The user has a dataset loaded. If they are asking about the data, "
            "respond analytically. If they are simply chatting, just chat — "
            "do NOT force dataset references into every reply."
        )
    else:
        parts.append("DATASET STATE: No dataset is currently loaded.")

    # --- Workspace state (natural language — never raw JSON) ---
    if workspace_summary:
        parts.append(f"\nWORKSPACE STATE: {workspace_summary}")

    # --- Evidence context (deterministic system findings, not LLM-generated) ---
    if evidence_description:
        parts.append(
            f"\nSYSTEM FOUND (deterministic): {evidence_description}\n"
            "Reference the above finding in your response. Do not contradict it. "
            "The user can click 'Locate' in the chat to navigate to these rows in the workspace."
        )

    # --- Analytical facts (from engines like analysis) ---
    if facts and _has_meaningful_facts(facts):
        parts.append(
            "\n⚠️  CRITICAL GROUNDING RULE — READ THIS FIRST:\n"
            "The ANALYTICAL FACTS below were computed DETERMINISTICALLY by pandas on the real dataset.\n"
            "You MUST state EXACTLY the values shown in the ANALYTICAL FACTS block.\n"
            "Do NOT invent, estimate, round, or hallucinate any numeric value.\n"
            "Do NOT refuse to answer when a computed_answer, operation, or count is provided in the facts.\n"
            "If a computed value or count is 0, answer that the count is 0. 0 is a definitive, valid computed result (e.g., 0 rows match the criteria), NOT a lack of information.\n"
            "If the fact says max_value=65, say 65. If it says 108, say 108. Read the fact — do not guess.\n"
            "FOR HYPOTHETICAL / SIMULATION OPERATIONS:\n"
            "  The `hypothetical_value` is the PRIMARY answer for what the value would be among the remaining rows under the simulated condition.\n"
            "  The `original_value` is the pre-exclusion baseline across the original dataset for comparison only.\n"
            "  You MUST state the `hypothetical_value` as the resulting value among the remaining rows. NEVER state the `original_value` as the hypothetical result among the remaining rows.\n"
            "Your only job is to explain these computed facts directly and accurately in natural language."
        )
        parts.append("\nANALYTICAL FACTS (from computation on the real dataset):")
        try:
            facts_str = json.dumps(facts, indent=2, default=str)
            # Truncate very large fact payloads to prevent prompt bloat
            if len(facts_str) > 3000:
                facts_str = facts_str[:3000] + "\n... [truncated for brevity]"
            parts.append(facts_str)
        except Exception:
            parts.append(str(facts))

    # --- Conversation history: last 6 turns ---
    if conversation_history:
        recent = conversation_history[-6:]
        parts.append("\nCONVERSATION HISTORY (most recent last):")
        for msg in recent:
            role = msg.get('role', 'user').upper()
            content = str(msg.get('content', '')).strip()
            if content:
                # Truncate very long history messages
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(f"{role}: {content}")

    # --- The actual message ---
    parts.append(f"\nUSER: {message}")

    return "\n".join(parts)



def _has_meaningful_facts(facts: Dict[str, Any]) -> bool:
    """Return True if the facts dict contains something worth showing."""
    if not facts:
        return False
    # Ignore trivial type-only facts
    if set(facts.keys()) == {"type"}:
        return False
    # Ignore error-only facts for conversation — handle gracefully in text
    if set(facts.keys()) == {"error"}:
        return False
    return True

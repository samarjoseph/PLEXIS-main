"""
WorkspaceInterpreter — converts WorkspaceState JSON to a compact natural language
summary for LLM context injection.

Design principle:
  The LLM is a language model. It reasons better on language than on JSON schemas.
  Sending raw JSON workspace state burns tokens and reduces response quality.
  This interpreter converts the state to a single, semantically dense sentence.

Frontend mirror: src/utils/WorkspaceInterpreter.js
  Both implementations must remain semantically equivalent.
  Update both on any change to the interpretation logic.

Usage:
  interpreter = WorkspaceInterpreter()
  summary = interpreter.interpret(workspace_state_dict)
  # → "Viewing 8,472 rows, filtered by Country equals 'India', sorted by Revenue descending."
"""
from typing import Any, Dict, List, Optional


class WorkspaceInterpreter:
    """Translates WorkspaceState into a compact semantic summary for LLM context."""

    def interpret(self, workspace_state: Dict[str, Any]) -> str:
        """
        Convert workspace state dict to a natural language summary.

        Args:
          workspace_state: Dict from frontend WorkspaceContext state snapshot.

        Returns:
          A single compact sentence describing the current workspace state.
          Returns 'The dataset workspace is closed.' if workspace is not open.
        """
        if not workspace_state:
            return ""

        is_open = workspace_state.get('isOpen', False)
        if not is_open:
            return "The dataset workspace is closed."

        parts: List[str] = []

        # Total rows
        total_rows = workspace_state.get('totalRows', 0)
        if total_rows:
            parts.append(f"Viewing {total_rows:,} rows")
        else:
            parts.append("Viewing dataset")

        # Active filters
        filters = workspace_state.get('filters', []) or []
        if filters:
            filter_parts = []
            for f in filters:
                col = f.get('col', '')
                op = f.get('op', 'eq')
                val = f.get('val', '')
                op_label = self._op_label(op)
                filter_parts.append(f"{col} {op_label} \"{val}\"")
            parts.append(f"filtered by {', '.join(filter_parts)}")

        # Sort
        sort = workspace_state.get('sort')
        if sort and sort.get('col'):
            direction = "descending" if sort.get('dir') == 'desc' else "ascending"
            parts.append(f"sorted by {sort['col']} {direction}")

        # Search
        search = workspace_state.get('search', '')
        if search:
            parts.append(f"searching for \"{search}\"")

        # Row selection
        selection = workspace_state.get('selection', {}) or {}
        selected_rows = selection.get('rows', []) or []
        selected_cols = selection.get('columns', []) or []
        if selected_rows:
            count = len(selected_rows)
            parts.append(f"{count} row{'s' if count > 1 else ''} selected")
            if selected_cols:
                parts.append(f"focusing on columns: {', '.join(selected_cols[:5])}")

        # Active evidence highlight
        active_evidence = workspace_state.get('activeEvidence')
        if active_evidence:
            desc = active_evidence.get('description', '')
            if desc:
                parts.append(f"currently highlighting: {desc}")

        # Scroll offset
        current_offset = workspace_state.get('currentOffset', 0)
        if current_offset and current_offset > 0:
            parts.append(f"viewing from row {current_offset:,}")

        if not parts:
            return "The dataset workspace is open."

        return ", ".join(parts) + "."

    def _op_label(self, op: str) -> str:
        """Convert operator shorthand to readable text."""
        labels = {
            'eq':       'equals',
            'neq':      'does not equal',
            'gt':       'greater than',
            'gte':      'greater than or equal to',
            'lt':       'less than',
            'lte':      'less than or equal to',
            'contains': 'contains',
            'starts':   'starts with',
            'ends':     'ends with',
        }
        return labels.get(op, op)

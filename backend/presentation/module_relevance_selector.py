"""
Presentation Layer — Module Relevance Selector (RFC-002 §5.3)

Selects which Knowledge Modules are relevant to a user's chat query.
Used by the chat context builder to avoid sending all 12 modules to the LLM.

Phase 1: keyword + role matching (deterministic, no embeddings needed)
Phase 2 (future): embedding-based semantic similarity

Design (audit fix — chat flow was unimplementable without this):
  Max modules returned: 3 (preserves chat token budget)
  Fallback: returns executive + insights modules if no match
"""

from __future__ import annotations

import re
import logging
from typing import List

from .domain.contracts import KnowledgeBundle, KnowledgeModule, ModuleID

logger = logging.getLogger(__name__)

MAX_MODULES_FOR_CHAT = 3

# Keyword → module_id mapping (order matters: first match wins)
KEYWORD_MODULE_MAP = [
    # Quality signals
    (["quality", "missing", "null", "duplicate", "clean", "complete", "issue", "error"],
     ModuleID.QUALITY),

    # Statistics signals
    (["average", "mean", "median", "min", "max", "range", "std", "variance",
      "statistic", "distribution", "spread", "outlier"],
     ModuleID.STATISTICS),

    # Relationship signals
    (["correlat", "relationship", "between", "group by", "group", "driven by",
      "affect", "impact", "influence", "depend"],
     ModuleID.RELATIONSHIPS),

    # Pattern signals
    (["pattern", "bimodal", "skew", "tail", "concentration", "seasonal",
      "periodic", "anomaly", "cluster", "unusual"],
     ModuleID.PATTERNS),

    # Rare value signals
    (["rare", "outlier", "singleton", "unusual value", "extreme", "anomal"],
     ModuleID.RARE),

    # Distribution signals
    (["distribut", "shape", "kurtosis", "normal", "right skew", "left skew", "histogram"],
     ModuleID.DISTRIBUTION),

    # Geographic signals
    (["country", "city", "region", "state", "location", "geography", "map", "geographic"],
     ModuleID.SEMANTIC),

    # Visualization signals
    (["chart", "graph", "plot", "visualiz", "dashboard", "bar chart", "line chart", "scatter"],
     ModuleID.VIZ),

    # Question signals
    (["question", "what can", "what should", "ask", "wonder", "next step"],
     ModuleID.QUESTIONS),

    # Column/schema signals
    (["column", "field", "variable", "schema", "type", "role", "identifier"],
     ModuleID.COLUMNS),
]


class ModuleRelevanceSelector:
    """
    Selects the top-K most relevant Knowledge Modules for a user query.

    Used by the chat endpoint to build context without sending all 12 modules.
    """

    def select(
        self, query: str, bundle: KnowledgeBundle
    ) -> List[KnowledgeModule]:
        """
        Return up to MAX_MODULES_FOR_CHAT relevant modules, most relevant first.

        Args:
            query: The user's natural language chat question.
            bundle: The 12-module KnowledgeBundle from ModuleRegistry.

        Returns:
            List of KnowledgeModule, max length = MAX_MODULES_FOR_CHAT.
        """
        query_lower = query.lower()
        matched_ids = []

        for keywords, module_id in KEYWORD_MODULE_MAP:
            if any(kw in query_lower for kw in keywords):
                module = bundle.get_module(module_id)
                if module and module.is_available and module_id not in matched_ids:
                    matched_ids.append(module_id)
                if len(matched_ids) >= MAX_MODULES_FOR_CHAT:
                    break

        if not matched_ids:
            # Fallback: insights + semantic (always context-enriching)
            matched_ids = [ModuleID.INSIGHTS, ModuleID.SEMANTIC]

        modules = []
        for mid in matched_ids[:MAX_MODULES_FOR_CHAT]:
            m = bundle.get_module(mid)
            if m and m.is_available:
                modules.append(m)

        logger.info(
            f"ModuleRelevanceSelector: query='{query[:50]}' → "
            f"modules={[m.module_id for m in modules]}"
        )
        return modules


# Module-level singleton
module_relevance_selector = ModuleRelevanceSelector()

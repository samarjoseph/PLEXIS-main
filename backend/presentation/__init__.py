"""
Presentation Layer — RFC-002: Modular Knowledge Architecture v2.0

Pipeline:
  DKO → KnowledgeDecomposer (12 modules) → SemanticImportanceRanker (13th executive)
       → ModuleRegistry (stored by dataset_id)
       → PresentationEngine (primary narrative, ~700 tokens)
       → ModuleExplainer (on-demand per-card SSE, ~300 tokens)
"""

from .knowledge_decomposer import KnowledgeDecomposer, knowledge_decomposer
from .importance_ranker import SemanticImportanceRanker, importance_ranker
from .module_registry import ModuleRegistry, module_registry
from .presentation_engine import PresentationEngine, presentation_engine
from .module_explainer import ModuleExplainer, module_explainer
from .session_manager import SessionManager, session_manager
from .module_relevance_selector import ModuleRelevanceSelector, module_relevance_selector
from .explanation_cache import ExplanationCache, explanation_cache

__all__ = [
    "KnowledgeDecomposer", "knowledge_decomposer",
    "SemanticImportanceRanker", "importance_ranker",
    "ModuleRegistry", "module_registry",
    "PresentationEngine", "presentation_engine",
    "ModuleExplainer", "module_explainer",
    "SessionManager", "session_manager",
    "ModuleRelevanceSelector", "module_relevance_selector",
    "ExplanationCache", "explanation_cache",
]

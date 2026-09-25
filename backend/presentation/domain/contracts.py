"""
Presentation Layer — Domain Contracts

All dataclasses and types that form the contracts between presentation components.
This is the foundation layer — all other presentation modules import from here.

Lifecycle clarification (from audit C-3):
  - KnowledgeDecomposer builds 12 SOURCE modules
  - SemanticImportanceRanker builds the 13th DERIVED 'executive' module
  - ModuleRegistry stores all 13 modules
  - PresentationEngine reads only the executive module
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ModuleID(str, Enum):
    """Canonical module identifiers — prevents magic strings."""
    EXECUTIVE     = "executive"       # DERIVED by ranker, not by decomposer
    QUALITY       = "quality"
    STATISTICS    = "statistics"
    COLUMNS       = "columns"
    RELATIONSHIPS = "relationships"
    PATTERNS      = "patterns"
    RARE          = "rare"
    DISTRIBUTION  = "distribution"
    INSIGHTS      = "insights"
    VIZ           = "viz"
    SEMANTIC      = "semantic"
    QUESTIONS     = "questions"


# PII-sensitive semantic types — values in these columns are REDACTED
# before flowing into the Ranker and LLM context (audit fix C-5)
PII_SEMANTIC_TYPES = {
    "email", "phone", "name", "uuid", "address"
}

# Richness threshold — modules below this are not rendered in the UI
RICHNESS_THRESHOLD = 20.0


@dataclass
class ExecutiveFact:
    """
    A single prioritized, scored fact destined for the primary LLM narrative.

    The LLM receives only these facts — never raw DKO JSON.
    The 'context' field is the only natural-language bridge between the
    deterministic intelligence engine and the LLM.

    Note: value is REDACTED if source column has a PII semantic type.
    """
    category:      str            # quality|scale|metric|anomaly|relationship|opportunity|pattern
    title:         str            # Human-readable label (e.g. "Primary KPI")
    value:         Any            # The fact (number, string, list)
    unit:          Optional[str]  # "%", "rows", "columns", None
    score:         float          # 0–100 importance score (from ranker)
    is_anomalous:  bool           # Is this surprising relative to the dataset?
    source_module: str            # Which ModuleID produced this fact
    context:       str            # 1-line human-readable context for the LLM


@dataclass
class KnowledgeModule:
    """
    A single named, typed knowledge container extracted from the DKO.

    richness_score < RICHNESS_THRESHOLD → not rendered in the UI.
    preview:        Deterministic 1-sentence subtitle (no LLM needed).
    data:           Typed dict conforming to RFC-002 §10 JSON schemas.
    prompt_version: Included in ExplanationCacheKey — increment when
                    the module's system prompt changes (audit fix).
    """
    module_id:      str            # One of ModuleID values
    display_name:   str            # Human-readable name for card header
    icon:           str            # Icon name (e.g. "shield-check")
    richness_score: float          # 0–100; threshold = RICHNESS_THRESHOLD
    fact_count:     int            # Number of extractable facts
    is_available:   bool           # False when DKO had no data for this module
    data:           Dict[str, Any] # Full module payload per RFC-002 §10
    preview:        str            # Deterministic card subtitle
    prompt_version: int = 1        # Version of the module's system prompt


@dataclass
class KnowledgeBundle:
    """
    The complete set of 12 source Knowledge Modules from KnowledgeDecomposer.

    The executive module (13th) is NOT included here — it is built by
    SemanticImportanceRanker and stored in ExecutiveSummary.
    """
    dataset_id:    str
    fingerprint:   str             # DKO fingerprint — used in all cache keys
    dataset_name:  str

    quality:       KnowledgeModule
    statistics:    KnowledgeModule
    columns:       KnowledgeModule
    relationships: KnowledgeModule
    patterns:      KnowledgeModule
    rare:          KnowledgeModule
    distribution:  KnowledgeModule
    insights:      KnowledgeModule
    viz:           KnowledgeModule
    semantic:      KnowledgeModule
    questions:     KnowledgeModule

    def all_modules(self) -> List[KnowledgeModule]:
        """Return all 12 source modules as a list."""
        return [
            self.quality, self.statistics, self.columns, self.relationships,
            self.patterns, self.rare, self.distribution, self.insights,
            self.viz, self.semantic, self.questions,
        ]

    def get_module(self, module_id: str) -> Optional[KnowledgeModule]:
        """Get a source module by ID string. Returns None if unknown or executive."""
        mapping = {
            ModuleID.QUALITY:        self.quality,
            ModuleID.STATISTICS:     self.statistics,
            ModuleID.COLUMNS:        self.columns,
            ModuleID.RELATIONSHIPS:  self.relationships,
            ModuleID.PATTERNS:       self.patterns,
            ModuleID.RARE:           self.rare,
            ModuleID.DISTRIBUTION:   self.distribution,
            ModuleID.INSIGHTS:       self.insights,
            ModuleID.VIZ:            self.viz,
            ModuleID.SEMANTIC:       self.semantic,
            ModuleID.QUESTIONS:      self.questions,
        }
        return mapping.get(module_id)  # type: ignore[arg-type]

    def available_modules(self) -> List[KnowledgeModule]:
        """Return only modules that have richness_score >= RICHNESS_THRESHOLD."""
        return [m for m in self.all_modules() if m.richness_score >= RICHNESS_THRESHOLD]


@dataclass
class ExecutiveSummary:
    """
    Output of SemanticImportanceRanker.

    Contains:
      - The 13th (derived) executive module for ModuleRegistry storage
      - The top-25 ExecutiveFacts for the primary LLM narrative
      - The original KnowledgeBundle (12 source modules)
    """
    executive_module: KnowledgeModule   # The 13th derived module
    facts:            List[ExecutiveFact]  # Top-25 facts for LLM
    bundle:           KnowledgeBundle
    dataset_id:       str
    fingerprint:      str


@dataclass(frozen=True)
class ExplanationCacheKey:
    """
    Immutable cache key for module explanations.

    prompt_version is included so stale explanations are automatically
    invalidated when a system prompt is improved (audit fix).

    session_id is NOT part of the key — explanations are dataset-level,
    not session-level. Same dataset always yields the same explanation.
    """
    dataset_fingerprint: str    # from DKO.fingerprint
    module_id:           str    # e.g. "patterns"
    prompt_version:      int    # from KnowledgeModule.prompt_version

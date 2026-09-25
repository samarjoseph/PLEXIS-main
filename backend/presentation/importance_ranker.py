"""
Presentation Layer — Semantic Importance Ranker

Scores every extractable fact across all 12 source modules using a
5-factor weighted model, then selects the top-25 as ExecutiveFacts.
Also builds the 13th (derived) executive module.

Single Responsibility: KnowledgeBundle → ExecutiveSummary
LLM calls: NONE — 100% deterministic

5-Factor Scoring Model:
  anomaly_score     × 0.30  — Is this fact unusual?
  domain_relevance  × 0.25  — Does domain context elevate this?
  data_presence     × 0.20  — Is it backed by sufficient data?
  effect_size       × 0.15  — Is the magnitude meaningful?
  novelty           × 0.10  — Percentile rank within its module's fact set

Audit Fixes Applied:
  C-3: Executive module built HERE (not in decomposer) — resolves circular dependency
  Audit §8.5: FactDeduplicator — max 2 facts per column, max 4 per category
  Audit §8.2.1: Adaptive weight normalization for anomaly-free / domain-unknown datasets
  Audit §8.2.2: Novelty = percentile rank of effect_size within module's fact set
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dataset_intelligence.models_v2 import DatasetKnowledgeObject
from .domain.contracts import (
    KnowledgeBundle, KnowledgeModule, ExecutiveFact, ExecutiveSummary, ModuleID
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring configuration
# ---------------------------------------------------------------------------

BASE_WEIGHTS = {
    "anomaly_score":    0.30,
    "domain_relevance": 0.25,
    "data_presence":    0.20,
    "effect_size":      0.15,
    "novelty":          0.10,
}

MAX_FACTS_PER_COLUMN   = 2   # Deduplication: max facts per affected column
MAX_FACTS_PER_CATEGORY = 4   # Deduplication: max facts per category type
MAX_EXECUTIVE_FACTS    = 25
MIN_EXECUTIVE_FACTS    = 10

# Domain-aware boosting: which fact categories to boost per domain
DOMAIN_BOOST: Dict[str, Dict[str, float]] = {
    "Retail/Sales":        {"metric": 1.4, "relationship": 1.2, "pattern": 1.3},
    "Finance":             {"anomaly": 1.5, "metric": 1.3, "pattern": 1.4},
    "HR":                  {"metric": 1.3, "scale": 1.1},
    "Education":           {"metric": 1.3, "quality": 1.2},
    "Healthcare":          {"quality": 1.5, "anomaly": 1.4},
    "Marketing":           {"metric": 1.3, "relationship": 1.2},
    "E-Commerce":          {"metric": 1.4, "relationship": 1.3, "pattern": 1.2},
    "Customer Analytics":  {"metric": 1.3, "relationship": 1.4},
    "General Purpose":     {"quality": 1.2, "scale": 1.1},
}


@dataclass
class _RawFact:
    """Internal intermediate fact before scoring."""
    category:      str
    title:         str
    value:         Any
    unit:          Optional[str]
    source_module: str
    context:       str
    affected_column: Optional[str]  # for deduplication grouping

    # Raw inputs to scoring formula
    is_anomalous:    bool  = False
    domain_relevant: bool  = False
    data_presence:   float = 1.0   # 0.0–1.0
    raw_effect_size: float = 0.0   # absolute magnitude indicator


# ---------------------------------------------------------------------------
# SemanticImportanceRanker
# ---------------------------------------------------------------------------

class SemanticImportanceRanker:
    """
    Scores and ranks all extractable facts from a KnowledgeBundle,
    then assembles ExecutiveFacts and builds the executive module.
    """

    def rank(
        self, bundle: KnowledgeBundle, dko: DatasetKnowledgeObject
    ) -> ExecutiveSummary:
        """
        Main entry point.

        Returns an ExecutiveSummary containing:
          - executive_module: the 13th derived module (built HERE, not in decomposer)
          - facts: top-25 ExecutiveFacts for the primary LLM
          - bundle: the original 12-module bundle
        """
        logger.info(f"SemanticImportanceRanker: ranking facts for '{bundle.dataset_name}'")

        domain = self._detect_domain(dko)
        weights = self._adapt_weights(dko)
        raw_facts = self._extract_all_facts(bundle, dko)
        scored = self._score_facts(raw_facts, weights, domain, dko)
        deduped = self._deduplicate(scored)
        top_facts = deduped[:MAX_EXECUTIVE_FACTS]
        if len(top_facts) < MIN_EXECUTIVE_FACTS:
            top_facts = scored[:MAX_EXECUTIVE_FACTS]  # fallback without dedup

        executive_facts = [
            ExecutiveFact(
                category=f.category,
                title=f.title,
                value=f.value,
                unit=f.unit,
                score=f.score,
                is_anomalous=f.is_anomalous,
                source_module=f.source_module,
                context=f.context,
            )
            for f in top_facts
        ]

        executive_module = self._build_executive_module(executive_facts, bundle, dko)

        logger.info(
            f"SemanticImportanceRanker: selected {len(executive_facts)} executive facts "
            f"from {len(raw_facts)} extracted (domain={domain})"
        )

        return ExecutiveSummary(
            executive_module=executive_module,
            facts=executive_facts,
            bundle=bundle,
            dataset_id=bundle.dataset_id,
            fingerprint=bundle.fingerprint,
        )

    # -------------------------------------------------------------------------
    # Weight Adaptation (audit §8.2.1)
    # -------------------------------------------------------------------------

    def _adapt_weights(self, dko: DatasetKnowledgeObject) -> Dict[str, float]:
        """
        Adapt scoring weights based on dataset profile.
        Redistributes weight from useless dimensions to productive ones.
        """
        weights = dict(BASE_WEIGHTS)
        qr = dko.quality_report

        # If dataset is nearly perfect quality, anomaly dimension is mostly empty
        if qr and qr.overall_score > 95 and len(qr.issues) == 0:
            weights["anomaly_score"] = 0.05
            weights["domain_relevance"] += 0.15
            weights["effect_size"] += 0.10

        # If domain confidence is low, domain_relevance dimension contributes noise
        domain_confidence = dko.domain.confidence if dko.domain else 0.0
        if domain_confidence < 0.5:
            weights["domain_relevance"] = 0.05
            weights["novelty"] += 0.10
            weights["effect_size"] += 0.10

        # Normalize to sum to 1.0
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}

    # -------------------------------------------------------------------------
    # Fact Extraction
    # -------------------------------------------------------------------------

    def _extract_all_facts(
        self, bundle: KnowledgeBundle, dko: DatasetKnowledgeObject
    ) -> List["_ScoredFact"]:
        """Extract raw facts from all 12 source modules."""
        raw: List[_RawFact] = []

        raw.extend(self._extract_quality_facts(bundle.quality, dko))
        raw.extend(self._extract_statistics_facts(bundle.statistics, dko))
        raw.extend(self._extract_relationship_facts(bundle.relationships, dko))
        raw.extend(self._extract_column_facts(bundle.columns, dko))
        raw.extend(self._extract_pattern_facts(bundle.patterns, dko))
        raw.extend(self._extract_rare_facts(bundle.rare, dko))
        raw.extend(self._extract_distribution_facts(bundle.distribution, dko))
        raw.extend(self._extract_insights_facts(bundle.insights, dko))
        raw.extend(self._extract_scale_facts(dko))
        raw.extend(self._extract_opportunity_facts(bundle.viz, dko))

        return raw

    def _extract_quality_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        d = module.data
        facts = []

        # Overall quality score — always present
        score = d.get("overall_score", 0)
        is_anomalous = score < 80
        facts.append(_RawFact(
            category="quality",
            title="Data Quality Score",
            value=score,
            unit="/100",
            source_module=ModuleID.QUALITY,
            context=f"Overall quality {score}/100 ({d.get('readiness', 'unknown')} readiness)",
            affected_column=None,
            is_anomalous=is_anomalous,
            domain_relevant=True,
            data_presence=1.0,
            raw_effect_size=abs(100 - score) / 100,
        ))

        # Duplicate rows
        dup = d.get("duplicate_rows", {})
        if dup.get("pct", 0) > 0:
            facts.append(_RawFact(
                category="quality",
                title="Duplicate Rows",
                value=dup.get("count", 0),
                unit="rows",
                source_module=ModuleID.QUALITY,
                context=f"{dup.get('pct', 0):.1f}% of rows are exact duplicates",
                affected_column=None,
                is_anomalous=dup.get("pct", 0) > 5,
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=dup.get("pct", 0) / 100,
            ))

        # Missing cells
        miss = d.get("missing_cells", {})
        if miss.get("pct", 0) > 0:
            facts.append(_RawFact(
                category="quality",
                title="Missing Data",
                value=f"{miss.get('pct', 0):.1f}%",
                unit="of cells",
                source_module=ModuleID.QUALITY,
                context=f"{miss.get('count', 0)} missing cells ({miss.get('pct', 0):.1f}%)",
                affected_column=None,
                is_anomalous=miss.get("pct", 0) > 10,
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=miss.get("pct", 0) / 100,
            ))

        # Critical issues
        for issue in d.get("issues", []):
            if issue.get("severity") in ("critical", "high"):
                facts.append(_RawFact(
                    category="anomaly",
                    title=f"Issue: {issue.get('type', 'unknown').replace('_', ' ').title()}",
                    value=issue.get("severity"),
                    unit=None,
                    source_module=ModuleID.QUALITY,
                    context=issue.get("description", ""),
                    affected_column=issue.get("affected_columns", [None])[0],
                    is_anomalous=True,
                    domain_relevant=True,
                    data_presence=1.0,
                    raw_effect_size=issue.get("impact_score", 5) / 10,
                ))

        return facts

    def _extract_statistics_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for col in module.data.get("numeric_columns", []):
            name = col.get("name", "")
            outlier_pct = col.get("outlier_pct", 0)
            is_primary = col.get("is_primary_metric", False)

            if is_primary:
                facts.append(_RawFact(
                    category="metric",
                    title=f"Primary KPI: {name}",
                    value=f"range {col.get('min')}–{col.get('max')}, mean {col.get('mean')}",
                    unit=None,
                    source_module=ModuleID.STATISTICS,
                    context=f"Primary metric '{name}': mean={col.get('mean')}, median={col.get('median')}, std={col.get('std')}",
                    affected_column=name,
                    is_anomalous=False,
                    domain_relevant=True,
                    data_presence=1.0,
                    raw_effect_size=0.8,
                ))

            if outlier_pct > 2.0:
                facts.append(_RawFact(
                    category="anomaly",
                    title=f"Outliers in {name}",
                    value=f"{outlier_pct:.1f}%",
                    unit="of values",
                    source_module=ModuleID.STATISTICS,
                    context=f"'{name}' has {outlier_pct:.1f}% outliers by IQR method",
                    affected_column=name,
                    is_anomalous=outlier_pct > 5,
                    domain_relevant=True,
                    data_presence=1.0,
                    raw_effect_size=min(1.0, outlier_pct / 20),
                ))
        return facts

    def _extract_relationship_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for corr in module.data.get("correlations", []):
            r = abs(corr.get("pearson_r", 0))
            if r > 0.4:
                facts.append(_RawFact(
                    category="relationship",
                    title=f"Correlation: {corr['col_a']} ↔ {corr['col_b']}",
                    value=f"r={corr['pearson_r']:.2f}",
                    unit=None,
                    source_module=ModuleID.RELATIONSHIPS,
                    context=corr.get("interpretation", f"r={corr['pearson_r']:.2f} ({corr.get('strength')})"),
                    affected_column=corr["col_a"],
                    is_anomalous=r > 0.85,
                    domain_relevant=True,
                    data_presence=1.0,
                    raw_effect_size=r,
                ))
        for grp in module.data.get("grouping_dimensions", []):
            facts.append(_RawFact(
                category="opportunity",
                title=f"Group by: {grp['column']}",
                value=grp.get("controls_metrics", []),
                unit=None,
                source_module=ModuleID.RELATIONSHIPS,
                context=f"'{grp['column']}' can group {len(grp.get('controls_metrics', []))} metric(s)",
                affected_column=grp["column"],
                is_anomalous=False,
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=grp.get("grouping_power", 0.5),
            ))
        return facts

    def _extract_column_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for col in module.data.get("columns", []):
            null_pct = col.get("null_pct", 0)
            if null_pct > 20:
                facts.append(_RawFact(
                    category="quality",
                    title=f"High Nulls: {col['name']}",
                    value=f"{null_pct:.1f}%",
                    unit="missing",
                    source_module=ModuleID.COLUMNS,
                    context=f"'{col['name']}' is {null_pct:.1f}% empty — may limit analytical usefulness",
                    affected_column=col["name"],
                    is_anomalous=null_pct > 50,
                    domain_relevant=True,
                    data_presence=1 - null_pct / 100,
                    raw_effect_size=null_pct / 100,
                ))
            if col.get("is_constant"):
                facts.append(_RawFact(
                    category="anomaly",
                    title=f"Constant Column: {col['name']}",
                    value="single value",
                    unit=None,
                    source_module=ModuleID.COLUMNS,
                    context=f"'{col['name']}' has only one unique value — analytically useless",
                    affected_column=col["name"],
                    is_anomalous=True,
                    domain_relevant=False,
                    data_presence=1.0,
                    raw_effect_size=0.9,
                ))
        return facts

    def _extract_pattern_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for p in module.data.get("patterns", []):
            facts.append(_RawFact(
                category="pattern",
                title=f"{p['type'].replace('_', ' ').title()} Pattern: {p['column']}",
                value=p["type"],
                unit=None,
                source_module=ModuleID.PATTERNS,
                context=p["description"],
                affected_column=p["column"],
                is_anomalous=p.get("severity") in ("high", "critical"),
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=p.get("importance_score", 50) / 100,
            ))
        return facts

    def _extract_rare_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for obs in module.data.get("observations", [])[:5]:
            facts.append(_RawFact(
                category="anomaly",
                title=f"Rare Value: {obs.get('column')}",
                value=obs.get("value"),
                unit=None,
                source_module=ModuleID.RARE,
                context=obs.get("description", ""),
                affected_column=obs.get("column"),
                is_anomalous=obs.get("importance_score", 40) > 60,
                domain_relevant=False,
                data_presence=1.0,
                raw_effect_size=obs.get("importance_score", 40) / 100,
            ))
        return facts

    def _extract_distribution_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for dist in module.data.get("distributions", []):
            dist_type = dist.get("distribution_type", "unknown")
            if dist_type not in ("normal", "unknown"):
                skewness = dist.get("skewness", 0) or 0
                facts.append(_RawFact(
                    category="pattern",
                    title=f"Distribution: {dist['column']}",
                    value=dist_type.replace("_", " ").title(),
                    unit=None,
                    source_module=ModuleID.DISTRIBUTION,
                    context=f"'{dist['column']}' is {dist_type.replace('_', ' ')} (skewness={skewness:.2f})",
                    affected_column=dist["column"],
                    is_anomalous=abs(skewness) > 2,
                    domain_relevant=True,
                    data_presence=1.0,
                    raw_effect_size=min(1.0, abs(skewness) / 4),
                ))
        return facts

    def _extract_insights_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        if not module.is_available:
            return []
        facts = []
        for ins in module.data.get("insights", [])[:6]:
            importance = ins.get("importance_score", 5.0)
            severity = ins.get("severity", "low")
            facts.append(_RawFact(
                category="metric" if ins.get("category") == "statistical" else ins.get("category", "metric"),
                title=ins["title"],
                value=ins.get("description", "")[:80],
                unit=None,
                source_module=ModuleID.INSIGHTS,
                context=ins.get("description", ""),
                affected_column=(ins.get("affected_columns") or [None])[0],
                is_anomalous=severity in ("critical", "high"),
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=importance / 10,
            ))
        return facts

    def _extract_scale_facts(self, dko) -> List[_RawFact]:
        """Always-present scale facts about the dataset itself."""
        return [
            _RawFact(
                category="scale",
                title="Dataset Size",
                value=f"{dko.row_count:,} rows × {dko.column_count} columns",
                unit=None,
                source_module=ModuleID.SEMANTIC,
                context=f"{dko.row_count:,} rows, {dko.column_count} columns, {dko.memory_usage_bytes // 1024}KB in memory",
                affected_column=None,
                is_anomalous=False,
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=0.3,
            )
        ]

    def _extract_opportunity_facts(self, module: KnowledgeModule, dko) -> List[_RawFact]:
        """Extract high-level capability facts."""
        count = len(dko.opportunities)
        if count == 0:
            return []
        names = [o.name for o in dko.opportunities[:5]]
        return [
            _RawFact(
                category="opportunity",
                title="Analysis Capabilities",
                value=count,
                unit="types",
                source_module=ModuleID.VIZ,
                context=f"{count} analysis types supported: {', '.join(names)}",
                affected_column=None,
                is_anomalous=False,
                domain_relevant=True,
                data_presence=1.0,
                raw_effect_size=min(1.0, count / 10),
            )
        ]

    # -------------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------------

    def _score_facts(
        self,
        raw_facts: List[_RawFact],
        weights: Dict[str, float],
        domain: str,
        dko,
    ) -> List["_ScoredFact"]:
        """Apply the 5-factor weighted scoring model to all raw facts."""
        domain_boosts = DOMAIN_BOOST.get(domain, {})

        # Compute effect sizes per module for novelty (§8.2.2)
        module_effects: Dict[str, List[float]] = {}
        for f in raw_facts:
            module_effects.setdefault(f.source_module, []).append(f.raw_effect_size)

        scored = []
        for f in raw_facts:
            # Factor 1: anomaly_score
            anomaly = 1.0 if f.is_anomalous else 0.2

            # Factor 2: domain_relevance
            category_boost = domain_boosts.get(f.category, 1.0)
            domain_rel = 1.0 if f.domain_relevant else 0.3
            domain_rel *= category_boost

            # Factor 3: data_presence
            presence = min(1.0, max(0.0, f.data_presence))

            # Factor 4: effect_size
            effect = min(1.0, max(0.0, f.raw_effect_size))

            # Factor 5: novelty — percentile rank within module (§8.2.2)
            siblings = sorted(module_effects.get(f.source_module, [f.raw_effect_size]))
            idx = siblings.index(f.raw_effect_size) if f.raw_effect_size in siblings else 0
            novelty = idx / max(len(siblings) - 1, 1)

            raw_score = (
                weights["anomaly_score"]    * anomaly
                + weights["domain_relevance"] * min(1.5, domain_rel)  # cap boost
                + weights["data_presence"]    * presence
                + weights["effect_size"]      * effect
                + weights["novelty"]          * novelty
            )

            # Normalize to 0–100
            score = min(100.0, raw_score * 100)

            scored.append(_ScoredFact(raw=f, score=score))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    # -------------------------------------------------------------------------
    # Deduplication (audit §8.5)
    # -------------------------------------------------------------------------

    def _deduplicate(self, scored: List["_ScoredFact"]) -> List["_ScoredFact"]:
        """
        Enforce fact diversity before budget selection.
        - Max MAX_FACTS_PER_COLUMN per affected column
        - Max MAX_FACTS_PER_CATEGORY per category
        """
        column_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        result = []

        for sf in scored:
            col = sf.raw.affected_column or "__global__"
            cat = sf.raw.category

            col_count = column_counts.get(col, 0)
            cat_count = category_counts.get(cat, 0)

            if col_count >= MAX_FACTS_PER_COLUMN:
                continue
            if cat_count >= MAX_FACTS_PER_CATEGORY:
                continue

            column_counts[col] = col_count + 1
            category_counts[cat] = cat_count + 1
            result.append(sf)

        return result

    # -------------------------------------------------------------------------
    # Executive Module Builder (audit C-3)
    # -------------------------------------------------------------------------

    def _build_executive_module(
        self,
        facts: List[ExecutiveFact],
        bundle: KnowledgeBundle,
        dko,
    ) -> KnowledgeModule:
        """
        Build the 13th derived 'executive' module from top-ranked facts.
        This is NOT called by KnowledgeDecomposer — only by this class.
        """
        identity = dko.get_dataset_identity()
        domain_result = dko.domain
        qr = dko.quality_report

        readiness_score = qr.overall_score if qr else 0.0
        readiness = qr.analysis_readiness if qr else "unknown"

        dataset_identity = {
            "name": dko.dataset_name,
            "rows": dko.row_count,
            "columns": dko.column_count,
            "domain": domain_result.domain.value if domain_result and hasattr(domain_result.domain, 'value') else "General Purpose",
            "domain_confidence": round(domain_result.confidence, 3) if domain_result else 0.0,
            "readiness": readiness,
            "readiness_score": round(readiness_score, 1),
        }

        facts_data = [
            {
                "category": f.category,
                "title": f.title,
                "value": f.value,
                "unit": f.unit,
                "score": round(f.score, 1),
                "is_anomalous": f.is_anomalous,
                "context": f.context,
            }
            for f in facts
        ]

        preview = (
            f"{dataset_identity['domain']} dataset — {dko.row_count:,} rows, "
            f"{dko.column_count} columns, quality {readiness_score:.0f}/100."
        )

        return KnowledgeModule(
            module_id=ModuleID.EXECUTIVE,
            display_name="Executive Summary",
            icon="star",
            richness_score=100.0,  # Always shown
            fact_count=len(facts),
            is_available=True,
            data={
                "module_id": ModuleID.EXECUTIVE,
                "facts": facts_data,
                "dataset_identity": dataset_identity,
            },
            preview=preview,
            prompt_version=1,
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _detect_domain(self, dko) -> str:
        if dko.domain and hasattr(dko.domain.domain, 'value'):
            return dko.domain.domain.value
        return "General Purpose"


@dataclass
class _ScoredFact:
    """Internal: a raw fact with its final computed score."""
    raw:   _RawFact
    score: float

    @property
    def category(self): return self.raw.category
    @property
    def title(self): return self.raw.title
    @property
    def value(self): return self.raw.value
    @property
    def unit(self): return self.raw.unit
    @property
    def source_module(self): return self.raw.source_module
    @property
    def context(self): return self.raw.context
    @property
    def is_anomalous(self): return self.raw.is_anomalous


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
importance_ranker = SemanticImportanceRanker()

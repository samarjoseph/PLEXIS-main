"""
Dataset Intelligence Engine — Stage 6: Domain Detector

Infers the business domain of the dataset using heuristic scoring
applied to semantic concepts, column names, and the semantic map.

No LLM calls. Pure deterministic inference.

Every domain prediction includes:
  - Inferred domain name
  - Confidence score (0.0–1.0)
  - Evidence list (human-readable reasons)
  - Optional secondary domain
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from .models import DataDomain, DomainResult, SemanticMap

logger = logging.getLogger(__name__)


class DomainDetector:
    """
    Stage 6 — Domain Detector

    Scores each possible domain using signals from:
      - Concept mappings in the SemanticMap (strongest signal)
      - Raw column names (secondary signal)
      - Dataset name (tertiary signal)

    Returns the domain with the highest score above a minimum threshold.
    Falls back to GENERAL if no domain exceeds the threshold.
    """

    # Minimum confidence score to report a non-GENERAL domain
    CONFIDENCE_THRESHOLD = 0.25

    # Minimum absolute score (raw points) before we trust a domain assignment
    MINIMUM_SCORE = 3

    def detect(self, dataset_name: str, semantics: SemanticMap) -> DomainResult:
        """
        Detect the business domain of the dataset.

        Args:
            dataset_name: Filename or identifier of the dataset
            semantics: Stage 5 SemanticMap

        Returns:
            A DomainResult with domain, confidence, and evidence.
        """
        scores: Dict[DataDomain, float] = {d: 0.0 for d in DataDomain}
        evidence: Dict[DataDomain, List[str]] = {d: [] for d in DataDomain}

        all_concepts = {
            col: sem.concept
            for col, sem in semantics.columns.items()
            if sem.concept
        }
        all_col_names = list(semantics.columns.keys())

        # Score based on concept signals (strongest signal)
        for col_name, concept in all_concepts.items():
            domain, score, reason = self._score_concept(concept, col_name)
            if domain:
                scores[domain] += score
                evidence[domain].append(reason)

        # Score based on column name patterns (secondary signal)
        for col_name in all_col_names:
            domain, score, reason = self._score_column_name(col_name)
            if domain:
                scores[domain] += score
                if reason not in evidence[domain]:
                    evidence[domain].append(reason)

        # Score based on dataset name (tertiary signal)
        ds_domain, ds_score, ds_reason = self._score_dataset_name(dataset_name)
        if ds_domain:
            scores[ds_domain] += ds_score
            evidence[ds_domain].append(ds_reason)

        # Find top-2 scoring domains
        sorted_domains = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_domain, top_score = sorted_domains[0]
        second_domain, second_score = sorted_domains[1] if len(sorted_domains) > 1 else (None, 0)

        total_score = sum(scores.values())
        confidence = round(top_score / total_score, 3) if total_score > 0 else 0.0

        if top_score < self.MINIMUM_SCORE or confidence < self.CONFIDENCE_THRESHOLD:
            return DomainResult(
                domain=DataDomain.GENERAL,
                confidence=1.0,
                evidence=["No strong domain signals detected."],
                secondary_domain=None,
            )

        secondary = second_domain if second_score >= self.MINIMUM_SCORE and second_domain != top_domain else None

        logger.info(f"DomainDetector: inferred domain='{top_domain.value}' (confidence={confidence:.2f})")
        return DomainResult(
            domain=top_domain,
            confidence=confidence,
            evidence=evidence[top_domain][:5],  # Cap evidence list
            secondary_domain=secondary,
        )

    def _score_concept(self, concept: str, col_name: str) -> Tuple[Optional[DataDomain], float, str]:
        """Score a domain based on a semantic concept."""
        c = concept.lower()

        if 'revenue' in c or 'sales' in c or 'price' in c or 'discount' in c:
            return DataDomain.RETAIL_SALES, 3.0, f"Column '{col_name}' maps to concept '{concept}'"
        if 'profit' in c or 'margin' in c or 'tax' in c or 'fee' in c:
            return DataDomain.FINANCE, 2.0, f"Column '{col_name}' maps to concept '{concept}'"
        if 'score' in c or 'grade' in c or 'gpa' in c or 'attendance' in c:
            return DataDomain.EDUCATION, 3.0, f"Column '{col_name}' maps to concept '{concept}'"
        if 'salary' in c or 'bonus' in c or 'tenure' in c or 'department' in c:
            return DataDomain.HR, 3.0, f"Column '{col_name}' maps to concept '{concept}'"
        if 'category' in c or 'product' in c or 'brand' in c or 'sku' in c:
            return DataDomain.RETAIL_SALES, 1.5, f"Column '{col_name}' maps to concept '{concept}'"

        return None, 0.0, ""

    def _score_column_name(self, col: str) -> Tuple[Optional[DataDomain], float, str]:
        """Score a domain based on raw column name patterns."""
        col_lower = col.lower()

        # Retail/Sales signals
        if any(w in col_lower for w in ['order', 'customer', 'cart', 'checkout', 'purchase', 'invoice', 'transaction']):
            return DataDomain.RETAIL_SALES, 2.0, f"Column '{col}' suggests retail/sales data"
        # E-commerce
        if any(w in col_lower for w in ['shipping', 'tracking', 'delivery', 'fulfillment']):
            return DataDomain.ECOMMERCE, 2.0, f"Column '{col}' suggests e-commerce data"
        # Education
        if any(w in col_lower for w in ['student', 'teacher', 'class', 'course', 'school', 'university', 'exam', 'curriculum']):
            return DataDomain.EDUCATION, 2.0, f"Column '{col}' suggests education data"
        # HR
        if any(w in col_lower for w in ['employee', 'hire', 'payroll', 'benefits', 'headcount', 'staff', 'workforce']):
            return DataDomain.HR, 2.0, f"Column '{col}' suggests HR data"
        # Healthcare
        if any(w in col_lower for w in ['patient', 'doctor', 'diagnosis', 'treatment', 'hospital', 'clinical', 'ward', 'medication']):
            return DataDomain.HEALTHCARE, 3.0, f"Column '{col}' suggests healthcare data"
        # Finance
        if any(w in col_lower for w in ['stock', 'equity', 'dividend', 'portfolio', 'asset', 'liability', 'balance']):
            return DataDomain.FINANCE, 2.5, f"Column '{col}' suggests finance data"
        # Marketing
        if any(w in col_lower for w in ['campaign', 'impression', 'click', 'conversion', 'lead', 'cpm', 'cpc', 'roas']):
            return DataDomain.MARKETING, 2.5, f"Column '{col}' suggests marketing data"
        # Sports
        if any(w in col_lower for w in ['player', 'team', 'match', 'game', 'win', 'loss', 'goal', 'stat', 'season']):
            return DataDomain.SPORTS, 2.0, f"Column '{col}' suggests sports data"
        # Logistics
        if any(w in col_lower for w in ['warehouse', 'freight', 'shipment', 'route', 'carrier', 'manifest']):
            return DataDomain.LOGISTICS, 2.5, f"Column '{col}' suggests logistics data"

        return None, 0.0, ""

    def _score_dataset_name(self, dataset_name: str) -> Tuple[Optional[DataDomain], float, str]:
        """Score a domain based on the dataset file/identifier name."""
        name_lower = dataset_name.lower()
        domain_keywords = {
            DataDomain.RETAIL_SALES: ['sales', 'revenue', 'orders', 'retail', 'ecommerce'],
            DataDomain.HR: ['hr', 'employee', 'workforce', 'payroll', 'staff'],
            DataDomain.EDUCATION: ['student', 'school', 'academic', 'grades', 'courses'],
            DataDomain.HEALTHCARE: ['patient', 'hospital', 'medical', 'clinical', 'health'],
            DataDomain.FINANCE: ['finance', 'financial', 'stock', 'portfolio', 'accounting'],
            DataDomain.MARKETING: ['marketing', 'campaign', 'ads', 'digital'],
            DataDomain.SPORTS: ['sports', 'athletes', 'players', 'teams', 'match'],
            DataDomain.LOGISTICS: ['logistics', 'shipment', 'supply', 'chain', 'warehouse'],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in name_lower for kw in keywords):
                return domain, 3.0, f"Dataset name '{dataset_name}' suggests {domain.value} domain"
        return None, 0.0, ""


domain_detector = DomainDetector()

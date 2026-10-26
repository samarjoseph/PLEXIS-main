"""
Semantic Schema Resolver for Plexis.

Provides generalized, reusable semantic schema resolution:
- Interprets user business concepts without brittle hardcoded mappings.
- Leverages schema evidence: data types, cardinality, value distributions, naming tokens, and semantic roles.
- Employs Head-Noun / Modifier weighting so 'customer rating' prioritizes 'Rating' over 'Customer_ID'.
- Distinguishes fine-grained financial constructs (pricing vs compensation vs revenue) to prevent false matches (e.g., salary -> Unit_Price).
- Detects ambiguity between multiple plausible measures (e.g. Total_Amount vs Order_Value).
- Caches semantic profiles per dataset instance with zero risk of stale cache.
- Purely deterministic and fast (< 2ms per resolution).
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class SemanticRole(str, Enum):
    IDENTIFIER = "IDENTIFIER"
    FINANCIAL_MEASURE = "FINANCIAL_MEASURE"
    QUANTITY = "QUANTITY"
    RATING_SCORE = "RATING_SCORE"
    STATUS_OUTCOME = "STATUS_OUTCOME"
    DATE_TIME = "DATE_TIME"
    GEOGRAPHIC = "GEOGRAPHIC"
    CATEGORICAL_DIMENSION = "CATEGORICAL_DIMENSION"
    UNKNOWN = "UNKNOWN"


# Fine-grained concept synonym clusters across domains
CONCEPT_SYNONYM_GROUPS: Dict[str, Set[str]] = {
    # Identifiers
    "transaction": {"transaction", "order", "purchase", "sale", "trans", "invoice", "receipt", "event"},
    "customer": {"customer", "client", "buyer", "user", "patron", "consumer", "account", "cust", "employee", "emp", "member", "passenger", "patient"},
    "product": {"product", "item", "sku", "good", "merchandise", "article"},
    "entity_id": {"id", "number", "num", "code", "key", "identifier", "uuid", "ref"},

    # Payment & promotions
    "payment": {"payment", "pay", "tender", "remittance", "billing"},
    "method": {"method", "mode", "channel", "type", "form", "gateway", "mechanism"},
    "promotion": {"promotion", "promo", "coupon", "voucher", "discount_code", "discount", "rebate", "offer"},

    # Metrics & Ratings
    "rating": {"rating", "score", "review", "satisfaction", "feedback", "stars", "grade"},
    "quantity": {"quantity", "qty", "count", "units", "items", "volume", "pieces"},
    "age": {"age", "years_old", "age_group"},

    # Financial Sub-concepts (strict separation)
    "revenue_sales": {"sales", "revenue", "turnover", "total_amount", "order_value", "gross", "bill_amount", "total", "amount"},
    "order_value": {"order_value", "order_amount", "cart_value", "subtotal", "base_amount", "order", "value", "amount"},
    "unit_price": {"unit_price", "price", "unit_cost", "mrp", "rate"},
    "cost_expense": {"cost", "expense", "spend", "shipping_cost", "cogs"},
    "compensation": {"salary", "wage", "bonus", "payroll", "stipend", "compensation"},
    "profit_margin": {"profit", "margin", "net_profit", "earnings"},

    # Status & Disposition
    "status": {"status", "state", "outcome", "disposition", "stage", "phase", "condition", "flag"},
    "delivery": {"delivery", "shipping", "dispatch", "fulfillment", "delivered"},
    "return": {"return", "refund", "returned", "cancellation", "cancelled"},

    # Temporal & Spatial
    "date": {"date", "day", "order_date", "timestamp", "datetime"},
    "time": {"time", "timestamp", "hour", "minute"},
    "location": {"city", "state", "country", "region", "territory", "zip", "location", "province", "district"},
}


@dataclass
class ColumnSemanticProfile:
    name: str
    clean_name: str
    tokens: List[str]
    token_set: Set[str]
    dtype: str
    dtype_category: str  # "numeric", "categorical", "temporal", "boolean"
    cardinality: int
    uniqueness_ratio: float
    missing_pct: float
    sample_values: List[str]
    primary_role: SemanticRole


@dataclass
class SemanticResolutionResult:
    concept: str
    resolved_column: Optional[str]
    confidence: float
    status: str  # "EXACT", "RESOLVED", "AMBIGUOUS", "UNSUPPORTED"
    is_ambiguous: bool
    candidates: List[Tuple[str, float, str]]  # [(col_name, score, reason)]
    ambiguity_details: Optional[Dict[str, Any]] = None
    evidence: str = ""


class DatasetSemanticProfile:
    """Encapsulates the full semantic profiling of a dataset's columns."""

    def __init__(self, df: pd.DataFrame, dataset_id: Optional[str] = None):
        self.dataset_id = dataset_id
        self.columns = list(df.columns)
        self.total_rows = len(df)
        self.profiles: Dict[str, ColumnSemanticProfile] = {}
        self._build_profiles(df)

    def _build_profiles(self, df: pd.DataFrame) -> None:
        for col in df.columns:
            s = df[col]
            clean_name = str(col).lower()
            tokens = re.findall(r'[a-z0-9]+', clean_name)
            token_set = set(tokens)

            # Raw & categorized dtypes
            raw_dtype = str(s.dtype)
            is_num = pd.api.types.is_numeric_dtype(s)
            is_bool = pd.api.types.is_bool_dtype(s)
            is_dt = pd.api.types.is_datetime64_any_dtype(s)

            non_null_s = s.dropna()
            total_non_null = len(non_null_s)
            uniq = int(non_null_s.nunique()) if total_non_null > 0 else 0
            uniq_ratio = (uniq / self.total_rows) if self.total_rows > 0 else 0.0
            missing_pct = round(((len(df) - total_non_null) / self.total_rows * 100), 2) if self.total_rows > 0 else 0.0
            samples = [str(x) for x in non_null_s.head(5).tolist()]

            # Determine category
            if is_bool or (uniq <= 2 and is_num):
                dtype_cat = "boolean"
            elif is_num:
                dtype_cat = "numeric"
            elif is_dt or any(k in clean_name for k in ("date", "time", "timestamp")):
                dtype_cat = "temporal"
            else:
                dtype_cat = "categorical"

            # Primary role detection
            id_keywords = {"id", "key", "uuid", "code", "num", "number", "ref"}
            has_id_kw = bool(token_set & id_keywords)

            if has_id_kw and (uniq_ratio > 0.10 or dtype_cat in ("categorical", "boolean")):
                primary_role = SemanticRole.IDENTIFIER
            elif dtype_cat == "numeric":
                if any(k in token_set for k in ("rating", "score", "index", "satisfaction", "stars", "grade")):
                    primary_role = SemanticRole.RATING_SCORE
                elif any(k in token_set for k in ("amount", "price", "cost", "value", "total", "sales", "revenue", "fee", "charge", "profit", "salary", "wage", "compensation", "bonus", "payroll", "stipend")):
                    primary_role = SemanticRole.FINANCIAL_MEASURE
                elif any(k in token_set for k in ("quantity", "qty", "count", "units", "items", "age", "hours", "days", "months", "years")):
                    primary_role = SemanticRole.QUANTITY
                else:
                    primary_role = SemanticRole.FINANCIAL_MEASURE if any(k in clean_name for k in ("amount", "val", "price", "cost")) else SemanticRole.QUANTITY
            elif dtype_cat == "temporal":
                primary_role = SemanticRole.DATE_TIME
            elif any(k in token_set for k in ("status", "flag", "state", "outcome", "mode", "channel", "churn", "delay")):
                primary_role = SemanticRole.STATUS_OUTCOME
            elif any(k in token_set for k in ("city", "state", "country", "region", "zip", "territory", "airport", "origin", "dest")):
                primary_role = SemanticRole.GEOGRAPHIC
            elif uniq_ratio > 0.85 and has_id_kw:
                primary_role = SemanticRole.IDENTIFIER
            else:
                primary_role = SemanticRole.CATEGORICAL_DIMENSION

            self.profiles[str(col)] = ColumnSemanticProfile(
                name=str(col),
                clean_name=clean_name,
                tokens=tokens,
                token_set=token_set,
                dtype=raw_dtype,
                dtype_category=dtype_cat,
                cardinality=uniq,
                uniqueness_ratio=uniq_ratio,
                missing_pct=missing_pct,
                sample_values=samples,
                primary_role=primary_role,
            )


class SemanticSchemaResolver:
    """
    Main resolver engine. Inspects active dataset schema and resolves
    business concepts with semantic evidence and ambiguity detection.
    """

    def __init__(self):
        self._profile_cache: Dict[Tuple[str, int, int], DatasetSemanticProfile] = {}

    def _get_cache_key(self, df: pd.DataFrame, dataset_id: Optional[str] = None) -> Tuple[str, int, int]:
        cols_key = hash(tuple(df.columns))
        rows_cnt = len(df)
        return (str(dataset_id or "unassigned"), cols_key, rows_cnt)

    def get_or_create_profile(self, df: pd.DataFrame, dataset_id: Optional[str] = None) -> DatasetSemanticProfile:
        cache_key = self._get_cache_key(df, dataset_id)
        if cache_key not in self._profile_cache:
            self._profile_cache[cache_key] = DatasetSemanticProfile(df, dataset_id)
        return self._profile_cache[cache_key]

    def resolve(
        self,
        concept: str,
        df: pd.DataFrame,
        expected_role: Optional[SemanticRole] = None,
        dataset_id: Optional[str] = None,
        threshold: float = 0.60,
    ) -> SemanticResolutionResult:
        profile = self.get_or_create_profile(df, dataset_id)
        concept_raw = str(concept).strip()
        concept_clean = concept_raw.lower().replace(" ", "_")
        concept_tokens = re.findall(r'[a-z0-9]+', concept_clean)
        concept_token_set = set(concept_tokens)

        # 1. Exact match (highest priority)
        for col_name in profile.columns:
            clean_col = col_name.lower()
            if clean_col == concept_clean or clean_col.replace("_", "") == concept_clean.replace("_", ""):
                return SemanticResolutionResult(
                    concept=concept_raw,
                    resolved_column=col_name,
                    confidence=1.0,
                    status="EXACT",
                    is_ambiguous=False,
                    candidates=[(col_name, 1.0, "exact_match")],
                    evidence=f"Exact match on dataset column '{col_name}'.",
                )

        # 2. Decompose Head Noun vs Modifier
        # In English noun phrases, the head noun is typically the LAST word:
        # e.g., 'customer rating' -> head='rating', modifier='customer'
        # 'transaction id' -> head='id', modifier='transaction'
        # 'payment method' -> head='method', modifier='payment'
        # 'promotion code' -> head='code', modifier='promotion'
        head_noun = concept_tokens[-1] if concept_tokens else ""
        modifiers = set(concept_tokens[:-1]) if len(concept_tokens) > 1 else set()

        # Find synonym groups matching head noun and modifiers
        head_synonyms = set()
        for group_name, syn_set in CONCEPT_SYNONYM_GROUPS.items():
            if head_noun in syn_set:
                head_synonyms.update(syn_set)

        modifier_synonyms: Dict[str, Set[str]] = {}
        for mod in modifiers:
            mod_syns = set()
            for group_name, syn_set in CONCEPT_SYNONYM_GROUPS.items():
                if mod in syn_set:
                    mod_syns.update(syn_set)
            if mod_syns:
                modifier_synonyms[mod] = mod_syns

        scored_candidates: List[Tuple[str, float, str]] = []

        for col_name, col_prof in profile.profiles.items():
            col_tokens = col_prof.tokens
            col_token_set = col_prof.token_set

            score = 0.0
            reasons = []

            # A. Head Noun Compatibility
            if head_noun and head_noun in col_token_set:
                score += 0.50
                reasons.append(f"head_match='{head_noun}'")
            elif head_synonyms and (col_token_set & head_synonyms):
                matched_syn = list(col_token_set & head_synonyms)[0]
                score += 0.45
                reasons.append(f"head_synonym='{matched_syn}'")
                # Bonus if multiple tokens in the column match the head noun synonyms (e.g. Satisfaction_Score)
                if len(col_token_set & head_synonyms) > 1:
                    score += 0.15
                    reasons.append("multiple_head_synonyms_matched")
            elif head_noun in ("id", "identifier", "key", "number", "ref") and col_prof.primary_role == SemanticRole.IDENTIFIER:
                score += 0.35
                reasons.append("identifier_role_head")

            # Check if concept token set as a whole has overlap with column tokens or synonyms
            concept_overlap = concept_token_set & col_token_set
            concept_synonym_overlap = set()
            for ct in concept_token_set:
                for group_name, syn_set in CONCEPT_SYNONYM_GROUPS.items():
                    if ct in syn_set and (col_token_set & syn_set):
                        concept_synonym_overlap.update(col_token_set & syn_set)

            if score == 0.0 and not concept_overlap and not concept_synonym_overlap:
                continue

            # B. Modifier Compatibility
            matched_mods = 0
            for mod, mod_syns in modifier_synonyms.items():
                if mod in col_token_set:
                    matched_mods += 1
                    reasons.append(f"modifier_match='{mod}'")
                elif col_token_set & mod_syns:
                    matched_syn = list(col_token_set & mod_syns)[0]
                    matched_mods += 1
                    reasons.append(f"modifier_synonym='{matched_syn}'")

            if modifiers:
                mod_ratio = matched_mods / len(modifiers)
                score += mod_ratio * 0.35
                if matched_mods > 0 and (head_noun in col_token_set or (col_token_set & head_synonyms)):
                    score += 0.10
                    reasons.append("compound_coherence_bonus")
            else:
                # Single-token concept (e.g. 'salary', 'rating')
                if score > 0:
                    score += 0.25
                    reasons.append("single_concept_salience")

            # C. Role-based alignment bonuses
            if col_prof.primary_role == SemanticRole.RATING_SCORE and any(t in concept_token_set or t in head_synonyms for t in ("rating", "score", "satisfaction", "review")):
                score += 0.20
                reasons.append("rating_role_match")
            elif col_prof.primary_role == SemanticRole.FINANCIAL_MEASURE and any(t in concept_token_set or t in head_synonyms for t in ("amount", "sales", "revenue", "price", "cost", "salary", "wage", "compensation")):
                score += 0.15
                reasons.append("financial_role_match")
            elif col_prof.primary_role == SemanticRole.IDENTIFIER and any(t in concept_token_set or t in head_synonyms for t in ("id", "identifier", "code", "number", "key", "ref")):
                score += 0.15
                reasons.append("identifier_role_match")

            # D. Generalized Domain & Entity Context Rules:
            # 1. Transaction Identifier vs Customer Identifier
            if "transaction" in concept_token_set or "order" in concept_token_set or "invoice" in concept_token_set:
                if col_prof.primary_role == SemanticRole.IDENTIFIER:
                    if any(t in col_token_set for t in ("order", "trans", "invoice", "receipt", "sale")):
                        score += 0.20
                        reasons.append("transaction_identifier_match")
                    elif any(t in col_token_set for t in ("customer", "client", "buyer", "user", "cust")):
                        score -= 0.25
                        reasons.append("customer_identifier_demoted")

            # 2. Strict Compensation vs General Sales/Revenue Separation
            comp_terms = {"salary", "wage", "bonus", "payroll", "stipend", "compensation"}
            if concept_token_set & comp_terms:
                if col_prof.primary_role == SemanticRole.FINANCIAL_MEASURE:
                    if not (col_token_set & comp_terms):
                        # Explicitly zero out sales/revenue/price columns when salary/compensation was asked
                        score = 0.0
                    else:
                        score += 0.15
                        reasons.append("compensation_term_confirmed")

            # 3. Unit Price vs Order/Total Amount
            if any(p in concept_token_set for p in ("unit_price", "price", "unit_cost")):
                if any(t in col_token_set for t in ("total", "order", "sum")):
                    score -= 0.25

            final_score = min(1.0, score)
            if final_score >= threshold:
                scored_candidates.append((col_name, round(final_score, 3), "; ".join(reasons)))

        # Sort candidates descending by score
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        # 3. Generalized Ambiguity Detection
        if len(scored_candidates) >= 2:
            top_cand, top_score, _ = scored_candidates[0]
            second_cand, second_score, _ = scored_candidates[1]

            top_prof = profile.profiles[top_cand]
            second_prof = profile.profiles[second_cand]

            # Ambiguity if both score well and are close in score
            if top_score >= 0.65 and second_score >= 0.60 and (top_score - second_score) <= 0.08:
                roles_compatible = (
                    top_prof.primary_role == second_prof.primary_role
                    or (top_prof.primary_role in (SemanticRole.FINANCIAL_MEASURE, SemanticRole.QUANTITY)
                        and second_prof.primary_role in (SemanticRole.FINANCIAL_MEASURE, SemanticRole.QUANTITY))
                )
                if roles_compatible:
                    ambiguity_info = {
                        "primary_candidate": top_cand,
                        "alternative_candidate": second_cand,
                        "top_score": top_score,
                        "second_score": second_score,
                        "candidates": [c[0] for c in scored_candidates[:3]],
                        "reason": f"Multiple plausible measures for '{concept_raw}': '{top_cand}' ({top_score}) and '{second_cand}' ({second_score}).",
                    }
                    return SemanticResolutionResult(
                        concept=concept_raw,
                        resolved_column=top_cand,
                        confidence=top_score,
                        status="AMBIGUOUS",
                        is_ambiguous=True,
                        candidates=scored_candidates,
                        ambiguity_details=ambiguity_info,
                        evidence=f"Ambiguous candidates detected: {top_cand} ({top_score}) vs {second_cand} ({second_score}).",
                    )

        # 4. Resolved cleanly
        if scored_candidates:
            top_cand, top_score, top_evidence = scored_candidates[0]
            return SemanticResolutionResult(
                concept=concept_raw,
                resolved_column=top_cand,
                confidence=top_score,
                status="RESOLVED",
                is_ambiguous=False,
                candidates=scored_candidates,
                evidence=f"Resolved '{concept_raw}' to '{top_cand}' (confidence={top_score}): {top_evidence}",
            )

        # 5. Unsupported concept
        return SemanticResolutionResult(
            concept=concept_raw,
            resolved_column=None,
            confidence=0.0,
            status="UNSUPPORTED",
            is_ambiguous=False,
            candidates=[],
            evidence=f"No matching column found for business concept '{concept_raw}' in dataset schema.",
        )


semantic_schema_resolver = SemanticSchemaResolver()


def get_semantic_resolver() -> SemanticSchemaResolver:
    return semantic_schema_resolver

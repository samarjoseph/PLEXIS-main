"""
LocatorBuilder — constructs a stable RowLocator from a DataFrame + boolean mask + DKO.

Called exclusively by IAnalyticalCapability implementations.
The AnalysisEngine and ResponseComposer never construct row indices directly.

Resolution priority:
  1. Primary key detected via DKO column annotations
  2. Composite key (multiple semantic identifier columns)
  3. SHA-256 row hash (always available as fallback)
  4. Position-only (last resort, marked unstable)
"""
import hashlib
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from evidence.locators import LocatorStrategy, RowLocator

logger = logging.getLogger(__name__)


class LocatorBuilder:
    """
    Builds a RowLocator from a DataFrame + boolean mask + DKO.

    Usage:
      mask = df['Price'] == df['Price'].max()
      locator = LocatorBuilder().build(df, mask, dko)
    """

    def build(self, df: pd.DataFrame, mask: pd.Series, dko: Any = None) -> RowLocator:
        """
        Build the most stable locator possible for the rows selected by `mask`.

        Args:
          df:   Full dataset DataFrame.
          mask: Boolean Series selecting target rows (same index as df).
          dko:  DatasetKnowledgeObject — used to detect PK columns. May be None.

        Returns:
          RowLocator with the highest available stability strategy.
        """
        subset = df[mask]
        if subset.empty:
            return RowLocator(
                strategy=LocatorStrategy.POSITION,
                fallback_indices=[],
                is_stable=False,
            )

        fallback_indices = subset.index.tolist()

        # Strategy 1: primary key from DKO
        pk_col = self._detect_primary_key(dko, df)
        if pk_col:
            try:
                pk_values = subset[pk_col].tolist()
                return RowLocator(
                    strategy=LocatorStrategy.PRIMARY_KEY,
                    primary_key={pk_col: pk_values},
                    row_hashes=self._compute_hashes(subset),
                    fallback_indices=fallback_indices,
                    is_stable=True,
                )
            except Exception as e:
                logger.debug(f"PK locator failed ({pk_col}): {e}")

        # Strategy 2: composite key (multiple identifier columns from DKO)
        composite_cols = self._detect_composite_key(dko, df)
        if composite_cols:
            try:
                composite_values = {
                    col: subset[col].tolist()
                    for col in composite_cols
                    if col in subset.columns
                }
                if composite_values:
                    return RowLocator(
                        strategy=LocatorStrategy.COMPOSITE_KEY,
                        composite_key=composite_values,
                        row_hashes=self._compute_hashes(subset),
                        fallback_indices=fallback_indices,
                        is_stable=True,
                    )
            except Exception as e:
                logger.debug(f"Composite key locator failed: {e}")

        # Strategy 3: row hash (always available)
        try:
            hashes = self._compute_hashes(subset)
            return RowLocator(
                strategy=LocatorStrategy.ROW_HASH,
                row_hashes=hashes,
                fallback_indices=fallback_indices,
                is_stable=True,
            )
        except Exception as e:
            logger.debug(f"Row hash locator failed: {e}")

        # Strategy 4: position fallback (unstable)
        logger.warning("Falling back to position-only locator (unstable)")
        return RowLocator(
            strategy=LocatorStrategy.POSITION,
            fallback_indices=fallback_indices,
            is_stable=False,
        )

    def build_from_filter_expr(
        self, df: pd.DataFrame, filter_expr: str, dko: Any = None
    ) -> RowLocator:
        """
        Build a FILTER_EXPR locator for aggregate evidence (e.g. 'Price == max(Price)').
        Used when the exact rows are defined by a deterministic expression.
        """
        try:
            # Verify the expression is valid by evaluating it now
            result_mask = df.eval(filter_expr)
            subset = df[result_mask]
            return RowLocator(
                strategy=LocatorStrategy.FILTER_EXPR,
                filter_expr=filter_expr,
                row_hashes=self._compute_hashes(subset),
                fallback_indices=subset.index.tolist(),
                is_stable=True,
            )
        except Exception as e:
            logger.warning(f"Filter expr locator failed ({filter_expr}): {e}")
            return self.build(df, pd.Series([False] * len(df), index=df.index), dko)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _detect_primary_key(self, dko: Any, df: pd.DataFrame) -> Optional[str]:
        """
        Detect the primary key column from the DKO.
        Returns the column name if found, else None.
        """
        if dko is None:
            return None
        try:
            # Try DKO column annotations
            for col_name, col_info in dko.columns.items():
                semantic = getattr(col_info, 'semantic_type', None)
                if semantic and 'identifier' in str(semantic).lower():
                    if col_name in df.columns and df[col_name].nunique() == len(df):
                        return col_name
            # Fallback: look for columns with all unique values and 'id' in name
            for col in df.columns:
                if 'id' in col.lower() and df[col].nunique() == len(df):
                    return col
        except Exception:
            pass
        return None

    def _detect_composite_key(self, dko: Any, df: pd.DataFrame) -> List[str]:
        """
        Detect multi-column natural key from DKO.
        Returns list of column names forming the composite key.
        """
        if dko is None:
            return []
        try:
            identifier_cols = []
            for col_name, col_info in dko.columns.items():
                semantic = getattr(col_info, 'semantic_type', None)
                if semantic and 'identifier' in str(semantic).lower():
                    if col_name in df.columns:
                        identifier_cols.append(col_name)
            # Only return if combination is unique
            if len(identifier_cols) >= 2:
                combo_unique = df[identifier_cols].drop_duplicates().shape[0] == len(df)
                if combo_unique:
                    return identifier_cols
        except Exception:
            pass
        return []

    def _compute_hashes(self, subset: pd.DataFrame) -> List[str]:
        """Compute SHA-256 hex digest for each row in the subset."""
        hashes = []
        for _, row in subset.iterrows():
            try:
                row_str = str(sorted(row.to_dict().items()))
                h = hashlib.sha256(row_str.encode('utf-8')).hexdigest()
                hashes.append(h)
            except Exception:
                hashes.append("")
        return hashes
